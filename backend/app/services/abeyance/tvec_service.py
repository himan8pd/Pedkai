"""
T-VEC 1.5B Serving — local SentenceTransformer for telecom-domain embeddings.

LLD v3.0 §2.2: Lazy singleton, ThreadPoolExecutor, micro-batching.
Zero cloud LLM dependency. Zero marginal cost per call.

Environment:
    HF_TOKEN              HuggingFace token. T-VEC is a gated repo; the token's
                          account must have accepted the model conditions.
    HF_HOME               Cache root. Set to a persistent volume in containers
                          so the 6GB weights survive restarts.
    TVEC_MODEL_NAME       HF repo id (default NetoAISolutions/T-VEC).
    TVEC_MAX_WORKERS      Threads owning the model (default 2).
    TVEC_CONCURRENCY      Async semaphore over embed calls (default 4).
    TVEC_TIMEOUT_SECONDS  Single-embed timeout. Defaults are sized for CPU
                          inference of a 1.5B model on ARM — adjust for GPU.
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
TVEC_TIMEOUT_SECONDS = int(os.environ.get("TVEC_TIMEOUT_SECONDS", "60"))
TVEC_CONCURRENCY = int(os.environ.get("TVEC_CONCURRENCY", "4"))
TVEC_LOAD_TIMEOUT_SECONDS = int(os.environ.get("TVEC_LOAD_TIMEOUT_SECONDS", "600"))
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
                    timeout=TVEC_LOAD_TIMEOUT_SECONDS,
                )
                # Probe output dim so silent mismatches fail loud at load,
                # not later in a similarity query.
                probe = await loop.run_in_executor(
                    self._executor, self._encode_sync, ["t-vec startup probe"]
                )
                probe_dim = len(probe[0]) if probe else 0
                if probe_dim != TVEC_OUTPUT_DIM:
                    logger.error(
                        "T-VEC loaded but emits %d-dim vectors (expected %d) — "
                        "schema mismatch will pad/truncate",
                        probe_dim, TVEC_OUTPUT_DIM,
                    )
                logger.info(
                    "T-VEC model loaded: %s (probe_dim=%d)",
                    TVEC_MODEL_NAME, probe_dim,
                )
                return True
            except Exception:
                logger.error("T-VEC model loading failed", exc_info=True)
                return False

    @staticmethod
    def _load_model():
        from sentence_transformers import SentenceTransformer
        import transformers.dynamic_module_utils as _dmu

        # Two-stage flash_attn problem on CPU-only ARM:
        #   1. check_imports() scans the modeling file's top-level imports and
        #      calls importlib.import_module("flash_attn") — fails because
        #      flash_attn requires CUDA and isn't installed.
        #   2. The modeling code itself guards flash_attn behind
        #      is_flash_attn_2_available() and falls back to standard attention
        #      when it returns False — which it does naturally when flash_attn
        #      is absent.
        # Monkey-patching check_imports to tolerate the missing flash_attn lets
        # stage 2 work correctly: the model sees flash_attn is unavailable and
        # uses PyTorch SDPA instead.
        _original_check_imports = _dmu.check_imports

        def _lenient_check_imports(filename):
            try:
                return _original_check_imports(filename)
            except ImportError as exc:
                if "flash_attn" in str(exc):
                    return _dmu.get_relative_imports(filename)
                raise

        _dmu.check_imports = _lenient_check_imports
        try:
            return SentenceTransformer(
                TVEC_MODEL_NAME,
                trust_remote_code=True,
                model_kwargs={"attn_implementation": "eager"},
            )
        finally:
            _dmu.check_imports = _original_check_imports

    def _encode_sync(self, texts: list[str]) -> list[list[float]]:
        embeddings = self._model.encode(texts, normalize_embeddings=True)
        result = []
        for emb in embeddings:
            vec = emb.tolist()
            actual = len(vec)
            if actual != TVEC_OUTPUT_DIM:
                # Defensive: a correctly-loaded T-VEC emits exactly
                # TVEC_OUTPUT_DIM. Hitting this branch means the loader
                # picked up the wrong model — log once per occurrence.
                logger.warning(
                    "T-VEC dim mismatch: got %d, expected %d — padding/truncating",
                    actual, TVEC_OUTPUT_DIM,
                )
                if actual < TVEC_OUTPUT_DIM:
                    vec = vec + [0.0] * (TVEC_OUTPUT_DIM - actual)
                else:
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
