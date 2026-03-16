"""
TSLAM-8B Serving — local text generation for entity extraction and hypothesis.

LLD v3.0 §2.3: vLLM sidecar (GPU primary) or llama-cpp-python (CPU fallback).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

TSLAM_BACKEND = os.environ.get("TSLAM_BACKEND", "auto")
TSLAM_VLLM_URL = os.environ.get("TSLAM_VLLM_URL", "http://localhost:8100")
TSLAM_GGUF_PATH = os.environ.get("TSLAM_GGUF_PATH", "models/tslam-4b-q4_k_m.gguf")
TSLAM_LLAMA_CPP_THREADS = int(os.environ.get("TSLAM_LLAMA_CPP_THREADS", "4"))
TSLAM_CONCURRENCY_VLLM = int(os.environ.get("TSLAM_CONCURRENCY", "8"))
TSLAM_CONCURRENCY_LLAMA = 2
TSLAM_TIMEOUT_VLLM = int(os.environ.get("TSLAM_TIMEOUT_SECONDS", "30"))
TSLAM_TIMEOUT_LLAMA = 60


class TSLAMService:
    """Async interface to TSLAM-8B (vLLM) or TSLAM-4B (llama-cpp fallback)."""

    def __init__(self) -> None:
        self._backend: Optional[str] = None  # "vllm" or "llama_cpp"
        self._llama_model = None
        self._lock = asyncio.Lock()
        self._semaphore: Optional[asyncio.Semaphore] = None
        self._error_count = 0
        self._http_client = httpx.AsyncClient(timeout=TSLAM_TIMEOUT_VLLM)

    async def _detect_backend(self) -> str:
        if TSLAM_BACKEND != "auto":
            return TSLAM_BACKEND
        try:
            resp = await self._http_client.get(f"{TSLAM_VLLM_URL}/health")
            if resp.status_code == 200:
                return "vllm"
        except Exception:
            pass
        if os.path.exists(TSLAM_GGUF_PATH):
            return "llama_cpp"
        return "unavailable"

    async def _ensure_backend(self) -> bool:
        if self._backend is not None:
            return self._backend != "unavailable"
        async with self._lock:
            if self._backend is not None:
                return self._backend != "unavailable"
            self._backend = await self._detect_backend()
            if self._backend == "vllm":
                self._semaphore = asyncio.Semaphore(TSLAM_CONCURRENCY_VLLM)
                logger.info("TSLAM backend: vLLM at %s", TSLAM_VLLM_URL)
            elif self._backend == "llama_cpp":
                self._semaphore = asyncio.Semaphore(TSLAM_CONCURRENCY_LLAMA)
                logger.info("TSLAM backend: llama-cpp-python (CPU fallback)")
            else:
                logger.warning("TSLAM backend: unavailable")
            return self._backend != "unavailable"

    async def _generate_vllm(self, prompt: str, max_tokens: int, temperature: float) -> Optional[str]:
        payload = {
            "model": "tslam-8b",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        try:
            resp = await self._http_client.post(
                f"{TSLAM_VLLM_URL}/v1/chat/completions",
                json=payload,
                timeout=TSLAM_TIMEOUT_VLLM,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except Exception:
            logger.warning("TSLAM vLLM generation failed", exc_info=True)
            self._error_count += 1
            return None

    async def _generate_llama(self, prompt: str, max_tokens: int, temperature: float) -> Optional[str]:
        if self._llama_model is None:
            try:
                from llama_cpp import Llama
                loop = asyncio.get_running_loop()
                self._llama_model = await loop.run_in_executor(
                    None,
                    lambda: Llama(
                        model_path=TSLAM_GGUF_PATH,
                        n_ctx=4096,
                        n_threads=TSLAM_LLAMA_CPP_THREADS,
                        verbose=False,
                    ),
                )
            except Exception:
                logger.error("Failed to load TSLAM-4B GGUF", exc_info=True)
                self._backend = "unavailable"
                return None

        try:
            loop = asyncio.get_running_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: self._llama_model(
                        prompt, max_tokens=max_tokens, temperature=temperature,
                    ),
                ),
                timeout=TSLAM_TIMEOUT_LLAMA,
            )
            return result["choices"][0]["text"]
        except Exception:
            logger.warning("TSLAM llama-cpp generation failed", exc_info=True)
            self._error_count += 1
            return None

    async def generate(
        self, prompt: str, max_tokens: int = 512, temperature: float = 0.1,
    ) -> Optional[str]:
        if not await self._ensure_backend():
            return None
        assert self._semaphore is not None
        async with self._semaphore:
            if self._backend == "vllm":
                return await self._generate_vllm(prompt, max_tokens, temperature)
            else:
                return await self._generate_llama(prompt, max_tokens, temperature)

    async def generate_structured(
        self, prompt: str, schema: dict, max_tokens: int = 512,
    ) -> Optional[dict]:
        full_prompt = (
            f"{prompt}\n\nRespond with valid JSON matching this schema:\n"
            f"{json.dumps(schema, indent=2)}\n\nJSON:"
        )
        raw = await self.generate(full_prompt, max_tokens=max_tokens, temperature=0.1)
        if raw is None:
            self._error_count += 1
            logger.warning("TSLAM structured output missing (raw=None)")
            return None
        # Try robust JSON extraction
        import re
        json_candidates = re.findall(r'{[\s\S]*?}', raw)
        for candidate in json_candidates:
            try:
                parsed = json.loads(candidate)
                # Optionally: validate against schema here
                return parsed
            except Exception:
                continue
        # Fallback: try to fix common issues (e.g., trailing commas)
        try:
            import json5
            parsed = json5.loads(raw)
            return parsed
        except Exception:
            pass
        self._error_count += 1
        logger.warning("TSLAM structured output not valid JSON: %r", raw)
        return None

    async def health(self) -> dict:
        await self._ensure_backend()
        return {
            "backend": self._backend or "unknown",
            "status": "ready" if self._backend not in (None, "unavailable") else "unavailable",
            "error_count": self._error_count,
        }
