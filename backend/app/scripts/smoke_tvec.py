"""
T-VEC smoke test.

Verifies the model loads under the current HF_TOKEN, emits 1536-dim vectors,
and produces semantically sensible cosine similarities on telecom prompts.

Embeddings come back L2-normalised from TVecService, so dot product equals
cosine similarity — no extra normalisation needed.

Run inside the backend container after deploy:
    docker compose -f docker-compose.cloud.yml exec pedkai-backend \\
        python -m backend.app.scripts.smoke_tvec

Exit codes:
    0  — model loaded, dim correct, semantic ordering holds.
    1  — load failed, dim mismatch, or related pair scored lower than unrelated.
"""
from __future__ import annotations

import asyncio
import logging
import sys

from backend.app.services.abeyance.tvec_service import TVEC_OUTPUT_DIM, TVecService

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("smoke_tvec")

# (related_pair, unrelated_pair) — cosine(related) must exceed cosine(unrelated).
CASES = [
    (
        ("5G NR handover failure on cell ENB-1234", "LTE handover failure on cell ENB-5678"),
        ("5G NR handover failure on cell ENB-1234", "Quarterly billing reconciliation report"),
    ),
    (
        ("RAN site outage caused by transport ring fault", "Fibre cut on transport ring near site"),
        ("RAN site outage caused by transport ring fault", "User requested password reset"),
    ),
]


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


async def main() -> int:
    tvec = TVecService()
    texts = [s for related, unrelated in CASES for pair in (related, unrelated) for s in pair]
    logger.info("Embedding %d sample texts (first call downloads/loads the model)...", len(texts))
    vecs = await tvec.embed_batch(texts)

    if any(v is None for v in vecs):
        logger.error("At least one embedding returned None — model failed to load or timed out.")
        return 1

    dim = len(vecs[0])
    if dim != TVEC_OUTPUT_DIM:
        logger.error("Vector dim %d != expected %d", dim, TVEC_OUTPUT_DIM)
        return 1
    logger.info("OK: %d vectors, dim=%d", len(vecs), dim)

    ok = True
    for i, (related, unrelated) in enumerate(CASES):
        base = i * 4
        rel = cosine(vecs[base], vecs[base + 1])
        unrel = cosine(vecs[base + 2], vecs[base + 3])
        logger.info(
            "case %d: related cos=%.3f (%r vs %r), unrelated cos=%.3f (%r vs %r)",
            i + 1, rel, related[0][:40], related[1][:40],
            unrel, unrelated[0][:40], unrelated[1][:40],
        )
        if rel <= unrel:
            logger.error("case %d FAIL: related pair scored no higher than unrelated.", i + 1)
            ok = False

    health = await tvec.health()
    logger.info("Health: %s", health)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
