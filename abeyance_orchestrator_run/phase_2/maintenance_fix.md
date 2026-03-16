# T2.3 — Maintenance Subsystem Remediation

**Task:** Fix N+1 query in `prune_stale_edges()` and design maintenance job history table.
**Findings addressed:** F-5.3 (SEVERE), F-7.3 (Moderate)
**Generated:** 2026-03-16

---

## 1. Problem Analysis

### F-5.3: N+1 Query in `prune_stale_edges()`

The current implementation in `maintenance.py` (lines 60–110) executes:

1. One `SELECT` to load up to `MAX_PRUNE_BATCH` (10,000) `AccumulationEdgeORM` rows into Python memory.
2. For each edge in Python: two additional `SELECT` queries — one for `fragment_a_id`, one for `fragment_b_id` — to fetch their `current_decay_score` and `snap_status`.

At `MAX_PRUNE_BATCH = 10,000` edges this produces up to **20,001 round-trips** per call. At any realistic edge density the query loop becomes the dominant latency contributor for the maintenance job.

The root cause is that the query fetches the edge rows without their associated fragment data, then resolves each fragment individually. A single JOIN can eliminate all per-edge queries.

### F-7.3: No Maintenance Job History

`run_full_maintenance()` returns a dict but does not persist it. There is no way to query historical decay rates, edge pruning counts, or expiration counts across runs. Operator tooling (dashboards, alerting, runbooks) cannot distinguish a healthy nightly run from a run that silently processed zero fragments due to a misconfiguration.

---

## 2. Fix: Batch JOIN Query for `prune_stale_edges()`

### Strategy

Replace the SELECT + N×(SELECT, SELECT) pattern with a single query that joins `accumulation_edge` to `abeyance_fragment` twice — once for each side of the edge — and evaluates the prune condition entirely in the database.

Three conditions warrant removal, evaluated in a single pass:
- **Orphaned edge**: one or both fragment rows do not exist (LEFT JOIN produces NULL).
- **Status-based removal**: either fragment has `snap_status` IN `('EXPIRED', 'COLD')`.
- **Score-based removal**: both fragments have `current_decay_score < STALE_EDGE_THRESHOLD`.

### Batch DELETE SQL

```sql
-- Identify edge IDs to remove in a single scan.
-- frag_a and frag_b are aliased self-joins on abeyance_fragment.
WITH edges_to_prune AS (
    SELECT e.id
    FROM accumulation_edge AS e
    LEFT JOIN abeyance_fragment AS fa
           ON fa.id = e.fragment_a_id
          AND fa.tenant_id = e.tenant_id
    LEFT JOIN abeyance_fragment AS fb
           ON fb.id = e.fragment_b_id
          AND fb.tenant_id = e.tenant_id
    WHERE e.tenant_id = :tenant_id
      AND (
            fa.id IS NULL                                         -- orphaned: fragment_a missing
         OR fb.id IS NULL                                         -- orphaned: fragment_b missing
         OR fa.snap_status IN ('EXPIRED', 'COLD')                 -- status-based
         OR fb.snap_status IN ('EXPIRED', 'COLD')                 -- status-based
         OR (    fa.current_decay_score < :threshold              -- score-based: both below
             AND fb.current_decay_score < :threshold)
      )
    LIMIT :batch_limit
)
DELETE FROM accumulation_edge
WHERE id IN (SELECT id FROM edges_to_prune)
RETURNING id;
```

Parameters:
- `:tenant_id` — current tenant
- `:threshold` — `STALE_EDGE_THRESHOLD` (0.2)
- `:batch_limit` — `MAX_PRUNE_BATCH` (10,000)

The `RETURNING id` clause gives the count of removed rows without a second query.

### SQLAlchemy Core Equivalent

The implementation should use SQLAlchemy Core text or ORM aliased-join constructs rather than raw SQL strings, but the logical structure must match the above exactly. Pseudocode for the SQLAlchemy translation:

```python
from sqlalchemy import select, delete, or_, and_, text
from sqlalchemy.orm import aliased

FragA = aliased(AbeyanceFragmentORM, flat=True)
FragB = aliased(AbeyanceFragmentORM, flat=True)

# Step 1: collect IDs to remove (single query)
candidate_stmt = (
    select(AccumulationEdgeORM.id)
    .join(FragA,
          and_(FragA.id == AccumulationEdgeORM.fragment_a_id,
               FragA.tenant_id == AccumulationEdgeORM.tenant_id),
          isouter=True)
    .join(FragB,
          and_(FragB.id == AccumulationEdgeORM.fragment_b_id,
               FragB.tenant_id == AccumulationEdgeORM.tenant_id),
          isouter=True)
    .where(AccumulationEdgeORM.tenant_id == tenant_id)
    .where(
        or_(
            FragA.id.is_(None),
            FragB.id.is_(None),
            FragA.snap_status.in_(("EXPIRED", "COLD")),
            FragB.snap_status.in_(("EXPIRED", "COLD")),
            and_(
                FragA.current_decay_score < STALE_EDGE_THRESHOLD,
                FragB.current_decay_score < STALE_EDGE_THRESHOLD,
            ),
        )
    )
    .limit(MAX_PRUNE_BATCH)
)
result = await session.execute(candidate_stmt)
ids_to_remove = [row[0] for row in result.fetchall()]

# Step 2: delete by collected IDs (single DELETE)
if ids_to_remove:
    await session.execute(
        delete(AccumulationEdgeORM).where(
            AccumulationEdgeORM.id.in_(ids_to_remove)
        )
    )
    await session.flush()

removed = len(ids_to_remove)
```

This is two queries total regardless of the number of edges examined — not 2N+1.

### Query Count Comparison

| Version | Queries per call (N edges evaluated) |
|---------|--------------------------------------|
| Current (N+1) | 1 + 2N (up to 20,001 at batch limit) |
| Fixed (batch JOIN) | 2 (always: one SELECT + one DELETE) |

### Index Verification

The existing indexes in `AccumulationEdgeORM.__table_args__` cover this query:
- `ix_accum_edge_frag_a (tenant_id, fragment_a_id)` — used for the first JOIN
- `ix_accum_edge_frag_b (tenant_id, fragment_b_id)` — used for the second JOIN

No new indexes are required. The planner will use the existing covering indexes on `abeyance_fragment (id)` (primary key) for the JOIN lookups.

---

## 3. Maintenance Job History Table

### 3.1 Purpose

Persist the result dict from every `run_full_maintenance()` (and its component sub-jobs) to a durable table. This allows:
- Trending decay/expiration rates over time per tenant.
- Detection of maintenance runs that processed 0 rows (possible misconfiguration, empty batch, or silent error).
- SLA verification that maintenance ran within the expected interval.
- Debugging: correlate a decay anomaly in production with a specific maintenance run.

### 3.2 Table Schema

**Table name:** `maintenance_job_history`

```sql
CREATE TABLE maintenance_job_history (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       VARCHAR(100)  NOT NULL,
    job_name        VARCHAR(60)   NOT NULL,
    -- 'full_maintenance' | 'decay_pass' | 'prune_stale_edges'
    -- | 'expire_stale_fragments' | 'cleanup_orphaned_entity_refs'
    started_at      TIMESTAMPTZ   NOT NULL,
    finished_at     TIMESTAMPTZ   NOT NULL,
    duration_ms     INTEGER       NOT NULL,   -- derived: (finished_at - started_at) in ms
    status          VARCHAR(20)   NOT NULL,   -- 'SUCCESS' | 'PARTIAL' | 'ERROR'
    result          JSONB         NOT NULL,   -- job-specific counts (see §3.3)
    error_detail    TEXT          NULL,       -- NULL on SUCCESS; exception message on ERROR
    triggered_by    VARCHAR(60)   NOT NULL    -- 'scheduler' | 'api' | 'test'
);

CREATE INDEX ix_mjh_tenant_started
    ON maintenance_job_history (tenant_id, started_at DESC);

CREATE INDEX ix_mjh_job_tenant_started
    ON maintenance_job_history (job_name, tenant_id, started_at DESC);
```

### 3.3 Column Definitions

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | UUID | NOT NULL | Surrogate primary key |
| `tenant_id` | VARCHAR(100) | NOT NULL | Tenant this run applied to; matches `abeyance_fragment.tenant_id` |
| `job_name` | VARCHAR(60) | NOT NULL | One of the five values listed below |
| `started_at` | TIMESTAMPTZ | NOT NULL | Wall-clock time at method entry (UTC) |
| `finished_at` | TIMESTAMPTZ | NOT NULL | Wall-clock time after `session.flush()` and before return |
| `duration_ms` | INTEGER | NOT NULL | `(finished_at - started_at)` in milliseconds; stored redundantly for fast aggregation |
| `status` | VARCHAR(20) | NOT NULL | `SUCCESS` — completed without exception; `PARTIAL` — partial batch processed (hit `LIMIT`); `ERROR` — exception raised |
| `result` | JSONB | NOT NULL | Counts specific to the job (see per-job schemas below) |
| `error_detail` | TEXT | NULL | Python exception class + message on `ERROR`; NULL otherwise |
| `triggered_by` | VARCHAR(60) | NOT NULL | Source that invoked the job: `scheduler`, `api`, `test` |

**Allowed `job_name` values:**
- `full_maintenance` — top-level orchestration entry (one row per full run)
- `decay_pass` — result from `run_decay_pass()`
- `prune_stale_edges` — result from `prune_stale_edges()`
- `expire_stale_fragments` — result from `expire_stale_fragments()`
- `cleanup_orphaned_entity_refs` — result from `cleanup_orphaned_entity_refs()`

When `run_full_maintenance()` runs, it writes **five rows**: one for the overall run (job_name = `full_maintenance`) and one per sub-job. The sub-job rows share the same `started_at` prefix so they can be grouped by a parent run via `started_at` proximity, or via a `parent_run_id` column (see §3.5 optional extension).

### 3.4 Per-Job `result` JSONB Schemas

**`full_maintenance`**
```json
{
  "decay":           {"updated": 1240, "expired": 87},
  "stale_edges_pruned": 312,
  "fragments_expired": 87,
  "orphans_cleaned": 5
}
```

**`decay_pass`**
```json
{"updated": 1240, "expired": 87}
```

**`prune_stale_edges`**
```json
{"removed": 312, "batch_limit_reached": false}
```
`batch_limit_reached` is `true` when `removed == MAX_PRUNE_BATCH`, signaling that more edges may remain and a second pass is warranted. Status is set to `PARTIAL` in this case.

**`expire_stale_fragments`**
```json
{"expired": 87, "batch_limit_reached": false}
```

**`cleanup_orphaned_entity_refs`**
```json
{"removed": 5, "batch_limit_reached": false}
```

**On error:**
```json
{"partial_result": <whatever was computed before the exception, or null>}
```

### 3.5 ORM Class

```python
class MaintenanceJobHistoryORM(Base):
    """Persistent record of every maintenance job execution (F-7.3 fix)."""

    __tablename__ = "maintenance_job_history"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id    = Column(String(100), nullable=False)
    job_name     = Column(String(60), nullable=False)
    started_at   = Column(DateTime(timezone=True), nullable=False)
    finished_at  = Column(DateTime(timezone=True), nullable=False)
    duration_ms  = Column(Integer, nullable=False)
    status       = Column(String(20), nullable=False)   # SUCCESS | PARTIAL | ERROR
    result       = Column(JSONB, nullable=False, default=dict)
    error_detail = Column(Text, nullable=True)
    triggered_by = Column(String(60), nullable=False)

    __table_args__ = (
        Index("ix_mjh_tenant_started",   "tenant_id", "started_at"),
        Index("ix_mjh_job_tenant_started", "job_name", "tenant_id", "started_at"),
    )
```

This class belongs in `backend/app/models/abeyance_orm.py` alongside the existing ORM classes, or in a dedicated `maintenance_orm.py` if the maintenance subsystem is broken into its own module.

### 3.6 Persistence Protocol

Job history rows must be written to a **separate session** (or committed inside the same session before the main flush) so that a rollback of the maintenance transaction does not erase the error record. The recommended pattern:

```python
async def _record_job(
    self,
    session: AsyncSession,         # job session (may be rolled back)
    history_session: AsyncSession, # dedicated history session (always committed)
    job_name: str,
    tenant_id: str,
    started_at: datetime,
    result: dict,
    status: str,
    error_detail: str | None,
    triggered_by: str,
) -> None:
    finished_at = datetime.now(timezone.utc)
    duration_ms = int((finished_at - started_at).total_seconds() * 1000)
    row = MaintenanceJobHistoryORM(
        tenant_id=tenant_id,
        job_name=job_name,
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=duration_ms,
        status=status,
        result=result,
        error_detail=error_detail,
        triggered_by=triggered_by,
    )
    history_session.add(row)
    await history_session.commit()
```

If a single-session design is mandated (e.g., to avoid a second DB connection), the history row is added to the session and `session.flush()` is called before any potential rollback point. The status `ERROR` row must still be flushed even when the outer transaction fails; use a `SAVEPOINT` or `session.begin_nested()` for this.

### 3.7 `PARTIAL` Status Logic

A sub-job sets `status = 'PARTIAL'` when the count of affected rows equals the batch limit, indicating the job was capped and did not process all eligible rows. The `full_maintenance` job sets `status = 'PARTIAL'` if any sub-job returned `PARTIAL`.

### 3.8 Retention Policy

`maintenance_job_history` is append-only during normal operation. To prevent unbounded growth, a scheduled cleanup deletes rows older than a configurable retention window. Default: **90 days**. This cleanup is itself recorded as a `maintenance_job_history` row with `job_name = 'history_cleanup'`.

---

## 4. Migration

A new Alembic migration (to follow the existing `009_*` revision) must:

1. Create the `maintenance_job_history` table with all columns and indexes defined in §3.2.
2. No data migration is required (table is new; historical runs are not backfilled).
3. Add `MaintenanceJobHistoryORM` to the import list in `backend/app/models/abeyance_orm.py` (or equivalent module).

---

## 5. Changes to `MaintenanceService`

### 5.1 `prune_stale_edges()` — replace body

Remove lines 65–108 of the current implementation. Replace with the two-query batch pattern from §2 above. The method signature and return type (`int`) are unchanged.

### 5.2 `run_full_maintenance()` — add history writes

Wrap each sub-job call in a `try/except` block that captures `started_at` before invocation and writes a `MaintenanceJobHistoryORM` row after. The overall `full_maintenance` row is written after all sub-jobs complete (or after the first unhandled error).

### 5.3 `__init__()` — no new dependencies

The `MaintenanceService` constructor does not require a new dependency injection argument for history writing. The `AsyncSession` passed to `run_full_maintenance()` (or a factory pattern already established in the project) is sufficient to write history rows.

---

## 6. Acceptance Criteria Verification

| Criterion | Addressed by |
|-----------|-------------|
| N+1 query replaced with batch query (exact SQL) | §2 — CTE-based DELETE with dual LEFT JOIN; SQL provided verbatim plus SQLAlchemy translation |
| Job history table: schema, columns, what is recorded per run | §3.2 (DDL), §3.3 (column definitions), §3.4 (per-job JSONB schemas) |
| Job history persistence (not just in-memory) | §3.5 (ORM class), §3.6 (persistence protocol, separate commit, error-safe) |
