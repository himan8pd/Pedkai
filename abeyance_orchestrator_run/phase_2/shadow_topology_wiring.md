# Shadow Topology Wiring — Interface Specification
**Task**: T2.2
**Phase**: 2 (Interface Contracts)
**Date**: 2026-03-16
**Addresses**: F-3.1 (Severe), F-3.2 (Critical)

---

## 1. Problem Statement

Two audit findings describe the same systemic failure: Shadow Topology was built as a standalone service but is wired to nothing that actually uses it.

**F-3.2 (Critical)** — `EnrichmentChain.enrich()` constructs `entity_identifiers` (a list of string identifiers) but calls `get_neighbourhood(entity_ids=[])`, passing the empty list every time. The neighbourhood dict returned is always empty. The 384-dim topological sub-vector is therefore always embedded from entity-only text with no neighbourhood context, violating the design intent.

**F-3.1 (Severe)** — `SnapEngine._score_pair()` uses `_jaccard_similarity(entity_set_a, entity_set_b) * 0.8` as the topological component. `topological_proximity()` exists on `ShadowTopologyService` and does correct BFS shortest-path scoring, but is never called. `SnapEngine.__init__` does not accept a `shadow_topology` parameter at all.

This specification defines the interface changes required so both call sites work correctly. It does NOT specify enrichment chain internals (T1.3) or snap scoring weight changes (T2.3).

---

## 2. Scope and Boundaries

| In Scope | Out of Scope |
|---|---|
| `get_neighbourhood()` signature change (string identifiers) | Enrichment chain internal logic (T1.3) |
| `topological_proximity()` signature change (string identifiers) | Snap scoring weight profiles (T2.3) |
| `SnapEngine` constructor — add shadow_topology parameter | Accumulation graph changes |
| BFS depth limits for both call sites | CMDB export path |
| Performance bounds on both call paths | `enrich_on_validated_snap()` |
| Return type contract for `get_neighbourhood()` | |

---

## 3. Current Signatures (Baseline)

```python
# shadow_topology.py — ShadowTopologyService

async def get_neighbourhood(
    self,
    session: AsyncSession,
    tenant_id: str,
    entity_ids: list[UUID],        # PROBLEM: callers have string identifiers, not UUIDs
    max_hops: int = 2,
) -> dict                           # PROBLEM: dict contents not contractually defined
```

```python
async def topological_proximity(
    self,
    session: AsyncSession,
    tenant_id: str,
    entity_set_a: set[UUID],       # PROBLEM: callers have string identifiers
    entity_set_b: set[UUID],       # PROBLEM: snap engine never calls this at all
    max_hops: int = 3,
) -> float
```

```python
# snap_engine.py — SnapEngine

def __init__(
    self,
    provenance: ProvenanceLogger,
    notifier: Optional[RedisNotifier] = None,
    # MISSING: no shadow_topology parameter
)
```

---

## 4. Required Interface Changes

### 4.1 `get_neighbourhood()` — Accept Entity Identifiers

**Change**: Add `entity_identifiers` parameter (string identifiers from entity extraction). Resolve to UUIDs internally via `get_or_create_entity`. The existing `entity_ids` parameter is retained for callers that already hold UUIDs (e.g. `enrich_on_validated_snap`).

```python
async def get_neighbourhood(
    self,
    session: AsyncSession,
    tenant_id: str,
    entity_identifiers: list[str],          # NEW: string identifiers from enrichment
    max_hops: int = 2,
    entity_ids: Optional[list[UUID]] = None, # KEPT: for UUID-based callers; merged with resolved identifiers
) -> NeighbourhoodResult:                    # CHANGED: typed dataclass instead of bare dict
```

**Resolution rule**: For each string in `entity_identifiers`, call `get_or_create_entity(session, tenant_id, identifier)` to resolve to a UUID before BFS begins. This is the same upsert path already used by CMDB ingestion. The call is idempotent — if the entity does not exist in the shadow graph, it is created with `origin="ENRICHMENT_OBSERVED"`.

**Merge rule**: If both `entity_identifiers` and `entity_ids` are provided, union the resolved UUID sets before BFS. Deduplication is by UUID.

**Constraint**: At least one of `entity_identifiers` or `entity_ids` must be non-empty. If both are empty or None, return an empty `NeighbourhoodResult` without touching the DB.

#### 4.1.1 Return Type: `NeighbourhoodResult`

Replace the bare `dict` return with a typed dataclass. This eliminates silent key-access bugs in the enrichment chain's `_build_topo_text` and `_compute_embeddings`.

```python
@dataclass
class NeighbourhoodResult:
    # Seed entities (depth 0) — the requested entities themselves
    seed_entities: list[ShadowEntityORM]

    # All expanded entities keyed by hop depth (1..max_hops)
    # depth 0 is the seeds; depth N contains entities first seen at hop N
    entities_by_depth: dict[int, list[ShadowEntityORM]]

    # All relationships traversed during BFS (tenant-scoped)
    relationships: list[ShadowRelationshipORM]

    # Flat list of all unique entity identifiers in the result (seeds + expanded)
    all_identifiers: list[str]

    # Total entity count (seeds + expanded, deduplicated)
    total_entities: int

    # Total relationship count
    total_relationships: int

    # Whether BFS was truncated by MAX_BFS_RESULT
    truncated: bool

    # Effective max_hops used (may be < requested if clamped)
    effective_max_hops: int
```

The `entities_by_depth` dict allows the enrichment chain to assign `topological_distance` to extracted entities (depth 0 = direct entity, depth 1 = one hop away, etc.), which populates `FragmentEntityRefORM.topological_distance` correctly.

#### 4.1.2 BFS Depth Limits for the Enrichment Call Site

The enrichment chain calls `get_neighbourhood` during fragment creation, on the hot ingestion path. The following constraints apply:

| Parameter | Value | Rationale |
|---|---|---|
| `max_hops` default | 2 | Neighbourhood at depth 2 captures directly-connected peers and one-hop transit paths — sufficient for topological context text |
| Hard ceiling enforced inside method | `min(max_hops, MAX_HOPS)` where `MAX_HOPS = 3` | Already enforced; no change needed |
| `MAX_BFS_RESULT` | 500 (existing constant) | Unchanged; truncation flag now surfaced in return type |
| `MAX_RELATIONSHIPS_PER_ENTITY` | 200 (existing constant) | Unchanged; per-frontier-batch limit |

**Rationale for max_hops=2 default**: At depth 3 with a dense telco graph (200 relationships/entity, 500-node cap) the BFS can issue up to 3 DB round-trips per fragment. Depth 2 bounds this at 2 round-trips while still capturing enough neighbourhood for meaningful topo-text. The snap engine call site uses max_hops=3 (see 4.2).

#### 4.1.3 Query Complexity Bound

The existing implementation issues one `SELECT ... WHERE from_entity_id IN (...) OR to_entity_id IN (...)` per BFS depth level. With `max_hops=2` and frontier sizes bounded by `MAX_BFS_RESULT`:

- Round-trips: exactly 2 relationship queries + 1 entity fetch + N entity-resolution upserts (one per seed identifier)
- Entity resolution upserts: bounded by `len(entity_identifiers)`. In practice the enrichment chain extracts at most ~20 entities (hardcoded `entities[:20]` in `_build_topo_text`). Upper bound: 20 upsert queries.
- Total DB operations per `get_neighbourhood` call: `20 + 2 + 1 = 23` maximum.

To keep this bounded, the implementation must not issue one upsert per identifier serially inside the BFS loop. Resolution must happen before BFS begins.

---

### 4.2 `topological_proximity()` — Accept Entity Identifiers

**Change**: Accept string identifiers in addition to UUIDs. The same internal resolution path as 4.1 is used.

```python
async def topological_proximity(
    self,
    session: AsyncSession,
    tenant_id: str,
    entity_set_a: set[str],         # CHANGED: string identifiers (from FragmentEntityRefORM)
    entity_set_b: set[str],         # CHANGED: string identifiers
    max_hops: int = 3,
    entity_uuids_a: Optional[set[UUID]] = None,  # KEPT: for UUID-based callers
    entity_uuids_b: Optional[set[UUID]] = None,
) -> float
```

**Resolution rule**: Same as 4.1 — resolve string identifiers to UUIDs via `get_or_create_entity` before BFS. Merge with any UUID sets provided.

**Return value contract** (unchanged from current implementation):
- `1.0` if the two sets share any entity (direct overlap after resolution)
- `1.0 / depth` where depth is the hop count of the shortest BFS path between any member of set_a and any member of set_b
- `0.0` if no path found within `max_hops`

The existing formula `1.0 / depth` produces the range `(0.0, 1.0]`. This is correct for use as the topological score component in snap scoring. No change to the formula is needed.

#### 4.2.1 BFS Depth Limits for the Snap Engine Call Site

The snap engine calls `topological_proximity` during `_score_pair`, which may compare up to `MAX_CANDIDATES = 200` fragment pairs per evaluation. This is a significantly more performance-sensitive call site than the enrichment chain.

| Parameter | Value | Rationale |
|---|---|---|
| `max_hops` for snap engine | 3 (existing default) | Sufficient for telco topology where most failure-correlated entities are within 3 hops |
| Hard ceiling | `min(max_hops, MAX_HOPS)` where `MAX_HOPS = 3` | Already enforced |
| Early-exit on direct overlap | Yes (existing: `if entity_set_a & entity_set_b: return 1.0`) | Must be preserved and extended to cover string-level overlap before UUID resolution |

**Early-exit extension**: Before any DB call, check if `entity_set_a & entity_set_b` is non-empty at the string level. This avoids all DB round-trips for the common case where two fragments mention the same entity identifier. Only proceed to UUID resolution and BFS if no string-level overlap exists.

#### 4.2.2 Query Complexity Bound for Snap Engine

The snap engine compares up to 200 fragment pairs. Each call to `topological_proximity` may issue up to `max_hops` relationship queries + resolution upserts. However:

- String-level early-exit eliminates DB calls for same-entity pairs (expected to be the majority of SNAP-bound pairs).
- For remaining pairs, resolution upserts are bounded by `len(entity_set_a) + len(entity_set_b)`. Entity sets per fragment are bounded by `MAX_CANDIDATES` retrieval logic, but in practice telco fragments extract 2-10 entities.
- Worst case without early-exit: `200 pairs × (10 + 10 upserts + 3 BFS queries) = 4,600` DB operations per evaluation.
- With string-level early-exit for pairs that share an entity (expected: >50% of snappable pairs): worst case halves to ~2,300.

**Required mitigation**: The snap engine must batch `topological_proximity` calls by reusing an entity-resolution cache within a single `evaluate()` call. The cache maps `(tenant_id, entity_identifier) → UUID` and is populated on first resolution, eliminating redundant upserts across fragment pairs evaluated in the same session. This cache is scoped to the `evaluate()` invocation and must not be persisted between calls.

This cache is implemented in the snap engine, not in `ShadowTopologyService`. The service itself remains stateless.

---

### 4.3 `SnapEngine` Constructor — Add `shadow_topology` Parameter

```python
def __init__(
    self,
    provenance: ProvenanceLogger,
    notifier: Optional[RedisNotifier] = None,
    shadow_topology: Optional[ShadowTopologyService] = None,   # NEW
)
```

`shadow_topology` is Optional for backward compatibility with existing tests. When `None`, `_score_pair` falls back to the existing Jaccard heuristic. When provided, `topological_proximity` is called instead.

The fallback must be explicit and logged:

```python
if self._shadow_topology is None:
    # Fallback: Jaccard*0.8 heuristic (F-3.1: used when topology service unavailable)
    logger.warning(
        "ShadowTopologyService not injected; using Jaccard*0.8 topo heuristic "
        "(degraded mode — wire shadow_topology for production)"
    )
    topo_score = _jaccard_similarity(new_entities, stored_entities) * 0.8
else:
    topo_score = await self._shadow_topology.topological_proximity(
        session, tenant_id, new_entities, stored_entities, max_hops=3
    )
```

This makes the degradation mode explicit and detectable via log monitoring.

---

### 4.4 `EnrichmentChain` — Fix the Call Site (F-3.2)

The current enrichment chain call is:

```python
neighbourhood = await self._shadow_topology.get_neighbourhood(
    session, tenant_id,
    entity_ids=[],          # BUG: always empty
    max_hops=2,
)
```

The corrected call site (implementing the new interface from 4.1):

```python
entity_identifiers = [e["identifier"] for e in entities]
neighbourhood = await self._shadow_topology.get_neighbourhood(
    session, tenant_id,
    entity_identifiers=entity_identifiers,
    max_hops=2,
)
```

The `neighbourhood` variable is then a `NeighbourhoodResult` dataclass. All downstream consumers (`_build_topo_text`, `_compute_embeddings`) must be updated to access typed fields (`neighbourhood.all_identifiers`, `neighbourhood.entities_by_depth`) rather than dict keys. This is covered by T1.3.

---

## 5. Interface Summary

### 5.1 Modified Method Signatures

```python
# ShadowTopologyService

async def get_neighbourhood(
    self,
    session: AsyncSession,
    tenant_id: str,
    entity_identifiers: list[str],
    max_hops: int = 2,
    entity_ids: Optional[list[UUID]] = None,
) -> NeighbourhoodResult

async def topological_proximity(
    self,
    session: AsyncSession,
    tenant_id: str,
    entity_set_a: set[str],
    entity_set_b: set[str],
    max_hops: int = 3,
    entity_uuids_a: Optional[set[UUID]] = None,
    entity_uuids_b: Optional[set[UUID]] = None,
) -> float
```

```python
# SnapEngine

def __init__(
    self,
    provenance: ProvenanceLogger,
    notifier: Optional[RedisNotifier] = None,
    shadow_topology: Optional[ShadowTopologyService] = None,
)
```

### 5.2 New Type

```python
@dataclass
class NeighbourhoodResult:
    seed_entities: list[ShadowEntityORM]
    entities_by_depth: dict[int, list[ShadowEntityORM]]
    relationships: list[ShadowRelationshipORM]
    all_identifiers: list[str]
    total_entities: int
    total_relationships: int
    truncated: bool
    effective_max_hops: int
```

### 5.3 Call Site Corrections

| File | Current (broken) | Required |
|---|---|---|
| `enrichment_chain.py:122-127` | `entity_ids=[]` | `entity_identifiers=[e["identifier"] for e in entities]` |
| `snap_engine.py:__init__` | No `shadow_topology` param | Add `shadow_topology: Optional[ShadowTopologyService] = None` |
| `snap_engine.py:_score_pair` | `_jaccard_similarity(...) * 0.8` | Call `topological_proximity` when service available; log fallback when not |

---

## 6. BFS Depth Limits — Decision Record

| Call Site | `max_hops` | Hard Ceiling | Rationale |
|---|---|---|---|
| `EnrichmentChain.enrich` | 2 | 3 | 2 round-trips on ingestion path; captures direct peers and one-hop transit |
| `SnapEngine._score_pair` | 3 | 3 | Snap needs broader proximity; string early-exit mitigates cost |
| `topological_proximity` default | 3 | 3 | Existing constant unchanged |
| `get_neighbourhood` default | 2 | 3 | Enrichment default; override to 3 for any diagnostic/API use |

`MAX_HOPS = 3` is a hard ceiling inside `ShadowTopologyService`. It is not caller-overridable. Any `max_hops` argument exceeding 3 is silently clamped to 3. This is already implemented and must be preserved.

---

## 7. Performance Invariants

The following invariants must hold after wiring:

| Invariant | Enforcement |
|---|---|
| `get_neighbourhood` issues at most `max_hops` relationship queries per call | BFS loop depth bounded by clamped `max_hops` |
| `get_neighbourhood` fetches at most `MAX_BFS_RESULT = 500` entities per call | Visited-set check inside BFS loop (already implemented) |
| `topological_proximity` issues zero DB queries when string-level overlap detected | Early-exit before resolution step |
| `SnapEngine.evaluate` does not upsert the same entity identifier more than once per evaluation | Per-evaluation resolution cache in snap engine |
| Both methods are tenant-scoped on all queries | `ShadowEntityORM.tenant_id == tenant_id` and `ShadowRelationshipORM.tenant_id == tenant_id` on every SELECT (already implemented for BFS; must extend to resolution upserts) |

---

## 8. Backward Compatibility

- Existing `entity_ids: list[UUID]` parameter on `get_neighbourhood` becomes optional with default `None`. All existing internal callers (e.g. `enrich_on_validated_snap` indirectly, the API router) continue to work without change.
- `SnapEngine` constructed without `shadow_topology` continues to work with the Jaccard fallback, logged as degraded mode.
- `NeighbourhoodResult` is a new return type. Existing callers accessing the dict directly will break. The only production caller is `enrichment_chain.py`; its update is specified in T1.3. The API router at `GET /neighbourhood/{entity_identifier}` serialises the result to JSON; it must be updated to serialise `NeighbourhoodResult` instead of a bare dict.

---

## 9. Files to Modify

| File | Change |
|---|---|
| `/Users/himanshu/Projects/Pedkai/backend/app/services/abeyance/shadow_topology.py` | Update `get_neighbourhood` and `topological_proximity` signatures; add `NeighbourhoodResult` dataclass; add entity-identifier resolution logic before BFS |
| `/Users/himanshu/Projects/Pedkai/backend/app/services/abeyance/snap_engine.py` | Add `shadow_topology` constructor parameter; add resolution cache; update `_score_pair` to call `topological_proximity` with fallback |
| `/Users/himanshu/Projects/Pedkai/backend/app/services/abeyance/enrichment_chain.py` | Fix `entity_ids=[]` bug; pass `entity_identifiers`; update `_build_topo_text` and `_compute_embeddings` to consume `NeighbourhoodResult` (T1.3 scope) |
| `/Users/himanshu/Projects/Pedkai/backend/app/api/shadow_topology.py` | Update `GET /neighbourhood/{entity_identifier}` serialisation for `NeighbourhoodResult` |
