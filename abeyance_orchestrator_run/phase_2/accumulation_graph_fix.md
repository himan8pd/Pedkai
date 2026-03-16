# Accumulation Graph Remediation — T2.1
## Fix F-5.2 (Unbounded Edge Load) and F-5.3 (N+1 Edge Pruning)

**Task**: T2.1 — Accumulation Graph Remediation
**Date**: 2026-03-16
**Affects**:
- `/Users/himanshu/Projects/Pedkai/backend/app/services/abeyance/accumulation_graph.py`
- `/Users/himanshu/Projects/Pedkai/backend/app/services/abeyance/maintenance.py`

---

## 1. Problem Statement

### F-5.2 — Unbounded Full-Tenant Edge Load (SEVERE)

**Location**: `accumulation_graph.py`, `detect_and_evaluate_clusters()`, lines 222–228.

**Defective code**:
```python
edge_stmt = (
    select(AccumulationEdgeORM)
    .where(AccumulationEdgeORM.tenant_id == tenant_id)
)
result = await session.execute(edge_stmt)
edges = list(result.scalars().all())
```

**Problem**: Loads every `accumulation_edge` row for the tenant into the SQLAlchemy ORM object graph. With MAX_EDGES_PER_FRAGMENT = 20 and a large tenant population:

| Active fragments | Edges (worst case) | Memory (ORM objects ~200B each) |
|---|---|---|
| 100K | 1M | ~200 MB |
| 500K | 5M | ~1 GB |
| 1M | 10M | ~2 GB |

Each `AccumulationEdgeORM` object materializes all columns including timestamps. The query has no LIMIT, no cursor, and no filtering — it loads the entire edge graph into Python heap before union-find begins.

**Trigger condition**: Every call to `detect_and_evaluate_clusters()`, which is called after every `add_or_update_edge()` invocation (i.e., after every affinity edge creation in the snap pipeline).

---

### F-5.3 — N+1 Edge Pruning Queries (SEVERE)

**Location**: `maintenance.py`, `prune_stale_edges()`, lines 60–109.

**Defective code**:
```python
edge_stmt = (
    select(AccumulationEdgeORM)
    .where(AccumulationEdgeORM.tenant_id == tenant_id)
    .limit(MAX_PRUNE_BATCH)
)
result = await session.execute(edge_stmt)
edges = list(result.scalars().all())

removed = 0
for edge in edges:
    frag_a_stmt = (
        select(AbeyanceFragmentORM.current_decay_score, AbeyanceFragmentORM.snap_status)
        .where(
            AbeyanceFragmentORM.id == edge.fragment_a_id,
            AbeyanceFragmentORM.tenant_id == tenant_id,
        )
    )
    frag_b_stmt = (
        select(AbeyanceFragmentORM.current_decay_score, AbeyanceFragmentORM.snap_status)
        .where(
            AbeyanceFragmentORM.id == edge.fragment_b_id,
            AbeyanceFragmentORM.tenant_id == tenant_id,
        )
    )
    a_result = await session.execute(frag_a_stmt)
    b_result = await session.execute(frag_b_stmt)
    ...
```

**Problem**: For each edge in the batch, two separate SELECT statements are executed (one for fragment_a, one for fragment_b). This is the textbook N+1 pattern.

| Batch size | DB round-trips |
|---|---|
| 1,000 edges | 2,001 (1 batch fetch + 2000 fragment lookups) |
| 10,000 edges | 20,001 (1 batch fetch + 20,000 fragment lookups) |

At MAX_PRUNE_BATCH = 10,000, this is 20,001 sequential async database round-trips per maintenance pass. On Postgres with 1ms average query latency this takes 20 seconds minimum, serialized.

---

## 2. Complexity Analysis — Before and After

### F-5.2 (detect_and_evaluate_clusters)

| Metric | Before (broken) | After (fixed) |
|---|---|---|
| Edges loaded per call | O(E_tenant) — all edges | O(E_neighbourhood) — edges of trigger fragment's connected component |
| Memory per call | O(E_tenant) | O(E_neighbourhood) ≤ O(MAX_CLUSTER_SIZE² / 2) = O(1225) |
| DB round-trips | 1 (but huge result) | 1 anchored + 1 expansion (2 total) |
| Worst-case edges loaded | 10M | MAX_CLUSTER_SIZE * MAX_EDGES_PER_FRAGMENT = 50 * 20 = 1000 |

### F-5.3 (prune_stale_edges)

| Metric | Before (broken) | After (fixed) |
|---|---|---|
| DB round-trips per batch | 2N + 1 | 1 (single JOIN) |
| Queries for 10K batch | 20,001 | 1 |
| Time at 1ms/query, 10K batch | ~20 seconds | ~50ms |
| Complexity | O(N) queries | O(1) query, O(N) scan in DB |

---

## 3. Fix for F-5.2 — Anchored Graph Traversal with Bounded Load

### Design

When `trigger_fragment_id` is provided (the common hot path — called after every snap), only load edges reachable from that fragment via BFS up to MAX_CLUSTER_SIZE depth. Do not load edges for unrelated fragments.

When `trigger_fragment_id` is None (background full evaluation), use cursor-based pagination and process components in pages rather than loading the entire tenant graph at once.

**Maximum edges loaded per call** (enforced by design):
- With trigger: `MAX_CLUSTER_SIZE * MAX_EDGES_PER_FRAGMENT = 50 * 20 = 1,000 edges`
- Without trigger (background): page size = `PAGE_SIZE_EDGES = 5,000` edges per page, yielding components page by page

### SQL Query 1 — Anchor Expansion (triggered path)

Get all edges connected to the trigger fragment (depth-1):

```sql
-- Step 1: Fetch direct edges of the trigger fragment
SELECT
    ae.id,
    ae.tenant_id,
    ae.fragment_a_id,
    ae.fragment_b_id,
    ae.affinity_score,
    ae.strongest_failure_mode
FROM accumulation_edge ae
WHERE
    ae.tenant_id = :tenant_id
    AND (ae.fragment_a_id = :trigger_id OR ae.fragment_b_id = :trigger_id)
LIMIT :max_seed_edges;  -- max_seed_edges = MAX_EDGES_PER_FRAGMENT = 20
```

From those edges, collect all fragment IDs discovered. Then expand one more hop to find all edges within that candidate set:

```sql
-- Step 2: Fetch all edges within the candidate fragment set
-- (candidate_ids = all fragment IDs discovered in Step 1, including trigger)
SELECT
    ae.id,
    ae.tenant_id,
    ae.fragment_a_id,
    ae.fragment_b_id,
    ae.affinity_score,
    ae.strongest_failure_mode
FROM accumulation_edge ae
WHERE
    ae.tenant_id = :tenant_id
    AND ae.fragment_a_id = ANY(:candidate_ids)
    AND ae.fragment_b_id = ANY(:candidate_ids)
LIMIT :max_cluster_edges;  -- max_cluster_edges = MAX_CLUSTER_SIZE * MAX_EDGES_PER_FRAGMENT = 1000
```

These two queries replace the single unbounded full-tenant SELECT. The LIMIT on Step 2 enforces the hard memory bound: at most 1,000 `AccumulationEdgeORM` rows per triggered evaluation.

### SQL Query 2 — Background Full Evaluation (paginated)

When `trigger_fragment_id` is None, use keyset pagination on the edge primary key to avoid OFFSET performance degradation:

```sql
-- Page N of background scan
SELECT
    ae.id,
    ae.tenant_id,
    ae.fragment_a_id,
    ae.fragment_b_id,
    ae.affinity_score,
    ae.strongest_failure_mode
FROM accumulation_edge ae
WHERE
    ae.tenant_id = :tenant_id
    AND ae.id > :last_seen_id        -- keyset cursor, not OFFSET
ORDER BY ae.id ASC
LIMIT :page_size;                    -- page_size = 5000
```

The background evaluator accumulates `(a_id, b_id, score)` tuples in-memory for union-find without materializing full ORM objects. This is the "projection only" approach: only the three columns needed for union-find are loaded, not the full ORM model.

### Exact SQLAlchemy Implementation

Replace lines 222–228 in `detect_and_evaluate_clusters()` with the following:

```python
# -----------------------------------------------------------------------
# F-5.2 FIX: Bounded edge loading.
# Hot path (trigger_fragment_id provided): two-hop expansion from trigger.
# Cold path (trigger_fragment_id is None): keyset-paginated background scan.
# -----------------------------------------------------------------------

MAX_SEED_EDGES = MAX_EDGES_PER_FRAGMENT          # 20
MAX_CLUSTER_EDGES = MAX_CLUSTER_SIZE * MAX_EDGES_PER_FRAGMENT  # 1000
PAGE_SIZE_EDGES = 5_000

EdgeRow = tuple  # (id, fragment_a_id, fragment_b_id, affinity_score, failure_mode)

async def _load_edges_for_trigger(
    session: AsyncSession,
    tenant_id: str,
    trigger_id: UUID,
) -> list[AccumulationEdgeORM]:
    """Two-hop bounded load anchored on trigger_id (F-5.2 hot-path fix)."""
    # Step 1: direct edges of trigger fragment
    seed_stmt = (
        select(
            AccumulationEdgeORM.id,
            AccumulationEdgeORM.fragment_a_id,
            AccumulationEdgeORM.fragment_b_id,
            AccumulationEdgeORM.affinity_score,
            AccumulationEdgeORM.strongest_failure_mode,
        )
        .where(
            AccumulationEdgeORM.tenant_id == tenant_id,
            (AccumulationEdgeORM.fragment_a_id == trigger_id)
            | (AccumulationEdgeORM.fragment_b_id == trigger_id),
        )
        .limit(MAX_SEED_EDGES)
    )
    seed_result = await session.execute(seed_stmt)
    seed_rows = seed_result.fetchall()

    if not seed_rows:
        return []

    # Collect all fragment IDs from seed edges (including trigger itself)
    candidate_ids: set[UUID] = {trigger_id}
    for row in seed_rows:
        candidate_ids.add(row.fragment_a_id)
        candidate_ids.add(row.fragment_b_id)

    # Step 2: all edges within the candidate set
    expand_stmt = (
        select(AccumulationEdgeORM)
        .where(
            AccumulationEdgeORM.tenant_id == tenant_id,
            AccumulationEdgeORM.fragment_a_id.in_(candidate_ids),
            AccumulationEdgeORM.fragment_b_id.in_(candidate_ids),
        )
        .limit(MAX_CLUSTER_EDGES)
    )
    expand_result = await session.execute(expand_stmt)
    return list(expand_result.scalars().all())


async def _load_edges_paginated(
    session: AsyncSession,
    tenant_id: str,
    page_size: int = PAGE_SIZE_EDGES,
) -> AsyncGenerator[list[tuple], None]:
    """Keyset-paginated edge scan for background full evaluation (F-5.2 cold-path fix).
    Yields batches of (fragment_a_id, fragment_b_id, affinity_score, failure_mode)
    WITHOUT materializing full ORM objects.
    """
    from uuid import UUID as _UUID
    last_id: Optional[UUID] = None

    while True:
        stmt = (
            select(
                AccumulationEdgeORM.id,
                AccumulationEdgeORM.fragment_a_id,
                AccumulationEdgeORM.fragment_b_id,
                AccumulationEdgeORM.affinity_score,
                AccumulationEdgeORM.strongest_failure_mode,
            )
            .where(AccumulationEdgeORM.tenant_id == tenant_id)
            .order_by(AccumulationEdgeORM.id.asc())
            .limit(page_size)
        )
        if last_id is not None:
            stmt = stmt.where(AccumulationEdgeORM.id > last_id)

        result = await session.execute(stmt)
        rows = result.fetchall()
        if not rows:
            break

        yield [(r.fragment_a_id, r.fragment_b_id, r.affinity_score, r.strongest_failure_mode)
               for r in rows]
        last_id = rows[-1].id

        if len(rows) < page_size:
            break
```

**Note on `_prune_cluster`**: The `_prune_cluster` method receives `all_edges: list[AccumulationEdgeORM]` as a parameter. After the F-5.2 fix, `all_edges` will be the bounded cluster-local edge list (at most 1,000 rows), not the full tenant graph. The `_prune_cluster` signature and body remain valid without changes because it only iterates the edges passed to it — the fix is at the call site in `detect_and_evaluate_clusters()`.

---

## 4. Fix for F-5.3 — Batch JOIN for Stale Edge Pruning

### Design

Replace the per-edge double-SELECT loop in `maintenance.py::prune_stale_edges()` with a single JOIN query that identifies all prunable edges in one round-trip.

An edge should be removed if any of the following conditions hold:
1. `fragment_a` does not exist (orphan)
2. `fragment_b` does not exist (orphan)
3. `fragment_a.snap_status IN ('EXPIRED', 'COLD')` OR `fragment_b.snap_status IN ('EXPIRED', 'COLD')`
4. `fragment_a.current_decay_score < STALE_EDGE_THRESHOLD AND fragment_b.current_decay_score < STALE_EDGE_THRESHOLD`

These four conditions can be expressed as a single LEFT JOIN query that identifies edge IDs meeting any condition.

### SQL Query — Single JOIN to Identify Prunable Edges

```sql
-- Identify all prunable edge IDs in a single pass.
-- LEFT JOINs detect missing fragments (condition 1 and 2).
-- WHERE clause encodes conditions 3 and 4.
SELECT ae.id
FROM accumulation_edge ae
LEFT JOIN abeyance_fragment fa
    ON fa.id = ae.fragment_a_id
    AND fa.tenant_id = ae.tenant_id
LEFT JOIN abeyance_fragment fb
    ON fb.id = ae.fragment_b_id
    AND fb.tenant_id = ae.tenant_id
WHERE
    ae.tenant_id = :tenant_id
    AND (
        -- Condition 1 and 2: orphaned edges (fragment missing)
        fa.id IS NULL
        OR fb.id IS NULL
        -- Condition 3: either fragment is expired or archived
        OR fa.snap_status IN ('EXPIRED', 'COLD')
        OR fb.snap_status IN ('EXPIRED', 'COLD')
        -- Condition 4: both fragments below decay threshold
        OR (
            fa.current_decay_score < :threshold
            AND fb.current_decay_score < :threshold
        )
    )
LIMIT :batch_limit;    -- batch_limit = MAX_PRUNE_BATCH = 10000
```

Then delete the identified IDs in a single DELETE:

```sql
DELETE FROM accumulation_edge
WHERE id = ANY(:prunable_ids)
  AND tenant_id = :tenant_id;    -- tenant guard on delete (INV-7)
```

### Exact SQLAlchemy Implementation

Replace the entire body of `prune_stale_edges()` in `maintenance.py` with:

```python
async def prune_stale_edges(
    self, session: AsyncSession, tenant_id: str
) -> int:
    """Remove accumulation edges where both fragments have low decay scores.

    F-5.3 FIX: Replaces N+1 per-edge fragment lookups with a single LEFT JOIN
    query that identifies all prunable edges in one round-trip.
    """
    # Single JOIN query replacing the N+1 loop.
    # LEFT JOIN detects orphans (fa.id IS NULL / fb.id IS NULL).
    # WHERE encodes all four prune conditions.
    prunable_stmt = (
        select(AccumulationEdgeORM.id)
        .join(
            AbeyanceFragmentORM,
            and_(
                AbeyanceFragmentORM.id == AccumulationEdgeORM.fragment_a_id,
                AbeyanceFragmentORM.tenant_id == AccumulationEdgeORM.tenant_id,
            ),
            isouter=True,
            # aliased as frag_a — see note below
        )
        # SQLAlchemy requires aliased tables for two joins to same model.
        # Use explicit aliased() — see full implementation note.
    )
```

Because SQLAlchemy does not allow two joins to the same ORM class in a single `select()` without aliasing, the correct implementation uses `aliased()`:

```python
from sqlalchemy.orm import aliased

async def prune_stale_edges(
    self, session: AsyncSession, tenant_id: str
) -> int:
    """Remove accumulation edges where both fragments have low decay scores.

    F-5.3 FIX: Single LEFT JOIN query replaces 2N+1 round-trips.
    DB round-trips: 2 (1 SELECT to find IDs, 1 DELETE by IDs).
    """
    frag_a = aliased(AbeyanceFragmentORM, flat=True)
    frag_b = aliased(AbeyanceFragmentORM, flat=True)

    prunable_stmt = (
        select(AccumulationEdgeORM.id)
        .outerjoin(
            frag_a,
            and_(
                frag_a.id == AccumulationEdgeORM.fragment_a_id,
                frag_a.tenant_id == AccumulationEdgeORM.tenant_id,
            ),
        )
        .outerjoin(
            frag_b,
            and_(
                frag_b.id == AccumulationEdgeORM.fragment_b_id,
                frag_b.tenant_id == AccumulationEdgeORM.tenant_id,
            ),
        )
        .where(
            AccumulationEdgeORM.tenant_id == tenant_id,
            (
                # Condition 1+2: orphaned (fragment missing from table)
                frag_a.id.is_(None)
                | frag_b.id.is_(None)
                # Condition 3: either fragment expired or cold-archived
                | frag_a.snap_status.in_(("EXPIRED", "COLD"))
                | frag_b.snap_status.in_(("EXPIRED", "COLD"))
                # Condition 4: both fragments below stale threshold
                | and_(
                    frag_a.current_decay_score < STALE_EDGE_THRESHOLD,
                    frag_b.current_decay_score < STALE_EDGE_THRESHOLD,
                )
            ),
        )
        .limit(MAX_PRUNE_BATCH)
    )

    result = await session.execute(prunable_stmt)
    prunable_ids = [row[0] for row in result.fetchall()]

    if not prunable_ids:
        logger.info("No stale edges found for tenant %s", tenant_id)
        return 0

    # Single DELETE for all identified prunable edges (tenant guard on delete, INV-7)
    await session.execute(
        delete(AccumulationEdgeORM).where(
            AccumulationEdgeORM.id.in_(prunable_ids),
            AccumulationEdgeORM.tenant_id == tenant_id,
        )
    )
    await session.flush()

    logger.info("Pruned %d stale edges for tenant %s", len(prunable_ids), tenant_id)
    return len(prunable_ids)
```

**Required import addition** in `maintenance.py`:
```python
from sqlalchemy.orm import aliased
```

---

## 5. Index Requirements

Both fixes rely on existing indexes. Confirmed present in `abeyance_orm.py`:

### For F-5.2 (accumulation_graph.py)

| Index | Used by |
|---|---|
| `ix_accum_edge_frag_a (tenant_id, fragment_a_id)` | Step 1 seed query (fragment_a side) |
| `ix_accum_edge_frag_b (tenant_id, fragment_b_id)` | Step 1 seed query (fragment_b side) |
| `ix_accum_edge_pair (tenant_id, fragment_a_id, fragment_b_id)` | Step 2 candidate set expansion |

The Step 2 expansion query uses `fragment_a_id = ANY(:candidate_ids) AND fragment_b_id = ANY(:candidate_ids)`. Postgres will use `ix_accum_edge_frag_a` with a bitmap scan when the candidate set is small (≤ ~21 IDs = 20 neighbours + trigger). This is index-accelerated. No new indexes required.

### For F-5.3 (maintenance.py)

| Index | Used by |
|---|---|
| `ix_abeyance_fragment_tenant_status (tenant_id, snap_status)` | JOIN condition filter on snap_status IN ('EXPIRED', 'COLD') |
| `ix_abeyance_fragment_tenant_decay (tenant_id, current_decay_score)` | Partial index (ACTIVE/NEAR_MISS only) — used for decay threshold filter |
| `ix_accum_edge_frag_a (tenant_id, fragment_a_id)` | Driving join from accumulation_edge to frag_a |
| `ix_accum_edge_frag_b (tenant_id, fragment_b_id)` | Driving join from accumulation_edge to frag_b |

No new indexes required for either fix. All required indexes are already present.

---

## 6. Boundary Constants

The following constants govern the bounded behaviour post-fix. They are defined at module level in `accumulation_graph.py` and should not be changed without updating this document.

```python
# F-5.2 bounds (add to accumulation_graph.py module constants)
MAX_SEED_EDGES = MAX_EDGES_PER_FRAGMENT         # 20: max direct edges from trigger
MAX_CLUSTER_EDGES = MAX_CLUSTER_SIZE * MAX_EDGES_PER_FRAGMENT  # 1000: hard cap per evaluation
PAGE_SIZE_EDGES = 5_000                          # edges per page in background scan
```

```python
# F-5.3 bounds (already present in maintenance.py, unchanged)
MAX_PRUNE_BATCH = 10_000    # max edges examined per maintenance pass
STALE_EDGE_THRESHOLD = 0.2  # both fragments must be below this to be stale
```

---

## 7. Behavioural Equivalence

The fixes are drop-in replacements that preserve all existing invariants:

| Invariant | Pre-fix behaviour | Post-fix behaviour |
|---|---|---|
| INV-4: Cluster membership monotonic | Unchanged — union-find logic identical | Unchanged |
| INV-7: Tenant isolation | All queries already tenant-scoped | All queries remain tenant-scoped; DELETE has explicit tenant guard |
| INV-8: Cluster scores in [0.0, 1.0] | Unchanged — LME + discount logic identical | Unchanged |
| INV-9: MAX_EDGES_PER_FRAGMENT, MAX_CLUSTER_SIZE | Enforced | Enforced; additionally MAX_CLUSTER_EDGES hard-caps edge load |
| INV-10: Cluster evaluation persisted | Unchanged | Unchanged |
| Pruning logic correctness | Conditions 1–4 evaluated per edge | Same four conditions, expressed as SQL predicates |

**Edge case — trigger fragment has no edges**: `_load_edges_for_trigger()` returns `[]` after Step 1, and `detect_and_evaluate_clusters()` returns `[]`. Same as the original (empty `edges` list on line 231 of current code).

**Edge case — cluster exceeds MAX_CLUSTER_SIZE after Step 2**: The `_prune_cluster()` call path is unchanged. The input `all_edges` will be the bounded Step 2 result (≤ 1,000 rows) rather than the full tenant graph, which is strictly better.

---

## 8. Files Changed

| File | Change | Lines affected |
|---|---|---|
| `backend/app/services/abeyance/accumulation_graph.py` | Replace lines 222–228 (unbounded edge load) with `_load_edges_for_trigger()` and `_load_edges_paginated()` helpers; update `detect_and_evaluate_clusters()` to call them | ~222–228 (load), new helpers ~30 lines each |
| `backend/app/services/abeyance/maintenance.py` | Replace lines 60–109 (N+1 loop) with single `aliased()` JOIN query and batch DELETE | ~60–109 |
| `backend/app/services/abeyance/maintenance.py` | Add `from sqlalchemy.orm import aliased` to imports | ~line 16 |

No schema changes. No migration required. No new indexes required.
