"""
T-VEC 1.5B Serving — local SentenceTransformer for telecom-domain embeddings.

LLD v3.0 §2.2: Lazy singleton, ThreadPoolExecutor, micro-batching.
Zero cloud LLM dependency. Zero marginal cost per call.
"""

from __future__ import annotations

import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

logger = logging.getLogger(__name__)

TVEC_MODEL_NAME = os.environ.get("TVEC_MODEL_NAME", "NetoAISolutions/T-VEC")
TVEC_MAX_WORKERS = int(os.environ.get("TVEC_MAX_WORKERS", "2"))
TVEC_TIMEOUT_SECONDS = int(os.environ.get("TVEC_TIMEOUT_SECONDS", "10"))
TVEC_CONCURRENCY = int(os.environ.get("TVEC_CONCURRENCY", "4"))
TVEC_OUTPUT_DIM = 1536


class TVecService:
    """Async interface to T-VEC 1.5B SentenceTransformer.

    Model loaded lazily on first call. Thread pool prevents blocking the
    asyncio event loop during CPU-bound encode() calls.
    """

    def __init__(self) -> None:
        self._model = None
        self._lock = asyncio.Lock()
        self._executor = ThreadPoolExecutor(
            max_workers=TVEC_MAX_WORKERS, thread_name_prefix="tvec"
        )
        self._semaphore = asyncio.Semaphore(TVEC_CONCURRENCY)
        self._error_count = 0

    async def _ensure_model(self) -> bool:
        if self._model is not None:
            return True
        async with self._lock:
            if self._model is not None:
                return True
            try:
                loop = asyncio.get_running_loop()
                self._model = await asyncio.wait_for(
                    loop.run_in_executor(self._executor, self._load_model),
                    timeout=120.0,
                )
                logger.info("T-VEC model loaded: %s", TVEC_MODEL_NAME)
                return True
            except Exception:
                logger.error("T-VEC model loading failed", exc_info=True)
                return False

    @staticmethod
    def _load_model():
        from sentence_transformers import SentenceTransformer
        return SentenceTransformer(TVEC_MODEL_NAME)

    def _encode_sync(self, texts: list[str]) -> list[list[float]]:
        import numpy as np
        embeddings = self._model.encode(texts, normalize_embeddings=True)
        result = []
        for emb in embeddings:
            vec = emb.tolist()
            if len(vec) < TVEC_OUTPUT_DIM:
                vec = vec + [0.0] * (TVEC_OUTPUT_DIM - len(vec))
            elif len(vec) > TVEC_OUTPUT_DIM:
                vec = vec[:TVEC_OUTPUT_DIM]
            result.append(vec)
        return result

    async def embed(self, text: str) -> Optional[list[float]]:
        """Embed a single text. Returns None on failure (mask=FALSE)."""
        async with self._semaphore:
            if not await self._ensure_model():
                return None
            try:
                loop = asyncio.get_running_loop()
                results = await asyncio.wait_for(
                    loop.run_in_executor(self._executor, self._encode_sync, [text]),
                    timeout=TVEC_TIMEOUT_SECONDS,
                )
                return results[0] if results else None
            except asyncio.TimeoutError:
                logger.warning("T-VEC embed timeout (%ds)", TVEC_TIMEOUT_SECONDS)
                self._error_count += 1
                return None
            except Exception:
                logger.warning("T-VEC embed failed", exc_info=True)
                self._error_count += 1
                return None

    async def embed_batch(self, texts: list[str]) -> list[Optional[list[float]]]:
        """Embed multiple texts. Individual failures return None."""
        async with self._semaphore:
            if not await self._ensure_model():
                return [None] * len(texts)
            try:
                loop = asyncio.get_running_loop()
                results = await asyncio.wait_for(
                    loop.run_in_executor(self._executor, self._encode_sync, texts),
                    timeout=TVEC_TIMEOUT_SECONDS * 3,
                )
                return results
            except asyncio.TimeoutError:
                logger.warning("T-VEC batch embed timeout")
                self._error_count += 1
                return [None] * len(texts)
            except Exception:
                logger.warning("T-VEC batch embed failed", exc_info=True)
                self._error_count += 1
                return [None] * len(texts)

    async def health(self) -> dict:
        model_loaded = self._model is not None
        return {
            "model": TVEC_MODEL_NAME,
            "status": "ready" if model_loaded else "not_loaded",
            "error_count": self._error_count,
            "output_dim": TVEC_OUTPUT_DIM,
        }
