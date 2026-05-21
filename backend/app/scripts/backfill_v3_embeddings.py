"""
Backfill v3.0 four-column abeyance embeddings using T-VEC.

For every AbeyanceFragmentORM row with any of mask_semantic / mask_topological /
mask_operational still FALSE, this script:

  1. Rebuilds the three embedding texts from already-stored JSONB columns
     (no re-enrichment — uses extracted_entities, topological_neighbourhood,
     operational_fingerprint, failure_mode_tags as-is).
  2. Computes embeddings via TVecService.embed_batch (one HTTP-free in-process
     call covering all texts in the chunk).
  3. Writes emb_semantic / emb_topological / emb_operational + corresponding
     masks. Always recomputes emb_temporal (deterministic sinusoidal).
  4. Commits per chunk so the run is resumable.

Designed for CPU inference on the cloud-demo ARM VM: small chunk size, long
per-batch timeouts (inherited from TVECTIMEOUTSECONDS env).

Run inside the backend container:
    docker compose -f docker-compose.cloud.yml exec pedkai-backend \\
        python -m backend.app.scripts.backfill_v3_embeddings \\
        --tenant pedkai_telco2_01

Flags:
    --tenant       Tenant id to scope the backfill (required).
    --chunk-size   Fragments per DB round-trip (default 8).
    --limit        Cap total fragments processed (default: unlimited).
    --dry-run      Build texts and report counts, skip embedding + writes.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import math
import sys
import time
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import or_, select, update

from backend.app.core.database import async_session_maker
from backend.app.models.abeyance_orm import AbeyanceFragmentORM
from backend.app.services.abeyance.tvec_service import TVecService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("backfill_v3")

SEMANTIC_DIM = 1536
TOPOLOGICAL_DIM = 1536
OPERATIONAL_DIM = 1536
TEMPORAL_DIM = 256


def build_semantic_text(raw_content: str, entities: list[dict]) -> Optional[str]:
    if not raw_content:
        return None
    entity_text = ", ".join(e.get("identifier", "") for e in (entities or [])[:20])
    return f"{raw_content[:1000]} Entities: {entity_text}"


def build_topo_text(entities: list[dict], neighbourhood: dict) -> Optional[str]:
    if not entities:
        return None
    parts = [
        f"{e.get('identifier', '?')} ({e.get('domain', 'unknown')})"
        for e in entities[:20]
    ]
    return f"Network topology context: {', '.join(parts)}"


def build_operational_text(
    failure_modes: list[dict], fingerprint: dict
) -> Optional[str]:
    if not failure_modes:
        return None
    parts = []
    for fm in failure_modes[:5]:
        if isinstance(fm, dict):
            parts.append(
                f"{fm.get('divergence_type', 'unknown')}: {fm.get('rationale', '')}"
            )
    time_bucket = (fingerprint or {}).get("traffic_cycle", {}).get(
        "time_bucket", "unknown"
    )
    parts.append(f"Traffic: {time_bucket}")
    return f"Operational context: {'; '.join(parts)}"


def build_temporal_vector(
    event_time: Optional[datetime], fingerprint: dict
) -> list[float]:
    """Deterministic sinusoidal encoding matching EnrichmentChainV3._build_temporal_vector."""
    if event_time is None:
        event_time = datetime.now(timezone.utc)
    hour = event_time.hour + event_time.minute / 60.0
    dow = event_time.weekday()
    doy = event_time.timetuple().tm_yday
    fp = fingerprint or {}
    change_hours = (fp.get("change_proximity") or {}).get("nearest_change_hours")
    change_prox = (
        math.exp(-(change_hours ** 2) / (2 * 24 ** 2))
        if change_hours is not None
        else 0.0
    )
    upgrade_days = (fp.get("vendor_upgrade") or {}).get("days_since_upgrade")
    upgrade_decay = (
        math.exp(-upgrade_days / 30.0) if upgrade_days is not None else 0.0
    )
    load_ratio = (fp.get("traffic_cycle") or {}).get("load_ratio_vs_baseline") or 0.0
    vec = [0.0] * TEMPORAL_DIM
    for i in range(TEMPORAL_DIM):
        freq = 1 + (i % 32)
        if i < 64:
            vec[i] = math.sin(2 * math.pi * freq * hour / 24)
        elif i < 128:
            vec[i] = math.cos(2 * math.pi * freq * dow / 7)
        elif i < 192:
            vec[i] = math.sin(2 * math.pi * freq * doy / 365)
        else:
            idx = i - 192
            if idx < 21:
                vec[i] = math.sin(2 * math.pi * freq * change_prox)
            elif idx < 42:
                vec[i] = math.cos(2 * math.pi * freq * upgrade_decay)
            else:
                vec[i] = math.sin(2 * math.pi * freq * load_ratio)
    return vec


def _pad_or_trim(vec: list[float], target_dim: int) -> list[float]:
    if len(vec) < target_dim:
        return vec + [0.0] * (target_dim - len(vec))
    return vec[:target_dim]


def _is_zero(vec: list[float]) -> bool:
    return all(v == 0.0 for v in vec)


async def fetch_chunk(session, tenant_id: str, chunk_size: int, after_id):
    stmt = (
        select(AbeyanceFragmentORM)
        .where(AbeyanceFragmentORM.tenant_id == tenant_id)
        .where(
            or_(
                AbeyanceFragmentORM.mask_semantic.is_(False),
                AbeyanceFragmentORM.mask_topological.is_(False),
                AbeyanceFragmentORM.mask_operational.is_(False),
            )
        )
        .order_by(AbeyanceFragmentORM.id)
        .limit(chunk_size)
    )
    if after_id is not None:
        stmt = stmt.where(AbeyanceFragmentORM.id > after_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def process_chunk(
    session, tvec: TVecService, fragments: list, dry_run: bool
) -> dict:
    """Embed up to 3 texts per fragment in a single batch call, then update rows."""
    stats = {"semantic": 0, "topological": 0, "operational": 0, "temporal": 0, "skipped_zero": 0}

    # Plan: collect (fragment_idx, column, text) for every text we need.
    plan: list[tuple[int, str, str]] = []
    for i, frag in enumerate(fragments):
        if not frag.mask_semantic:
            t = build_semantic_text(frag.raw_content or "", frag.extracted_entities or [])
            if t:
                plan.append((i, "semantic", t))
        if not frag.mask_topological:
            t = build_topo_text(
                frag.extracted_entities or [], frag.topological_neighbourhood or {}
            )
            if t:
                plan.append((i, "topological", t))
        if not frag.mask_operational:
            t = build_operational_text(
                frag.failure_mode_tags or [], frag.operational_fingerprint or {}
            )
            if t:
                plan.append((i, "operational", t))

    if dry_run:
        for i, col, _ in plan:
            stats[col] += 1
        for frag in fragments:
            frag_id = frag.id
            stats["temporal"] += 1
            _ = frag_id  # silence linter
        return stats

    # Single batched embedding call for the whole chunk.
    texts = [p[2] for p in plan]
    vectors: list[Optional[list[float]]] = []
    if texts:
        vectors = await tvec.embed_batch(texts)

    # Group results back to fragments.
    DIMS = {"semantic": SEMANTIC_DIM, "topological": TOPOLOGICAL_DIM, "operational": OPERATIONAL_DIM}
    updates: dict[int, dict] = {i: {} for i in range(len(fragments))}
    for (frag_idx, col, _), vec in zip(plan, vectors):
        if vec is None:
            continue
        padded = _pad_or_trim(vec, DIMS[col])
        if _is_zero(padded):
            stats["skipped_zero"] += 1
            continue
        updates[frag_idx][f"emb_{col}"] = padded
        updates[frag_idx][f"mask_{col}"] = True
        stats[col] += 1

    # Always recompute temporal (deterministic, cheap).
    for i, frag in enumerate(fragments):
        updates[i]["emb_temporal"] = build_temporal_vector(
            frag.event_timestamp, frag.operational_fingerprint or {}
        )
        updates[i]["embedding_schema_version"] = 3
        stats["temporal"] += 1

    # Persist.
    for i, frag in enumerate(fragments):
        patch = updates[i]
        if not patch:
            continue
        await session.execute(
            update(AbeyanceFragmentORM)
            .where(AbeyanceFragmentORM.id == frag.id)
            .values(**patch)
        )
    await session.commit()
    return stats


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant", required=True, help="Tenant id (e.g. pedkai_telco2_01)")
    parser.add_argument("--chunk-size", type=int, default=8)
    parser.add_argument("--limit", type=int, default=0, help="0 = unlimited")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    tvec = TVecService()
    totals = {"semantic": 0, "topological": 0, "operational": 0, "temporal": 0, "skipped_zero": 0}
    processed = 0
    after_id = None
    started = time.time()

    logger.info(
        "Backfill starting tenant=%s chunk=%d limit=%s dry_run=%s",
        args.tenant, args.chunk_size, args.limit or "unlimited", args.dry_run,
    )

    while True:
        async with async_session_maker() as session:
            chunk = await fetch_chunk(session, args.tenant, args.chunk_size, after_id)
            if not chunk:
                break
            stats = await process_chunk(session, tvec, chunk, args.dry_run)
        for k, v in stats.items():
            totals[k] += v
        processed += len(chunk)
        after_id = chunk[-1].id
        elapsed = time.time() - started
        rate = processed / elapsed if elapsed > 0 else 0.0
        logger.info(
            "processed=%d (%.2f frag/s) chunk_stats=%s totals=%s",
            processed, rate, stats, totals,
        )
        if args.limit and processed >= args.limit:
            logger.info("Hit --limit=%d, stopping.", args.limit)
            break

    elapsed = time.time() - started
    logger.info(
        "Backfill complete in %.1fs. fragments=%d totals=%s",
        elapsed, processed, totals,
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.warning("Interrupted — partial progress is committed per chunk.")
        sys.exit(130)
