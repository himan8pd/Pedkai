# Abeyance Memory v3.0 — Embedding Schema Migration Strategy

**Task:** T1.6
**Author:** Architecture Agent
**Date:** 2026-03-16
**Status:** DRAFT

---

## 1. Overview

This document specifies the Alembic migration steps, backfill approach, dual-write period, cutover criteria, and rollback plan for the transition from the v2 concatenated embedding schema to the v3 decomposed four-vector embedding schema on `abeyance_fragment` and `cold_fragment`.

### 1.1 Schema Delta Summary

| Aspect | v2 (old) | v3 (new) |
|--------|----------|----------|
| Embedding storage | `enriched_embedding Vector(1536)` | `emb_semantic Vector(1536)`, `emb_topological Vector(1536)`, `emb_temporal Vector(256)`, `emb_operational Vector(1536)` |
| Mask storage | `embedding_mask JSONB` (4-element array `[bool, bool, bool, bool]`) | `mask_semantic BOOLEAN`, `mask_topological BOOLEAN`, `mask_temporal BOOLEAN`, `mask_operational BOOLEAN` |
| ANN index | IVFFLAT on `enriched_embedding` (cosine) | HNSW per-dimension on each `emb_*` column |
| `raw_embedding` | `Vector(768)` — retained, not in scope | unchanged |

**Critical constraint:** The old `enriched_embedding Vector(1536)` is an L2-normalised concatenation of sub-vectors. There is no mathematically sound way to decompose it back into constituent sub-vectors. Backfill of old fragments therefore sets all four `mask_*` columns to `FALSE` and leaves all four `emb_*` columns `NULL`. Old fragments remain searchable only via the old `enriched_embedding` column until they naturally decay and exit active status.

---

## 2. Migration Design Principles

1. **Zero downtime.** All DDL uses `ADD COLUMN` (non-blocking in Postgres 13+). No table rewrites. No locks on writes.
2. **Additive first.** New columns are added before any application code switches to writing them.
3. **Dual-write window.** New fragments write to new columns. Old fragments are never re-embedded retroactively.
4. **Natural decay governs cutover.** Old columns are dropped only after zero active/near-miss old-schema fragments remain — driven by the existing `max_lifetime_days` decay cycle, not by a calendar date.
5. **Reversible at every step.** Each Alembic revision has a complete `downgrade()` path until the drop migration, which is irreversible by nature and requires an explicit guard.

---

## 3. Alembic Migration Revisions

Four revisions are defined. They are run sequentially. Each must be applied independently so partial rollback is clean.

### Revision 1: `v3_001_add_decomposed_embedding_columns`

**Description:** Adds new embedding and mask columns to `abeyance_fragment`. No data is written. No indexes are added yet (deferred to avoid long lock during column add).

```python
# upgrade()
op.add_column('abeyance_fragment',
    sa.Column('emb_semantic',     Vector(1536), nullable=True))
op.add_column('abeyance_fragment',
    sa.Column('emb_topological',  Vector(1536), nullable=True))
op.add_column('abeyance_fragment',
    sa.Column('emb_temporal',     Vector(256),  nullable=True))
op.add_column('abeyance_fragment',
    sa.Column('emb_operational',  Vector(1536), nullable=True))

op.add_column('abeyance_fragment',
    sa.Column('mask_semantic',     sa.Boolean(), nullable=True, server_default='false'))
op.add_column('abeyance_fragment',
    sa.Column('mask_topological',  sa.Boolean(), nullable=True, server_default='false'))
op.add_column('abeyance_fragment',
    sa.Column('mask_temporal',     sa.Boolean(), nullable=True, server_default='false'))
op.add_column('abeyance_fragment',
    sa.Column('mask_operational',  sa.Boolean(), nullable=True, server_default='false'))

# Schema version marker — allows application layer to detect transition state
op.add_column('abeyance_fragment',
    sa.Column('embedding_schema_version', sa.SmallInteger(), nullable=True,
              server_default='2'))

# downgrade()
op.drop_column('abeyance_fragment', 'emb_semantic')
op.drop_column('abeyance_fragment', 'emb_topological')
op.drop_column('abeyance_fragment', 'emb_temporal')
op.drop_column('abeyance_fragment', 'emb_operational')
op.drop_column('abeyance_fragment', 'mask_semantic')
op.drop_column('abeyance_fragment', 'mask_topological')
op.drop_column('abeyance_fragment', 'mask_temporal')
op.drop_column('abeyance_fragment', 'mask_operational')
op.drop_column('abeyance_fragment', 'embedding_schema_version')
```

**Execution characteristics:**
- `ADD COLUMN ... DEFAULT` with a constant default in Postgres 11+ is metadata-only (no rewrite).
- Lock acquired: `AccessExclusiveLock` for the duration of the catalog update only — typically <100ms on any table size.
- Application can continue reading and writing during this revision.

---

### Revision 2: `v3_002_backfill_old_fragment_mask_columns`

**Description:** Backfills all pre-existing rows. Sets `mask_*=FALSE` (all four) and `embedding_schema_version=2` to mark them as old-schema. The new `emb_*` columns remain `NULL`. Runs as a batched UPDATE to avoid lock escalation.

```python
# upgrade()
# Batched UPDATE — 10,000 rows per batch, 50ms sleep between batches
# to avoid replication lag and autovacuum contention.
connection = op.get_bind()

BATCH_SIZE = 10_000
SLEEP_MS = 0.05  # 50ms

while True:
    result = connection.execute(sa.text("""
        WITH batch AS (
            SELECT id FROM abeyance_fragment
            WHERE embedding_schema_version IS NULL
               OR embedding_schema_version = 2
                  AND mask_semantic IS NULL
            LIMIT :batch_size
            FOR UPDATE SKIP LOCKED
        )
        UPDATE abeyance_fragment af
        SET
            mask_semantic       = FALSE,
            mask_topological    = FALSE,
            mask_temporal       = FALSE,
            mask_operational    = FALSE,
            embedding_schema_version = 2
        FROM batch
        WHERE af.id = batch.id
        RETURNING af.id
    """), {"batch_size": BATCH_SIZE})
    rows_updated = result.rowcount
    if rows_updated == 0:
        break
    import time; time.sleep(SLEEP_MS)

# downgrade(): no-op — mask columns were added in v3_001
# Setting them back to NULL is safe and equivalent to pre-backfill state
connection.execute(sa.text("""
    UPDATE abeyance_fragment
    SET mask_semantic = NULL,
        mask_topological = NULL,
        mask_temporal = NULL,
        mask_operational = NULL,
        embedding_schema_version = NULL
    WHERE embedding_schema_version = 2
"""))
```

**Execution characteristics:**
- `FOR UPDATE SKIP LOCKED` ensures concurrent writers are never blocked.
- Batched processing keeps individual transaction durations short; WAL write amplification stays bounded.
- This revision is safe to re-run if interrupted; batching is idempotent (rows already updated are not in the `IS NULL` filter).
- Estimated duration: 10,000 rows/batch × (write latency + 50ms sleep). A table of 1M rows completes in approximately 100 batches, around 5 seconds of sleep plus write time.

---

### Revision 3: `v3_003_add_decomposed_embedding_indexes`

**Description:** Adds HNSW ANN indexes on each new `emb_*` column, using `CREATE INDEX CONCURRENTLY`. Also adds a partial BTREE index on `embedding_schema_version` for cutover monitoring queries. Adds the same decomposed columns to `cold_fragment`.

```python
# upgrade()

# HNSW indexes on abeyance_fragment — partial WHERE mask_* = TRUE
# so index only contains fragments where the sub-vector is valid.
# HNSW parameters: m=16, ef_construction=64 (tunable).

op.execute("""
    CREATE INDEX CONCURRENTLY IF NOT EXISTS
    ix_af_emb_semantic_hnsw
    ON abeyance_fragment
    USING hnsw (emb_semantic vector_cosine_ops)
    WITH (m = 16, ef_construction = 64)
    WHERE mask_semantic = TRUE
""")

op.execute("""
    CREATE INDEX CONCURRENTLY IF NOT EXISTS
    ix_af_emb_topological_hnsw
    ON abeyance_fragment
    USING hnsw (emb_topological vector_cosine_ops)
    WITH (m = 16, ef_construction = 64)
    WHERE mask_topological = TRUE
""")

op.execute("""
    CREATE INDEX CONCURRENTLY IF NOT EXISTS
    ix_af_emb_temporal_hnsw
    ON abeyance_fragment
    USING hnsw (emb_temporal vector_cosine_ops)
    WITH (m = 16, ef_construction = 64)
    WHERE mask_temporal = TRUE
""")

op.execute("""
    CREATE INDEX CONCURRENTLY IF NOT EXISTS
    ix_af_emb_operational_hnsw
    ON abeyance_fragment
    USING hnsw (emb_operational vector_cosine_ops)
    WITH (m = 16, ef_construction = 64)
    WHERE mask_operational = TRUE
""")

# Monitoring index: count of v2-schema active fragments
op.execute("""
    CREATE INDEX CONCURRENTLY IF NOT EXISTS
    ix_af_schema_version_active
    ON abeyance_fragment (embedding_schema_version, snap_status)
    WHERE snap_status IN ('INGESTED', 'ACTIVE', 'NEAR_MISS')
""")

# cold_fragment: add decomposed columns (no backfill needed — cold
# fragments are read-rarely; query layer falls back to enriched_embedding)
op.add_column('cold_fragment',
    sa.Column('emb_semantic',     Vector(1536), nullable=True))
op.add_column('cold_fragment',
    sa.Column('emb_topological',  Vector(1536), nullable=True))
op.add_column('cold_fragment',
    sa.Column('emb_temporal',     Vector(256),  nullable=True))
op.add_column('cold_fragment',
    sa.Column('emb_operational',  Vector(1536), nullable=True))
op.add_column('cold_fragment',
    sa.Column('mask_semantic',    sa.Boolean(), nullable=True, server_default='false'))
op.add_column('cold_fragment',
    sa.Column('mask_topological', sa.Boolean(), nullable=True, server_default='false'))
op.add_column('cold_fragment',
    sa.Column('mask_temporal',    sa.Boolean(), nullable=True, server_default='false'))
op.add_column('cold_fragment',
    sa.Column('mask_operational', sa.Boolean(), nullable=True, server_default='false'))
op.add_column('cold_fragment',
    sa.Column('embedding_schema_version', sa.SmallInteger(), nullable=True,
              server_default='2'))

op.execute("""
    CREATE INDEX CONCURRENTLY IF NOT EXISTS
    ix_cf_emb_semantic_hnsw
    ON cold_fragment
    USING hnsw (emb_semantic vector_cosine_ops)
    WITH (m = 16, ef_construction = 64)
    WHERE mask_semantic = TRUE
""")

# downgrade()
op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_af_emb_semantic_hnsw")
op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_af_emb_topological_hnsw")
op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_af_emb_temporal_hnsw")
op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_af_emb_operational_hnsw")
op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_af_schema_version_active")
op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_cf_emb_semantic_hnsw")
op.drop_column('cold_fragment', 'emb_semantic')
op.drop_column('cold_fragment', 'emb_topological')
op.drop_column('cold_fragment', 'emb_temporal')
op.drop_column('cold_fragment', 'emb_operational')
op.drop_column('cold_fragment', 'mask_semantic')
op.drop_column('cold_fragment', 'mask_topological')
op.drop_column('cold_fragment', 'mask_temporal')
op.drop_column('cold_fragment', 'mask_operational')
op.drop_column('cold_fragment', 'embedding_schema_version')
```

**Execution characteristics:**
- `CREATE INDEX CONCURRENTLY` does not block reads or writes; it acquires only a `ShareUpdateExclusiveLock`.
- HNSW index build is CPU-intensive. On a 2-OCPU VM with 12 GB RAM, a 1M-row table with partial WHERE clause typically completes in 2–10 minutes depending on the number of qualifying rows.
- Indexes are partial (only rows where `mask_*=TRUE`). Initially these indexes are empty because no v3-schema fragments exist yet. They grow incrementally as new fragments are ingested.
- This revision must complete before application code begins writing new-schema fragments.

---

### Revision 4: `v3_004_drop_old_embedding_columns` (CUTOVER — IRREVERSIBLE)

**Description:** Drops `enriched_embedding`, `embedding_mask`, and the old IVFFLAT index from `abeyance_fragment`. Also drops `enriched_embedding` from `cold_fragment`. This revision has no `downgrade()` path — it is guarded by cutover criteria (Section 5) and must only be executed when those criteria are fully satisfied.

```python
# upgrade()
# GUARD: this revision must be executed manually after verifying cutover
# criteria. The migration runner must set env var
# ABEYANCE_V3_CUTOVER_CONFIRMED=1 or this upgrade() will raise.
import os
if os.environ.get('ABEYANCE_V3_CUTOVER_CONFIRMED') != '1':
    raise RuntimeError(
        "v3_004 requires ABEYANCE_V3_CUTOVER_CONFIRMED=1. "
        "Run the cutover readiness check first."
    )

# Drop old IVFFLAT index first (non-blocking CONCURRENTLY)
op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_abeyance_fragment_enriched_emb_ann")
# Note: the old IVFFLAT index on cold_fragment:
op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_cold_frag_embedding_ann")

# Drop old columns (requires AccessExclusiveLock but is fast — metadata only)
op.drop_column('abeyance_fragment', 'enriched_embedding')
op.drop_column('abeyance_fragment', 'embedding_mask')
op.drop_column('cold_fragment',     'enriched_embedding')

# Drop schema version column — no longer needed after full cutover
op.drop_column('abeyance_fragment', 'embedding_schema_version')
op.drop_column('cold_fragment',     'embedding_schema_version')

# downgrade() — NOT POSSIBLE. Data is gone.
# This is intentional. Downgrade path for v3_004 raises explicitly.
raise NotImplementedError(
    "v3_004 drop migration is irreversible. "
    "Restore from backup if rollback is required."
)
```

---

## 4. Backfill Approach

### 4.1 Why No Vector Backfill

The old `enriched_embedding` is a single L2-normalised vector produced by concatenating and normalising four sub-vectors of dimensions 1536 + 1536 + 256 + 1536 = 4864, then further compressed to 1536 via a learned projection. This projection is a lossy, non-invertible operation. Even if the projection matrix were known, the L2 normalisation applied post-projection destroys the magnitude information of each sub-vector. There is no mathematically sound path from the 1536-dimensional composite back to four separate sub-vectors.

**Decision:** Old fragments receive `mask_*=FALSE` on all four new columns. Their `emb_*` columns remain `NULL`. During the dual-write period the query layer uses the old `enriched_embedding` for similarity search on old-schema fragments and the new per-dimension columns for new-schema fragments.

### 4.2 Mask Migration from JSONB

The old `embedding_mask` JSONB column holds a 4-element array `[semantic_valid, topo_valid, temporal_valid, operational_valid]`. For old-schema fragments this is already set to `[true, false, true, false]` by default (per INV-11). However, this historical validity information cannot be used to populate the new mask columns, because the corresponding decomposed sub-vectors are not stored and cannot be recovered. The new `mask_*` columns represent validity of the new decomposed vectors only. Therefore:

- All old-schema fragments: `mask_semantic=FALSE, mask_topological=FALSE, mask_temporal=FALSE, mask_operational=FALSE`
- The old `embedding_mask` JSONB is preserved until revision 4 (cutover drop)

This is handled in revision 2 (batched UPDATE).

### 4.3 `cold_fragment` Backfill

`cold_fragment` rows are not backfilled. They are rarely queried and immutable after archival. The query layer falls back to `enriched_embedding` for cold storage similarity search until v3_004 drops that column. After v3_004, cold fragments with `mask_*=FALSE` are excluded from ANN similarity search (they have no valid embedding to search against); this is acceptable because cold fragments represent terminal-state evidence with very low retrieval utility.

---

## 5. Dual-Write Period

### 5.1 Application Layer Contract During Dual-Write

After revisions 1–3 are applied, the application operates in dual-write mode. The following contract applies at the application layer (not enforced in this migration spec, but required for correctness):

| Fragment generation | Write target |
|---------------------|--------------|
| New fragments (v3 enrichment pipeline) | Write to `emb_semantic`, `emb_topological`, `emb_temporal`, `emb_operational`; set corresponding `mask_*` per enrichment availability; set `embedding_schema_version=3`; leave `enriched_embedding=NULL` |
| Old fragments (v2 — already in DB) | No re-write. `enriched_embedding` unchanged. `mask_*=FALSE`. `embedding_schema_version=2` |

### 5.2 Query Layer Contract During Dual-Write

Similarity search must branch on `embedding_schema_version`:

```sql
-- New-schema ANN search (v3 fragments only, per-dimension)
SELECT id, tenant_id, current_decay_score
FROM abeyance_fragment
WHERE tenant_id = :tid
  AND snap_status IN ('ACTIVE', 'NEAR_MISS')
  AND embedding_schema_version = 3
  AND mask_semantic = TRUE
ORDER BY emb_semantic <=> :query_vector
LIMIT :k;

-- Old-schema ANN search (v2 fragments — fallback path during dual-write)
SELECT id, tenant_id, current_decay_score
FROM abeyance_fragment
WHERE tenant_id = :tid
  AND snap_status IN ('ACTIVE', 'NEAR_MISS')
  AND embedding_schema_version = 2
ORDER BY enriched_embedding <=> :query_composite_vector
LIMIT :k;
```

Results from both paths are merged and ranked before returning to the snap evaluator. This dual-path query is removed at cutover (revision 4).

### 5.3 Duration of Dual-Write Period

The dual-write period ends when the cutover criteria in Section 6 are met. The governing constraint is the natural decay of old-schema fragments. With `max_lifetime_days=730` as the hard cap, the maximum theoretical dual-write period is 730 days. In practice, fragments expire much sooner via decay scoring. The monitoring query in Section 6.1 tracks remaining old-schema active fragments.

---

## 6. Cutover Criteria

All six criteria must be satisfied before executing revision 4.

### 6.1 Criterion 1: Zero Active Old-Schema Fragments

```sql
-- This query must return 0 rows before revision 4 is executed
SELECT COUNT(*) AS old_schema_active_count
FROM abeyance_fragment
WHERE embedding_schema_version = 2
  AND snap_status IN ('INGESTED', 'ACTIVE', 'NEAR_MISS');
```

Target: `old_schema_active_count = 0`

This is the primary cutover gate. It is evaluated weekly by the operator. The `ix_af_schema_version_active` index (added in revision 3) makes this query fast.

### 6.2 Criterion 2: No v2-Schema Fragments in NEAR_MISS State

NEAR_MISS fragments can be reactivated (state machine allows `NEAR_MISS → ACTIVE`). They must be zero before cutover.

```sql
SELECT COUNT(*) AS near_miss_v2_count
FROM abeyance_fragment
WHERE embedding_schema_version = 2
  AND snap_status = 'NEAR_MISS';
```

Target: `near_miss_v2_count = 0`

### 6.3 Criterion 3: Application Code No Longer References Old Columns

All code paths that read or write `enriched_embedding` or `embedding_mask` on `abeyance_fragment` must have been removed and deployed before revision 4 runs. Verification: grep the deployed codebase and confirm zero references.

### 6.4 Criterion 4: v3-Schema Fragments Constitute 100% of Recent Ingestion

```sql
SELECT embedding_schema_version, COUNT(*) AS cnt
FROM abeyance_fragment
WHERE created_at > NOW() - INTERVAL '7 days'
GROUP BY embedding_schema_version;
```

Target: only `embedding_schema_version = 3` rows in the past 7-day window.

### 6.5 Criterion 5: HNSW Indexes Are Populated and Healthy

```sql
SELECT indexname, idx_scan, idx_tup_read
FROM pg_stat_user_indexes
WHERE indexname IN (
    'ix_af_emb_semantic_hnsw',
    'ix_af_emb_topological_hnsw',
    'ix_af_emb_temporal_hnsw',
    'ix_af_emb_operational_hnsw'
);
```

Target: all four indexes have `idx_scan > 0` (at least one query has exercised them). Confirms the query layer is actively using the new indexes.

### 6.6 Criterion 6: Backup Taken Within 24 Hours

A full `pg_dump` or equivalent backup of the DB VM must be confirmed within 24 hours before executing revision 4. Revision 4 is irreversible; backup is the only rollback path.

---

## 7. Rollback Plan

### 7.1 Rollback After Revision 1 (`v3_001`)

**Trigger:** Application errors on new columns; unexpected lock contention.
**Action:** `alembic downgrade v3_000` (base).
**Effect:** Drops all eight new columns and `embedding_schema_version`. No data loss — no data was written to these columns yet.
**Risk:** None. Fully reversible.

### 7.2 Rollback After Revision 2 (`v3_002`)

**Trigger:** Backfill causes replication lag > 30 seconds or autovacuum bloat exceeds threshold.
**Action:** Stop the backfill script. Downgrade to `v3_001`.
**Effect:** Sets `mask_*=NULL` and `embedding_schema_version=NULL` for all rows. Application is back to reading only old columns.
**Risk:** Low. Downgrade is a simple UPDATE + re-run of v3_001 state (no data written yet to emb_* columns).
**Resume:** Re-run `v3_002` with a smaller `BATCH_SIZE` (e.g., 2000 rows) and longer sleep (200ms).

### 7.3 Rollback After Revision 3 (`v3_003`)

**Trigger:** HNSW index build consumes excessive CPU (>80% sustained for >30 minutes on production VM); or cold_fragment column additions fail.
**Action:** Downgrade to `v3_002`. This drops all HNSW indexes with `DROP INDEX CONCURRENTLY` and removes cold_fragment new columns.
**Effect:** Application continues operating on old embedding columns. HNSW build can be rescheduled for a maintenance window.
**Risk:** Low. Downgrade DROP CONCURRENTLY is non-blocking.

### 7.4 Rollback After Revision 4 (`v3_004`) — DATABASE BACKUP RESTORE ONLY

Revision 4 drops `enriched_embedding` and `embedding_mask`. There is no Alembic downgrade path.

**Rollback procedure:**
1. Stop all application processes that write to `abeyance_fragment`.
2. Restore the DB VM block volume from the backup snapshot taken per Criterion 6.6.
3. Re-apply revisions 1–3 against the restored backup.
4. Redeploy application code that includes the dual-write path.
5. Do not re-run revision 4 until root cause is understood and all six cutover criteria are re-verified.

**RPL (Recovery Point Loss):** All writes between the backup snapshot and the revision 4 execution are lost. This window must be kept short — revision 4 should be executed immediately after backup confirmation, during a low-ingestion window.

---

## 8. Operational Monitoring During Migration

### 8.1 Metrics to Track

| Metric | Query / Source | Alert threshold |
|--------|----------------|-----------------|
| Old-schema active fragment count | Criterion 6.1 query | Alert if count stalls (no change over 14 days) |
| Replication lag | `pg_stat_replication.sent_lsn - write_lsn` | > 10 seconds |
| Autovacuum bloat | `pg_stat_user_tables.n_dead_tup` on `abeyance_fragment` | > 20% of live rows |
| HNSW index size | `pg_relation_size('ix_af_emb_semantic_hnsw')` | Monitor for growth; no threshold |
| Dual-write error rate | Application logs: `embedding_schema_version` mismatch errors | Any error |

### 8.2 Migration State Machine

```
NOT_STARTED
    → [apply v3_001] → COLUMNS_ADDED
    → [apply v3_002] → BACKFILL_COMPLETE
    → [apply v3_003] → INDEXES_BUILT (dual-write begins)
    → [all 6 criteria met] → CUTOVER_READY
    → [apply v3_004] → CUTOVER_COMPLETE
```

---

## 9. Migration Execution Checklist

Execute in this order. Do not skip steps.

- [ ] 1. Confirm pgvector version supports HNSW (`SELECT extversion FROM pg_extension WHERE extname='vector'` — requires >= 0.5.0)
- [ ] 2. Confirm Postgres version >= 13 (`SELECT version()`)
- [ ] 3. Take a database snapshot/backup before starting
- [ ] 4. Apply `v3_001` — verify `\d abeyance_fragment` shows new columns
- [ ] 5. Apply `v3_002` — verify `SELECT COUNT(*) FROM abeyance_fragment WHERE embedding_schema_version IS NULL` returns 0
- [ ] 6. Apply `v3_003` — monitor CPU during HNSW build; verify indexes appear in `pg_stat_user_indexes`
- [ ] 7. Deploy application code with dual-write support (before any new fragments are ingested)
- [ ] 8. Monitor old-schema fragment count weekly via Criterion 6.1 query
- [ ] 9. When all six cutover criteria are met:
    - [ ] 9a. Take fresh backup
    - [ ] 9b. Deploy application code with old-column references removed
    - [ ] 9c. Set `ABEYANCE_V3_CUTOVER_CONFIRMED=1`
    - [ ] 9d. Apply `v3_004` during low-ingestion window
- [ ] 10. Verify `\d abeyance_fragment` no longer shows `enriched_embedding` or `embedding_mask`
- [ ] 11. Update INV-11 in ORM documentation to reflect boolean column contract

---

## 10. Dependencies and Constraints

| Dependency | Owner | Required Before |
|------------|-------|-----------------|
| pgvector >= 0.5.0 (HNSW support) | Infrastructure | Revision 3 |
| T1.2 target schema finalized | Architecture Agent | Revision 1 |
| Application dual-write code deployed | Engineering | Between Revision 3 and first new fragment ingestion |
| Old-column read/write code removed | Engineering | Revision 4 |
| DB backup procedure confirmed | Infrastructure | Revision 4 |

---

*Generated by Architecture Agent — T1.6 | Abeyance Memory v3.0 Reconstruction*
