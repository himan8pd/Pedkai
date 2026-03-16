# T1.5 — Cold Storage Redesign
**Phase**: 1 | **Task**: T1.5 | **Status**: COMPLETE
**Date**: 2026-03-16
**Audit Findings Addressed**: F-3.4, F-5.4, F-6.3, F-8.2, F-9.1

---

## 1. Problem Statement

The v2.0 cold storage implementation has five compounding defects:

| Finding | Severity | Description |
|---------|----------|-------------|
| F-3.4 | Moderate | Dual backends (PostgreSQL + Parquet) with different schemas, different embedding dimensionalities, and no synchronisation. No reconciliation path. |
| F-5.4 | Moderate | IVFFlat `lists` parameter hard-coded at 100. As `cold_fragment` grows, recall degrades because the optimal list count is `ceil(sqrt(n))`. Weekly rebuild triggers on 20% row-count change but does not recompute `lists`. |
| F-6.3 | Moderate | `_load_tenant_fragments()` swallows every exception with a bare `except: continue`. Corrupted Parquet files produce incomplete search results with no operator visibility. |
| F-8.2 | Moderate | Fragments expire from hot storage after up to 730 days, then enter cold with no retention limit. At 10 K events/min for 2 years the table reaches 10.5 B rows. No tiered retirement policy exists. |
| F-9.1 | Severe | `cold_storage_path()` inserts raw `tenant_id` into a `Path`. A tenant_id of `../../etc` causes `rglob` to escape the intended base directory. No sanitisation. |

The v3.0 redesign also migrates the single `enriched_embedding` column (Vector(1536)) to a four-column T-VEC schema aligned with the embedding architecture introduced in T1.2/T1.3.

---

## 2. Embedding Architecture Reference

The T-VEC model decomposes the enriched embedding into four semantically distinct sub-vectors:

| Column | Dimension | Source | Mask column |
|--------|-----------|--------|-------------|
| `emb_semantic` | 1536 | LLM text embedding of `raw_content` | `mask_semantic` |
| `emb_topological` | 1536 | LLM embedding of `_build_topo_text()` output | `mask_topological` |
| `emb_temporal` | 256 | Deterministic `_build_temporal_vector()` | — (never masked; always computable) |
| `emb_operational` | 1536 | LLM embedding of `_build_operational_text()` output | `mask_operational` |

Masks are `Boolean DEFAULT FALSE`. A mask value of `TRUE` means the sub-vector was not produced by the LLM at archive time and contains zeros. The search strategy must consult masks before scoring (see §6).

---

## 3. ColdFragmentORM — v3.0 Schema

```python
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean, Column, DateTime, Float, Index, String, Text, func, text
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from pgvector.sqlalchemy import Vector

from backend.app.core.database import Base

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

COLD_SEARCH_DEFAULT_K: int = 20
MAX_COLD_BATCH: int = 5_000

# Embedding dimensions (must match enrichment_chain.py T-VEC definitions)
SEMANTIC_DIM: int = 1536
TOPOLOGICAL_DIM: int = 1536
TEMPORAL_DIM: int = 256
OPERATIONAL_DIM: int = 1536

# Expiration tiers (days since archived_at)
COLD_TIER1_DAYS: int = 365        # standard fragments — compress summary
COLD_TIER2_DAYS: int = 730        # tombstone — drop embeddings, keep metadata
COLD_TIER3_DAYS: int = 1095       # permanent deletion eligible

# Tenant ID sanitisation pattern: only alphanumeric, hyphen, underscore
_TENANT_ID_SAFE_RE = re.compile(r'^[a-zA-Z0-9_-]{1,128}$')


# ---------------------------------------------------------------------------
# ORM
# ---------------------------------------------------------------------------

class ColdFragmentORM(Base):
    """Archived fragment with four-column T-VEC embedding schema.

    Replaces the single enriched_embedding(1536) column with four typed
    sub-vectors that mirror the hot-store AbeyanceFragmentORM T-VEC layout.
    Three Boolean mask columns track LLM availability at archive time.
    """

    __tablename__ = "cold_fragment"

    # --- Identity ---
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(String(128), nullable=False)
    original_fragment_id = Column(PG_UUID(as_uuid=True), nullable=False)

    # --- Content summary ---
    source_type = Column(String(50), nullable=False)
    raw_content_summary = Column(Text, nullable=True)      # first 500 chars only (INV-6)
    extracted_entities = Column(JSONB, nullable=False, default=list, server_default='[]')
    failure_mode_tags = Column(JSONB, nullable=False, default=list, server_default='[]')

    # --- T-VEC embedding columns ---
    emb_semantic = Column(Vector(SEMANTIC_DIM), nullable=True)
    emb_topological = Column(Vector(TOPOLOGICAL_DIM), nullable=True)
    emb_temporal = Column(Vector(TEMPORAL_DIM), nullable=True)
    emb_operational = Column(Vector(OPERATIONAL_DIM), nullable=True)

    # --- Embedding validity masks ---
    # TRUE = sub-vector was unavailable (LLM offline) at archive time; contains zeros
    mask_semantic = Column(Boolean, nullable=False, default=False, server_default='false')
    mask_topological = Column(Boolean, nullable=False, default=False, server_default='false')
    mask_operational = Column(Boolean, nullable=False, default=False, server_default='false')
    # emb_temporal has no mask: it is computed deterministically from timestamps

    # --- Provenance timestamps ---
    event_timestamp = Column(DateTime(timezone=True), nullable=True)
    archived_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )
    original_created_at = Column(DateTime(timezone=True), nullable=True)

    # --- Archive state ---
    original_decay_score = Column(Float, nullable=False, default=0.0)
    snap_status_at_archive = Column(String(20), nullable=False, default="EXPIRED")

    # --- Expiration tier (F-8.2) ---
    # Populated/updated by the expiration job. Values: ACTIVE, COMPRESSED, TOMBSTONED
    expiration_tier = Column(String(20), nullable=False, default="ACTIVE", server_default="'ACTIVE'")
    expires_at = Column(DateTime(timezone=True), nullable=True)  # set at archive time

    # -------------------------------------------------------------------
    # Indexes
    # -------------------------------------------------------------------
    __table_args__ = (
        # Scalar lookup indexes
        Index("ix_cold_frag_tenant",    "tenant_id"),
        Index("ix_cold_frag_original",  "original_fragment_id"),
        Index("ix_cold_frag_archived",  "tenant_id", "archived_at"),
        Index("ix_cold_frag_expires",   "expiration_tier", "expires_at"),

        # IVFFlat ANN indexes — one per T-VEC column.
        # lists parameter is set to ceil(sqrt(expected_n)) at index-creation
        # time and is rebuilt periodically (see §5). The placeholder value
        # 100 is for initial DDL only; the rebuild procedure sets the correct
        # value based on actual row counts.
        #
        # NOTE: these cannot be expressed as SQLAlchemy Index() objects
        # because IVFFlat requires the vector_cosine_ops operator class.
        # They are created via Alembic raw SQL (see §7).
        #
        # CREATE INDEX CONCURRENTLY ix_cold_emb_semantic
        #   ON cold_fragment USING ivfflat (emb_semantic vector_cosine_ops)
        #   WITH (lists = 100)
        #   WHERE mask_semantic = false;
        #
        # CREATE INDEX CONCURRENTLY ix_cold_emb_topological
        #   ON cold_fragment USING ivfflat (emb_topological vector_cosine_ops)
        #   WITH (lists = 100)
        #   WHERE mask_topological = false;
        #
        # CREATE INDEX CONCURRENTLY ix_cold_emb_temporal
        #   ON cold_fragment USING ivfflat (emb_temporal vector_cosine_ops)
        #   WITH (lists = 100);
        #
        # CREATE INDEX CONCURRENTLY ix_cold_emb_operational
        #   ON cold_fragment USING ivfflat (emb_operational vector_cosine_ops)
        #   WITH (lists = 100)
        #   WHERE mask_operational = false;
    )
```

---

## 4. IVFFlat Index Strategy (F-5.4)

### 4.1 List Count Formula

The optimal IVFFlat `lists` parameter for recall is `ceil(sqrt(n))` where `n` is the number of indexable rows. The current implementation uses a hard-coded value of 100, which becomes increasingly inaccurate as the table grows.

```python
import math

def compute_ivfflat_lists(row_count: int, min_lists: int = 10, max_lists: int = 4096) -> int:
    """Return ceil(sqrt(n)) clamped to [min_lists, max_lists].

    pgvector documentation recommends lists = rows / 1000 for tables over 1M
    rows, which is equivalent to sqrt(n) at n ≈ 1M. We use sqrt(n) universally
    for consistency and simplicity.
    """
    if row_count <= 0:
        return min_lists
    return max(min_lists, min(max_lists, math.ceil(math.sqrt(row_count))))
```

### 4.2 Partial Indexes on Mask Columns

Each embedding-column IVFFlat index carries a `WHERE mask_X = false` partial index predicate. This has two benefits:

1. Rows with zero-filled embeddings (LLM unavailable at archive time) are excluded from the index. Including them would degrade recall because zero vectors contaminate cosine distance rankings.
2. The effective `n` for list-count computation is the count of *indexable* (unmasked) rows, not total rows.

`emb_temporal` has no mask and no partial predicate because it is always computed deterministically.

### 4.3 Rebuild Procedure

The index rebuild procedure is called by the weekly maintenance job. It must:

1. Count unmasked rows per embedding column.
2. Compute `new_lists = compute_ivfflat_lists(unmasked_count)`.
3. Compare with the current `lists` value stored in `pg_index` / `pg_opclass_options`.
4. If `|new_lists - current_lists| / current_lists > 0.20`, rebuild the index with `CREATE INDEX CONCURRENTLY ... WITH (lists = new_lists)` then `DROP INDEX` on the old one.

```python
async def rebuild_ivfflat_index_if_needed(
    session: AsyncSession,
    column_name: str,          # e.g. "emb_semantic"
    mask_column: str | None,   # e.g. "mask_semantic"; None for emb_temporal
    index_name: str,           # e.g. "ix_cold_emb_semantic"
    operator_class: str = "vector_cosine_ops",
) -> dict:
    """
    Rebuild IVFFlat index if row count has drifted >20% from last build.

    Returns:
        {
            "rebuilt": bool,
            "old_lists": int | None,
            "new_lists": int,
            "unmasked_count": int,
        }
    """
    import math

    # Count indexable rows
    if mask_column:
        count_sql = text(
            f"SELECT COUNT(*) FROM cold_fragment WHERE {mask_column} = false"
        )
    else:
        count_sql = text("SELECT COUNT(*) FROM cold_fragment")

    result = await session.execute(count_sql)
    unmasked_count: int = result.scalar_one()
    new_lists = compute_ivfflat_lists(unmasked_count)

    # Read current lists from pg_indexes (approximate via pg_opclass_options)
    current_lists_sql = text("""
        SELECT (regexp_match(indexdef, 'lists\s*=\s*(\d+)'))[1]::int AS lists
        FROM pg_indexes
        WHERE indexname = :idx_name
    """)
    cur = await session.execute(current_lists_sql, {"idx_name": index_name})
    row = cur.fetchone()
    old_lists: int | None = row[0] if row else None

    if old_lists is not None:
        drift = abs(new_lists - old_lists) / max(old_lists, 1)
        if drift <= 0.20:
            return {"rebuilt": False, "old_lists": old_lists,
                    "new_lists": new_lists, "unmasked_count": unmasked_count}

    # Rebuild
    tmp_index = f"{index_name}_new"
    where_clause = f"WHERE {mask_column} = false" if mask_column else ""
    await session.execute(text(
        f"CREATE INDEX CONCURRENTLY {tmp_index} "
        f"ON cold_fragment USING ivfflat ({column_name} {operator_class}) "
        f"WITH (lists = {new_lists}) {where_clause}"
    ))
    await session.execute(text(f"DROP INDEX CONCURRENTLY {index_name}"))
    await session.execute(text(f"ALTER INDEX {tmp_index} RENAME TO {index_name}"))

    logger.info(
        "Rebuilt IVFFlat index %s: lists %s -> %d (unmasked rows: %d)",
        index_name, old_lists, new_lists, unmasked_count,
    )
    return {"rebuilt": True, "old_lists": old_lists,
            "new_lists": new_lists, "unmasked_count": unmasked_count}
```

---

## 5. Search Strategy

### 5.1 Default Search: emb_semantic Primary

The default cold-store query uses `emb_semantic` only. This matches the hot-store snap engine's primary scoring axis and provides the lowest-latency ANN path.

```python
async def search_db(
    self,
    session: AsyncSession,
    tenant_id: str,
    query_embedding: list[float],        # must be SEMANTIC_DIM = 1536
    top_k: int = COLD_SEARCH_DEFAULT_K,
) -> list[ColdFragmentORM]:
    """ANN search over emb_semantic (default path).

    Only queries rows where mask_semantic = false (valid embeddings).
    The IVFFlat partial index on emb_semantic WHERE mask_semantic = false
    will be used automatically.
    """
    from pgvector.sqlalchemy import Vector
    stmt = (
        select(ColdFragmentORM)
        .where(ColdFragmentORM.tenant_id == tenant_id)
        .where(ColdFragmentORM.mask_semantic.is_(False))
        .where(ColdFragmentORM.emb_semantic.isnot(None))
        .where(ColdFragmentORM.expiration_tier != "TOMBSTONED")
        .order_by(ColdFragmentORM.emb_semantic.cosine_distance(query_embedding))
        .limit(top_k)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())
```

### 5.2 Multi-Index Fusion (Optional)

When the caller provides multiple query vectors (e.g. during hypothesis re-hydration), results from multiple T-VEC indexes can be fused using reciprocal rank fusion (RRF). This is an optional call path; the default path always uses `emb_semantic` alone.

```python
async def search_db_multi_index(
    self,
    session: AsyncSession,
    tenant_id: str,
    query_semantic: list[float] | None = None,    # dim 1536
    query_topological: list[float] | None = None, # dim 1536
    query_temporal: list[float] | None = None,    # dim 256
    query_operational: list[float] | None = None, # dim 1536
    top_k: int = COLD_SEARCH_DEFAULT_K,
    rrf_k: int = 60,
) -> list[tuple[ColdFragmentORM, float]]:
    """Multi-index ANN search with Reciprocal Rank Fusion.

    Each provided query vector is issued as a separate ANN query. Results
    are merged by RRF score: score(d) = sum(1 / (rrf_k + rank_i(d))).

    Rules:
    - Only issue a sub-query when the corresponding mask column is false
      (or when the column has no mask, i.e. emb_temporal).
    - A sub-query is skipped entirely if the caller does not supply the
      corresponding query vector.
    - At least one sub-query must execute; if all vectors are None, falls
      back to search_db() with an error log.

    Returns list of (ColdFragmentORM, rrf_score) sorted descending.
    """
    candidate_sets: list[list[ColdFragmentORM]] = []

    if query_semantic is not None:
        rows = await self._ann_query(
            session, tenant_id,
            column=ColdFragmentORM.emb_semantic,
            mask_column=ColdFragmentORM.mask_semantic,
            query=query_semantic,
            fetch=top_k * 4,
        )
        candidate_sets.append(rows)

    if query_topological is not None:
        rows = await self._ann_query(
            session, tenant_id,
            column=ColdFragmentORM.emb_topological,
            mask_column=ColdFragmentORM.mask_topological,
            query=query_topological,
            fetch=top_k * 4,
        )
        candidate_sets.append(rows)

    if query_temporal is not None:
        rows = await self._ann_query(
            session, tenant_id,
            column=ColdFragmentORM.emb_temporal,
            mask_column=None,           # no mask on temporal
            query=query_temporal,
            fetch=top_k * 4,
        )
        candidate_sets.append(rows)

    if query_operational is not None:
        rows = await self._ann_query(
            session, tenant_id,
            column=ColdFragmentORM.emb_operational,
            mask_column=ColdFragmentORM.mask_operational,
            query=query_operational,
            fetch=top_k * 4,
        )
        candidate_sets.append(rows)

    if not candidate_sets:
        logger.error(
            "search_db_multi_index called with no query vectors for tenant %s; "
            "falling back to empty result",
            tenant_id,
        )
        return []

    # RRF merge
    scores: dict[UUID, float] = {}
    frags: dict[UUID, ColdFragmentORM] = {}
    for ranked_list in candidate_sets:
        for rank, frag in enumerate(ranked_list, start=1):
            fid = frag.id
            scores[fid] = scores.get(fid, 0.0) + 1.0 / (rrf_k + rank)
            frags[fid] = frag

    merged = sorted(frags.values(), key=lambda f: scores[f.id], reverse=True)
    return [(f, scores[f.id]) for f in merged[:top_k]]

async def _ann_query(
    self,
    session: AsyncSession,
    tenant_id: str,
    column,
    mask_column,
    query: list[float],
    fetch: int,
) -> list[ColdFragmentORM]:
    stmt = (
        select(ColdFragmentORM)
        .where(ColdFragmentORM.tenant_id == tenant_id)
        .where(ColdFragmentORM.expiration_tier != "TOMBSTONED")
        .where(column.isnot(None))
        .order_by(column.cosine_distance(query))
        .limit(fetch)
    )
    if mask_column is not None:
        stmt = stmt.where(mask_column.is_(False))
    result = await session.execute(stmt)
    return list(result.scalars().all())
```

### 5.3 Search Exclusion Rules

A row is excluded from all search paths if:
- `expiration_tier = 'TOMBSTONED'` (embeddings have been dropped)
- The relevant mask column is `TRUE` (zero embedding; default search path)
- The embedding column is `NULL`

---

## 6. Expiration Policy (F-8.2)

### 6.1 Retention Tiers

Growth model: 10 K events/min × 60 min/hr × 24 hr/day = 14.4 M rows/day. Without a retirement policy, a two-year deployment accumulates ~10.5 B rows.

The v3.0 policy uses three age-based tiers computed relative to `archived_at`:

| Tier | Age Threshold | Action | Retained columns | Embedding status |
|------|---------------|--------|-----------------|-----------------|
| ACTIVE | 0 – 364 days | No action | All columns | All T-VEC columns intact |
| COMPRESSED | 365 – 729 days | Compress summary; clear raw_content_summary | Embeddings, metadata, timestamps | All T-VEC columns intact (still searchable) |
| TOMBSTONED | 730 – 1094 days | Drop all embedding columns | tenant_id, original_fragment_id, source_type, failure_mode_tags, event_timestamp, snap_status_at_archive, archived_at | All four T-VEC columns set NULL; excluded from search |
| DELETED | >= 1095 days | Hard DELETE | — | Row removed |

### 6.2 `expires_at` Column

`expires_at` is set at archive time to `archived_at + COLD_TIER3_DAYS` (i.e. 1095 days). This allows a simple index scan to identify deletion-eligible rows without computing `NOW() - archived_at` in the expiration job.

### 6.3 Expiration Job Interface

```python
async def run_expiration_pass(
    self,
    session: AsyncSession,
    tenant_id: str,
    dry_run: bool = False,
) -> dict:
    """Advance fragments through expiration tiers.

    Processed in reverse-severity order so a single pass handles all tiers.
    Returns counts per tier action for observability.

    Counters emitted (all prefixed cold_storage_expiration_):
      .deleted_total
      .tombstoned_total
      .compressed_total
      .errors_total
    """
    now = datetime.now(timezone.utc)
    counts = {"deleted": 0, "tombstoned": 0, "compressed": 0, "errors": 0}

    # --- Tier 4: Hard DELETE (>= COLD_TIER3_DAYS) ---
    try:
        delete_cutoff = now - timedelta(days=COLD_TIER3_DAYS)
        if not dry_run:
            del_result = await session.execute(
                text("""
                    DELETE FROM cold_fragment
                    WHERE tenant_id = :tid
                      AND archived_at < :cutoff
                      AND expiration_tier = 'TOMBSTONED'
                """),
                {"tid": tenant_id, "cutoff": delete_cutoff},
            )
            counts["deleted"] = del_result.rowcount
        else:
            count_result = await session.execute(
                text("""
                    SELECT COUNT(*) FROM cold_fragment
                    WHERE tenant_id = :tid
                      AND archived_at < :cutoff
                      AND expiration_tier = 'TOMBSTONED'
                """),
                {"tid": tenant_id, "cutoff": delete_cutoff},
            )
            counts["deleted"] = count_result.scalar_one()
    except Exception:
        logger.exception(
            "Expiration DELETE pass failed for tenant %s", tenant_id
        )
        counts["errors"] += 1

    # --- Tier 3: TOMBSTONE (730 – 1094 days) ---
    try:
        tombstone_cutoff = now - timedelta(days=COLD_TIER2_DAYS)
        if not dry_run:
            ts_result = await session.execute(
                text("""
                    UPDATE cold_fragment
                    SET expiration_tier = 'TOMBSTONED',
                        emb_semantic = NULL,
                        emb_topological = NULL,
                        emb_temporal = NULL,
                        emb_operational = NULL,
                        raw_content_summary = NULL
                    WHERE tenant_id = :tid
                      AND archived_at < :cutoff
                      AND expiration_tier = 'COMPRESSED'
                """),
                {"tid": tenant_id, "cutoff": tombstone_cutoff},
            )
            counts["tombstoned"] = ts_result.rowcount
    except Exception:
        logger.exception(
            "Expiration TOMBSTONE pass failed for tenant %s", tenant_id
        )
        counts["errors"] += 1

    # --- Tier 2: COMPRESS (365 – 729 days) ---
    try:
        compress_cutoff = now - timedelta(days=COLD_TIER1_DAYS)
        if not dry_run:
            comp_result = await session.execute(
                text("""
                    UPDATE cold_fragment
                    SET expiration_tier = 'COMPRESSED',
                        raw_content_summary = NULL
                    WHERE tenant_id = :tid
                      AND archived_at < :cutoff
                      AND expiration_tier = 'ACTIVE'
                """),
                {"tid": tenant_id, "cutoff": compress_cutoff},
            )
            counts["compressed"] = comp_result.rowcount
    except Exception:
        logger.exception(
            "Expiration COMPRESS pass failed for tenant %s", tenant_id
        )
        counts["errors"] += 1

    logger.info(
        "Expiration pass tenant=%s dry_run=%s: deleted=%d tombstoned=%d "
        "compressed=%d errors=%d",
        tenant_id, dry_run,
        counts["deleted"], counts["tombstoned"],
        counts["compressed"], counts["errors"],
    )
    return counts
```

### 6.4 Retention Policy Configuration

Retention thresholds are configurable via environment variables so operators can tune without code changes:

| Env var | Default | Description |
|---------|---------|-------------|
| `COLD_TIER1_DAYS` | 365 | Days before ACTIVE → COMPRESSED |
| `COLD_TIER2_DAYS` | 730 | Days before COMPRESSED → TOMBSTONED |
| `COLD_TIER3_DAYS` | 1095 | Days before TOMBSTONED → DELETE |

The service reads these on construction:

```python
def __init__(self) -> None:
    self._tier1_days = int(os.environ.get("COLD_TIER1_DAYS", COLD_TIER1_DAYS))
    self._tier2_days = int(os.environ.get("COLD_TIER2_DAYS", COLD_TIER2_DAYS))
    self._tier3_days = int(os.environ.get("COLD_TIER3_DAYS", COLD_TIER3_DAYS))
```

---

## 7. Tenant ID Sanitisation in Parquet Path Construction (F-9.1)

The Parquet fallback path constructs a filesystem path from `tenant_id`. The existing code passes the raw string directly to `Path`, enabling directory traversal attacks such as `tenant_id = "../../etc/passwd"`.

### 7.1 Sanitisation Function

```python
def _sanitise_tenant_id(self, tenant_id: str) -> str:
    """Validate and return a filesystem-safe tenant_id.

    Accepts only alphanumeric characters, hyphens, and underscores,
    with a maximum length of 128 characters. This matches the tenant_id
    column constraint on ColdFragmentORM.

    Raises:
        ValueError: if tenant_id contains any disallowed characters or
                    exceeds maximum length. The caller must treat this as
                    a security event and must NOT fall through to any
                    default path.
    """
    if not tenant_id:
        raise ValueError("tenant_id must not be empty")
    if not _TENANT_ID_SAFE_RE.match(tenant_id):
        logger.error(
            "SECURITY: tenant_id failed sanitisation check: %r "
            "(contains path-traversal characters or exceeds length limit)",
            tenant_id,
        )
        raise ValueError(
            f"tenant_id contains disallowed characters: {tenant_id!r}"
        )
    return tenant_id
```

### 7.2 Updated `cold_storage_path`

```python
def cold_storage_path(self, tenant_id: str, year: int, month: int) -> Path:
    """Return a safe, deterministic Parquet path for (tenant, year, month).

    Sanitises tenant_id before constructing the path. Raises ValueError
    on a malformed tenant_id; callers must not catch and suppress this.
    """
    safe_tid = self._sanitise_tenant_id(tenant_id)
    return (
        self.base_path
        / safe_tid
        / str(year)
        / f"{month:02d}"
        / "fragments.parquet"
    )
```

### 7.3 Updated `_load_tenant_fragments` with Logging (F-6.3 / F-3.4)

The bare `except: continue` in `_load_tenant_fragments` is replaced with structured logging and a counter. This addresses both F-6.3 (silent error suppression) and the observability gap from F-3.4.

```python
def _load_tenant_fragments(
    self, tenant_id: str | None = None
) -> list[AbeyanceFragment]:
    """Load Parquet cold files for a tenant.

    Sanitises tenant_id before path construction (F-9.1).
    Logs and counts every file-load error (F-6.3).
    """
    results: list[AbeyanceFragment] = []
    parquet_errors: int = 0

    if tenant_id is not None:
        try:
            safe_tid = self._sanitise_tenant_id(tenant_id)
        except ValueError:
            # Security: do not fall through to base_path rglob
            logger.error(
                "SECURITY: Rejected Parquet load for unsafe tenant_id %r",
                tenant_id,
            )
            _COLD_PARQUET_ERRORS.inc()  # Prometheus counter (see §9)
            return []
        search_root = self.base_path / safe_tid
    else:
        search_root = self.base_path

    if not search_root.exists():
        return []

    for parquet_file in search_root.rglob("*.parquet"):
        try:
            df = pd.read_parquet(parquet_file)
            for _, row in df.iterrows():
                emb = row["embedding"]
                emb_list = list(emb) if isinstance(emb, (list, np.ndarray)) else list(emb)
                results.append(AbeyanceFragment(
                    fragment_id=str(row["fragment_id"]),
                    tenant_id=str(row["tenant_id"]),
                    embedding=emb_list,
                    created_at=str(row["created_at"]),
                    decay_score=float(row.get("decay_score", 1.0)),
                    status=str(row.get("status", "ACTIVE")),
                    corroboration_count=int(row.get("corroboration_count", 0)),
                ))
        except Exception:
            parquet_errors += 1
            logger.warning(
                "Failed to load Parquet file %s (tenant=%s); "
                "skipping. Total errors this call: %d",
                parquet_file, tenant_id, parquet_errors,
                exc_info=True,
            )
            _COLD_PARQUET_ERRORS.inc()

    if parquet_errors > 0:
        logger.error(
            "Parquet load completed with %d file errors for tenant=%s. "
            "Results may be incomplete.",
            parquet_errors, tenant_id,
        )

    return results
```

---

## 8. Dual-Backend Synchronisation (F-3.4)

### 8.1 Problem

v2.0 has two independent backends:
- **PostgreSQL path**: `ColdFragmentORM` with `enriched_embedding(1536)`
- **Parquet path**: `AbeyanceFragment` dataclass with a flat `embedding: list`

They have different schemas, different dimensionalities (Vector(1536) vs. whatever the enrichment chain produced at write time), and the Parquet path silently swallowed all errors. There is no reconciliation mechanism.

### 8.2 v3.0 Resolution

The dual-backend architecture is **retained** for its degraded-mode value, but the design contract is clarified and enforced:

1. **PostgreSQL is canonical**. The Parquet path is explicitly a degraded fallback only, not a primary storage path. The `archive_fragment()` method must only be called from `archive_to_db()`'s exception handler.

2. **Schema alignment in Parquet**: The Parquet fallback now writes all four T-VEC columns as separate list columns: `emb_semantic`, `emb_topological`, `emb_temporal`, `emb_operational`, plus the three mask columns. The flat `embedding` column is retired.

3. **Write path**: `archive_to_db()` is the authoritative write path. If the DB session fails, the service logs the failure (not silently swallows it) and, if the fallback is enabled via `COLD_STORAGE_FALLBACK_ENABLED=true`, writes to Parquet with an explicit warning log.

4. **No reconciliation on search**: The `search_cold()` Parquet path is only invoked when the DB session is explicitly unavailable. It is never called as a supplement to `search_db()`. The caller decides which path to use.

```python
async def archive_to_db(
    self,
    session: AsyncSession,
    fragment,  # AbeyanceFragmentORM v3.0
    tenant_id: str,
) -> ColdFragmentORM:
    """Archive a fragment to cold_fragment table (canonical path).

    Falls back to Parquet only if COLD_STORAGE_FALLBACK_ENABLED=true
    and the DB write raises an exception. Fallback is logged at ERROR
    level, not silently swallowed.
    """
    from datetime import timedelta

    expires_at = datetime.now(timezone.utc) + timedelta(days=self._tier3_days)

    cold = ColdFragmentORM(
        id=uuid4(),
        tenant_id=tenant_id,
        original_fragment_id=fragment.id,
        source_type=fragment.source_type,
        raw_content_summary=(fragment.raw_content or "")[:500],
        extracted_entities=fragment.extracted_entities or [],
        failure_mode_tags=fragment.failure_mode_tags or [],
        emb_semantic=fragment.emb_semantic,
        emb_topological=fragment.emb_topological,
        emb_temporal=fragment.emb_temporal,
        emb_operational=fragment.emb_operational,
        mask_semantic=fragment.mask_semantic,
        mask_topological=fragment.mask_topological,
        mask_operational=fragment.mask_operational,
        event_timestamp=fragment.event_timestamp,
        original_created_at=fragment.created_at,
        original_decay_score=fragment.current_decay_score,
        snap_status_at_archive=fragment.snap_status,
        expiration_tier="ACTIVE",
        expires_at=expires_at,
    )
    try:
        session.add(cold)
        await session.flush()
        logger.info("Archived fragment %s to cold storage (DB)", fragment.id)
        _COLD_ARCHIVE_SUCCESS.inc()
        return cold
    except Exception:
        _COLD_ARCHIVE_DB_ERRORS.inc()
        logger.error(
            "DB archive failed for fragment %s tenant=%s",
            fragment.id, tenant_id,
            exc_info=True,
        )
        fallback_enabled = os.environ.get(
            "COLD_STORAGE_FALLBACK_ENABLED", "false"
        ).lower() == "true"
        if fallback_enabled:
            logger.warning(
                "Falling back to Parquet for fragment %s (degraded mode)",
                fragment.id,
            )
            self._archive_fragment_parquet_v3(fragment, tenant_id)
        raise
```

---

## 9. Observability Counters (F-6.3, F-3.4)

All counters use Prometheus `Counter` semantics. They are registered in the module-level scope so they survive across service method calls.

```python
# Declared at module level in cold_storage.py
try:
    from prometheus_client import Counter
    _COLD_ARCHIVE_SUCCESS = Counter(
        "cold_storage_archive_success_total",
        "Fragments successfully archived to DB cold storage",
        ["tenant_id"],
    )
    _COLD_ARCHIVE_DB_ERRORS = Counter(
        "cold_storage_archive_db_errors_total",
        "DB errors during cold storage archival",
        ["tenant_id"],
    )
    _COLD_PARQUET_ERRORS = Counter(
        "cold_storage_parquet_errors_total",
        "Parquet file load errors in cold storage fallback",
        ["tenant_id"],
    )
    _COLD_EXPIRATION_DELETED = Counter(
        "cold_storage_expiration_deleted_total",
        "Rows hard-deleted by expiration job",
        ["tenant_id"],
    )
    _COLD_EXPIRATION_TOMBSTONED = Counter(
        "cold_storage_expiration_tombstoned_total",
        "Rows tombstoned by expiration job",
        ["tenant_id"],
    )
    _COLD_EXPIRATION_COMPRESSED = Counter(
        "cold_storage_expiration_compressed_total",
        "Rows compressed by expiration job",
        ["tenant_id"],
    )
    _COLD_SECURITY_REJECTIONS = Counter(
        "cold_storage_security_rejections_total",
        "Requests rejected due to tenant_id sanitisation failure",
    )
except ImportError:
    # prometheus_client not installed; use no-op stubs
    class _Noop:
        def inc(self, amount=1): pass
        def labels(self, **kw): return self
    _COLD_ARCHIVE_SUCCESS = _COLD_ARCHIVE_DB_ERRORS = _COLD_PARQUET_ERRORS = \
        _COLD_EXPIRATION_DELETED = _COLD_EXPIRATION_TOMBSTONED = \
        _COLD_EXPIRATION_COMPRESSED = _COLD_SECURITY_REJECTIONS = _Noop()
```

---

## 10. Migration DDL (Alembic)

The v3.0 cold_storage migration must be performed in two stages to avoid locking the table during index creation.

### Stage 1: Schema changes

```sql
-- Add four T-VEC columns
ALTER TABLE cold_fragment
  ADD COLUMN emb_semantic     vector(1536),
  ADD COLUMN emb_topological  vector(1536),
  ADD COLUMN emb_temporal     vector(256),
  ADD COLUMN emb_operational  vector(1536);

-- Add mask columns
ALTER TABLE cold_fragment
  ADD COLUMN mask_semantic     boolean NOT NULL DEFAULT false,
  ADD COLUMN mask_topological  boolean NOT NULL DEFAULT false,
  ADD COLUMN mask_operational  boolean NOT NULL DEFAULT false;

-- Add expiration tier and expires_at
ALTER TABLE cold_fragment
  ADD COLUMN expiration_tier   varchar(20) NOT NULL DEFAULT 'ACTIVE',
  ADD COLUMN expires_at        timestamptz;

-- Backfill expires_at from archived_at + 1095 days (COLD_TIER3_DAYS)
UPDATE cold_fragment
SET expires_at = archived_at + INTERVAL '1095 days'
WHERE expires_at IS NULL;

-- Backfill: copy enriched_embedding -> emb_semantic if dim matches
-- (rows with enriched_embedding of wrong dimension get NULL + mask=true)
UPDATE cold_fragment
SET
  emb_semantic = CASE
    WHEN vector_dims(enriched_embedding) = 1536 THEN enriched_embedding
    ELSE NULL
  END,
  mask_semantic = CASE
    WHEN vector_dims(enriched_embedding) = 1536 THEN false
    ELSE true
  END;

-- Drop legacy column after backfill verified
-- ALTER TABLE cold_fragment DROP COLUMN enriched_embedding;
-- (deferred to Stage 2 after validation)

-- Add scalar indexes
CREATE INDEX ix_cold_frag_archived ON cold_fragment (tenant_id, archived_at);
CREATE INDEX ix_cold_frag_expires ON cold_fragment (expiration_tier, expires_at);
```

### Stage 2: IVFFlat index creation (CONCURRENTLY)

```sql
-- Compute initial lists based on row count at migration time.
-- Replace :semantic_lists etc. with computed values from
-- compute_ivfflat_lists(SELECT COUNT(*) FROM cold_fragment WHERE mask_semantic = false)

CREATE INDEX CONCURRENTLY ix_cold_emb_semantic
  ON cold_fragment USING ivfflat (emb_semantic vector_cosine_ops)
  WITH (lists = :semantic_lists)
  WHERE mask_semantic = false;

CREATE INDEX CONCURRENTLY ix_cold_emb_topological
  ON cold_fragment USING ivfflat (emb_topological vector_cosine_ops)
  WITH (lists = :topological_lists)
  WHERE mask_topological = false;

CREATE INDEX CONCURRENTLY ix_cold_emb_temporal
  ON cold_fragment USING ivfflat (emb_temporal vector_cosine_ops)
  WITH (lists = :temporal_lists);

CREATE INDEX CONCURRENTLY ix_cold_emb_operational
  ON cold_fragment USING ivfflat (emb_operational vector_cosine_ops)
  WITH (lists = :operational_lists)
  WHERE mask_operational = false;
```

---

## 11. Invariant Declarations

| Invariant | Enforcement | Note |
|-----------|-------------|------|
| INV-7 | `tenant_id` on every DB query and every Parquet path construction | tenant_id sanitised via `_sanitise_tenant_id()` before any filesystem access |
| INV-6 | `raw_content_summary` capped at 500 chars in `archive_to_db()` | Cleared entirely in COMPRESSED tier |
| INV-11 | `mask_semantic`, `mask_topological`, `mask_operational` track LLM availability | Search paths exclude masked rows from ANN index traversal |
| NEW-CS-1 | `expiration_tier` must be one of `ACTIVE`, `COMPRESSED`, `TOMBSTONED` | Enforced by CHECK constraint in Stage 1 DDL |
| NEW-CS-2 | `tenant_id` must match `^[a-zA-Z0-9_-]{1,128}$` | Enforced in `_sanitise_tenant_id()` and as DB column constraint `String(128)` |
| NEW-CS-3 | IVFFlat `lists` parameter must be `ceil(sqrt(unmasked_count))` within ±20% drift | Enforced by weekly rebuild procedure (§4.3) |
| NEW-CS-4 | TOMBSTONED rows must have all four embedding columns set NULL | Enforced by expiration job UPDATE statement |
| NEW-CS-5 | `expires_at` must be set at archive time to `archived_at + COLD_TIER3_DAYS` | Enforced in `archive_to_db()` |

---

## 12. Acceptance Criteria Verification

| Criterion | Addressed in Section |
|-----------|---------------------|
| ColdFragmentORM with four embedding columns + masks | §3 |
| IVFFlat index per T-VEC column, list count = ceil(sqrt(n)) | §4 |
| Search strategy: default on emb_semantic, optional multi-index fusion | §5 |
| Expiration policy (F-8.2) | §6 |
| Tenant_id sanitisation in Parquet path construction (F-9.1) | §7 |
| Silent exception removal with logging + counters (F-3.4, F-6.3) | §7.3, §8, §9 |
