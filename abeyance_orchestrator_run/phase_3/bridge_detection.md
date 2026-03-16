# Bridge Detection — Discovery Mechanism #4
## Cross-Cluster Bridge Detection for Abeyance Memory v3.0

**Task**: T3.1 — Bridge Detection Algorithm Design
**Date**: 2026-03-16
**Discovery Tier**: TIER 1 — Foundation (no LLM dependency; pure graph algorithm)
**Reads**: `accumulation_graph.py`, `accumulation_graph_fix.md` (T2.1)
**Writes to**: `bridge_discovery` table (new), `bridge_discovery_provenance` table (new)

---

## 1. Problem Statement

The accumulation graph encodes affinity edges between fragments that share entities. Cluster detection (union-find in `detect_and_evaluate_clusters()`) groups tightly connected fragments into clusters. However, union-find treats edges uniformly — it cannot distinguish a bridge fragment that connects two otherwise-disjoint sub-graphs from a fragment that is merely an internal cluster node.

A **bridge fragment** is a fragment whose removal would disconnect two or more currently-connected components. It represents a cross-domain linkage that no pairwise scoring mechanism can surface: the fragment scores high affinity with two groups that have zero direct edges between them. This is the cross-cluster discovery signal.

**Why pairwise scoring misses it**: `snap_engine.evaluate()` retrieves candidates via shared entity refs. If cluster A and cluster B share no entity refs, they never appear in each other's candidate lists. The bridge fragment is the only path through which this cross-domain relationship is observable.

**Target**: Detect bridge fragments systematically, classify them, and persist the discovery as a provenance-linked record.

---

## 2. Definitions

**Accumulation graph G(V, E)**:
- `V` = set of active `AbeyanceFragmentORM` IDs for a tenant
- `E` = set of `AccumulationEdgeORM` rows for that tenant
- Edge weight `w(u,v)` = `affinity_score` in [0.0, 1.0]
- Graph is undirected (edges are symmetric; `(a_id, b_id)` treated as `{a_id, b_id}`)

**Cluster**: A connected component of G with `|V| >= MIN_CLUSTER_SIZE` (currently 3).

**Bridge edge**: An edge `(u,v)` whose removal increases the number of connected components. Standard graph theory definition.

**Articulation point**: A vertex whose removal increases the number of connected components. Also called a cut vertex.

**Bridge fragment** (operational definition): A fragment `f` that is an articulation point in the component subgraph `G_C` induced by the cluster containing `f`, AND whose removal splits that component into at least two sub-components each satisfying `|sub-component| >= MIN_CLUSTER_SIZE`.

**Bridge discovery** (signal definition): A bridge fragment constitutes a discovery — not routine connectivity — when ALL of the following hold:

| Condition | Threshold | Rationale |
|---|---|---|
| Both sub-components after removal meet minimum size | `>= MIN_CLUSTER_SIZE` (3) | Single-fragment orphans are noise, not discoveries |
| Fragment betweenness centrality in its component | `>= BRIDGE_BC_THRESHOLD` (0.30) | High centrality = structurally load-bearing, not coincidental |
| Fragment spans at least 2 distinct entity domains | Verified via `fragment_entity_ref.entity_domain` | Cross-domain connectivity is the signal; same-domain bridging is expected |
| No existing bridge discovery record for this fragment in the same component configuration | Deduplication check | Avoid re-firing on stable topology |

A bridge fragment that fails any condition is logged as `ROUTINE_CONNECTIVITY` and not surfaced as a discovery event.

---

## 3. Algorithm

### 3.1 Scope and Trigger

Bridge detection runs in two modes:

**Triggered mode** (hot path): Called after `detect_and_evaluate_clusters()` confirms a cluster change for a trigger fragment. Only the affected component is analyzed. Input is the bounded edge set already loaded by T2.1's `_load_edges_for_trigger()` — no additional DB load required for the component.

**Background mode** (cold path): Scheduled maintenance pass. Iterates components via the paginated edge scan `_load_edges_paginated()` from T2.1. Each page yields a partial edge set; components are accumulated across pages before bridge detection runs on each fully-assembled component.

### 3.2 Component Isolation

Before running bridge detection, isolate the component containing the trigger fragment (triggered mode) or each component from the page (background mode).

```
Input: edge_list  — list of (fragment_a_id, fragment_b_id, affinity_score)
       trigger_id — UUID (triggered mode) or None (background mode)

Step A — Build adjacency:
  adj = defaultdict(set)
  for (a, b, score) in edge_list:
    adj[a].add(b)
    adj[b].add(a)

Step B — BFS to isolate component of trigger_id:
  (triggered mode only)
  visited = {trigger_id}
  queue   = deque([trigger_id])
  while queue:
    node = queue.popleft()
    for nbr in adj[node]:
      if nbr not in visited:
        visited.add(nbr)
        queue.append(nbr)
  component_nodes = visited
  component_edges = [(a, b, s) for (a, b, s) in edge_list
                     if a in component_nodes and b in component_nodes]
```

For background mode, standard BFS-based connected components on the full page edge set yields all components in the page.

### 3.3 Articulation Point Detection — Tarjan's Algorithm

Run Tarjan's linear-time articulation point algorithm on the component subgraph. This is O(V + E) per component.

```
Given: component_nodes (set of UUIDs), adj (adjacency dict scoped to component)

Assign integer indices to nodes:
  index_of = {node: i for i, node in enumerate(component_nodes)}
  node_of  = {i: node for i, node in enumerate(component_nodes)}

disc    = [-1] * n          # discovery time
low     = [ 0] * n          # lowest disc reachable via subtree
parent  = [-1] * n
visited = [False] * n
ap_set  = set()             # articulation point indices
timer   = [0]

def dfs(u: int):
    visited[u] = True
    disc[u] = low[u] = timer[0]
    timer[0] += 1
    child_count = 0

    for v_uuid in adj[node_of[u]]:
        v = index_of[v_uuid]
        if not visited[v]:
            child_count += 1
            parent[v] = u
            dfs(v)
            low[u] = min(low[u], low[v])

            # Articulation point conditions:
            # (a) u is root of DFS tree and has 2+ children
            if parent[u] == -1 and child_count > 1:
                ap_set.add(u)
            # (b) u is not root and low[v] >= disc[u]
            if parent[u] != -1 and low[v] >= disc[u]:
                ap_set.add(u)

        elif v != parent[u]:
            low[u] = min(low[u], disc[v])

for start_idx in range(n):
    if not visited[start_idx]:
        dfs(start_idx)

articulation_points = {node_of[i] for i in ap_set}
```

**Iterative DFS note**: Python's default recursion limit (1000) may be breached for components near MAX_CLUSTER_SIZE (50). Since MAX_CLUSTER_SIZE = 50, max recursion depth is 50 — well within limit. No iterative conversion required.

**Complexity**: O(V + E) per component. With MAX_CLUSTER_SIZE = 50 and MAX_EDGES_PER_FRAGMENT = 20, worst-case per component is O(50 + 1000) = O(1050) operations.

### 3.4 Betweenness Centrality — Brandes Approximation

Full betweenness centrality (Brandes, 2001) is O(VE) per graph. For the component size bounds here (V ≤ 50, E ≤ 1000), this is O(50,000) operations — tractable without approximation.

However, for correctness and future-proofing (if MAX_CLUSTER_SIZE is raised), the algorithm uses **pivot-sampled approximate betweenness** with a configurable sample count. For V ≤ 50, full Brandes is used (all V pivots). For V > 50, use `min(V, BRIDGE_BC_SAMPLE_SIZE)` pivots.

**Brandes algorithm per component**:

```
BC[v] = 0.0 for all v in component

For each source s in component:
    S = empty stack
    P[w] = [] for all w          # predecessors on shortest paths from s
    sigma[w] = 0 for all w;  sigma[s] = 1
    d[w] = -1 for all w;     d[s] = 0
    Q = deque([s])

    # BFS phase (unweighted — topology only, not affinity-weighted)
    while Q:
        v = Q.popleft()
        S.push(v)
        for w in adj[v]:
            if d[w] < 0:
                Q.append(w)
                d[w] = d[v] + 1
            if d[w] == d[v] + 1:
                sigma[w] += sigma[v]
                P[w].append(v)

    # Accumulation phase
    delta[w] = 0.0 for all w
    while S not empty:
        w = S.pop()
        for v in P[w]:
            delta[v] += (sigma[v] / sigma[w]) * (1 + delta[w])
        if w != s:
            BC[w] += delta[w]

# Normalize by (V-1)(V-2) for directed, (V-1)(V-2)/2 for undirected
# For undirected graph (our case):
norm = (len(component_nodes) - 1) * (len(component_nodes) - 2) / 2.0
if norm > 0:
    BC[v] = BC[v] / norm for all v
```

**Note on edge weights**: Betweenness is computed on the unweighted topology only (hop count). Affinity scores are not used as edge weights here — topological centrality is what matters for bridge detection. Affinity scores are used separately in the discovery quality assessment (Section 4).

**Complexity**: O(V * (V + E)) per component. Bounded: O(50 * 1050) = O(52,500) operations per component call. Negligible.

### 3.5 Sub-component Size Verification

For each articulation point candidate `f`, compute the sub-component sizes that would result from `f`'s removal:

```
For candidate f in articulation_points:
    adj_minus_f = {v: adj[v] - {f} for v in component_nodes if v != f}
    remaining_nodes = component_nodes - {f}

    # BFS to find all sub-components
    sub_components = []
    unvisited = set(remaining_nodes)
    while unvisited:
        start = next(iter(unvisited))
        sub_vis = {start}
        queue = deque([start])
        while queue:
            node = queue.popleft()
            for nbr in adj_minus_f.get(node, set()):
                if nbr in unvisited:
                    sub_vis.add(nbr)
                    unvisited.discard(nbr)
                    queue.append(nbr)
        unvisited -= sub_vis
        sub_components.append(frozenset(sub_vis))

    # Only count sub-components that meet MIN_CLUSTER_SIZE
    qualifying_sub_components = [sc for sc in sub_components
                                  if len(sc) >= MIN_CLUSTER_SIZE]
    if len(qualifying_sub_components) >= 2:
        # f is a qualifying bridge fragment — proceed to domain check
```

**Complexity**: O(V + E) per candidate. In worst case all 50 nodes are articulation points: O(50 * 1050) = O(52,500). Still bounded.

### 3.6 Domain Span Verification

For each qualifying bridge fragment `f`, load its entity domain set from the DB:

```sql
SELECT DISTINCT entity_domain
FROM fragment_entity_ref
WHERE fragment_id = :fragment_id
  AND tenant_id   = :tenant_id
  AND entity_domain IS NOT NULL;
```

This is a single indexed lookup (index on `(tenant_id, fragment_id)` already present per `FragmentEntityRefORM`). If the fragment spans `>= 2` distinct `entity_domain` values, the domain span condition passes.

### 3.7 Discovery Classification

```
For each qualified bridge fragment f:

  bc_score = BC[f]                           # normalized betweenness
  domains  = entity_domains(f)               # set of domain strings

  if bc_score >= BRIDGE_BC_THRESHOLD         # 0.30
     and len(domains) >= 2:
       classification = "BRIDGE_DISCOVERY"
       severity       = _bridge_severity(bc_score, sub_components)
  else:
       classification = "ROUTINE_CONNECTIVITY"
       severity       = None

def _bridge_severity(bc: float, sub_components: list[frozenset]) -> str:
    """
    CRITICAL : bc >= 0.60 AND largest sub_component >= 10 fragments
    HIGH     : bc >= 0.45 OR  largest sub_component >= 7  fragments
    MEDIUM   : bc >= 0.30  (minimum qualifying threshold)
    """
    max_sub = max(len(sc) for sc in sub_components)
    if bc >= 0.60 and max_sub >= 10:
        return "CRITICAL"
    elif bc >= 0.45 or max_sub >= 7:
        return "HIGH"
    else:
        return "MEDIUM"
```

---

## 4. Bridge Discovery Record Schema

### Table: `bridge_discovery`

```sql
CREATE TABLE bridge_discovery (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id               VARCHAR(64) NOT NULL,

    -- The fragment that is the articulation point
    bridge_fragment_id      UUID NOT NULL
                            REFERENCES abeyance_fragment(id) ON DELETE CASCADE,

    -- Classification outcome
    classification          VARCHAR(32) NOT NULL,
    -- CHECK classification IN ('BRIDGE_DISCOVERY', 'ROUTINE_CONNECTIVITY')
    severity                VARCHAR(16),
    -- CHECK severity IN ('CRITICAL', 'HIGH', 'MEDIUM', NULL)

    -- Betweenness centrality score (normalized, within component)
    betweenness_centrality  FLOAT NOT NULL,

    -- Number of qualifying sub-components produced by removal
    sub_component_count     INTEGER NOT NULL,

    -- Entity domains observed on the bridge fragment
    entity_domains          JSONB NOT NULL,   -- e.g. ["RAN", "TRANSPORT"]

    -- Fingerprint of the component configuration at detection time
    -- Hash of (sorted member UUIDs) — used for deduplication
    component_fingerprint   VARCHAR(64) NOT NULL,

    -- Timestamps
    detected_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    suppressed              BOOLEAN NOT NULL DEFAULT FALSE,
    suppressed_reason       TEXT,

    CONSTRAINT uq_bridge_fragment_component
        UNIQUE (tenant_id, bridge_fragment_id, component_fingerprint)
);

CREATE INDEX ix_bridge_disc_tenant_fragment
    ON bridge_discovery (tenant_id, bridge_fragment_id);

CREATE INDEX ix_bridge_disc_tenant_class
    ON bridge_discovery (tenant_id, classification, detected_at DESC);

CREATE INDEX ix_bridge_disc_component
    ON bridge_discovery (tenant_id, component_fingerprint);
```

### Table: `bridge_discovery_provenance`

Normalized provenance: one row per sub-component produced by the bridge fragment's removal.

```sql
CREATE TABLE bridge_discovery_provenance (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    bridge_discovery_id UUID NOT NULL
                        REFERENCES bridge_discovery(id) ON DELETE CASCADE,
    tenant_id           VARCHAR(64) NOT NULL,

    -- Which sub-component this row describes
    sub_component_index INTEGER NOT NULL,    -- 0-based ordinal
    sub_component_size  INTEGER NOT NULL,

    -- Cluster identity before the bridge fragment was (hypothetically) removed
    -- Stable cluster label derived from component_fingerprint
    cluster_label       VARCHAR(64) NOT NULL,

    -- Representative fragment IDs in this sub-component (for UI navigation)
    -- Capped at BRIDGE_PROV_MAX_MEMBERS to bound JSONB size
    member_fragment_ids JSONB NOT NULL,      -- list of UUID strings

    -- Domain summary of this sub-component
    dominant_domain     VARCHAR(32),         -- most common entity_domain in sub-component
    domain_distribution JSONB NOT NULL,      -- {"RAN": 3, "TRANSPORT": 2}

    CONSTRAINT uq_bridge_prov_subcomp
        UNIQUE (bridge_discovery_id, sub_component_index)
);

CREATE INDEX ix_bridge_prov_discovery
    ON bridge_discovery_provenance (bridge_discovery_id);

CREATE INDEX ix_bridge_prov_tenant_cluster
    ON bridge_discovery_provenance (tenant_id, cluster_label);
```

### Constants

```python
BRIDGE_BC_THRESHOLD       = 0.30   # minimum normalized betweenness for discovery
BRIDGE_BC_SAMPLE_SIZE     = 50     # max pivots for approx BC (exact for V <= 50)
BRIDGE_PROV_MAX_MEMBERS   = 20     # max fragment IDs stored per sub-component row
```

---

## 5. Provenance: Which Clusters Were Connected, Through Which Fragment

The `bridge_discovery_provenance` table answers this question deterministically. For a given `bridge_discovery` record:

- `bridge_fragment_id` is the connecting fragment
- Each `bridge_discovery_provenance` row describes one sub-component that exists on one side of the bridge
- `cluster_label` is a stable identifier: `sha256(sorted(member_fragment_ids))[:16]` — a content-addressed label for the sub-component at detection time
- `dominant_domain` and `domain_distribution` characterize what domain each side of the bridge represents

**Full provenance reconstruction query**:

```sql
SELECT
    bd.bridge_fragment_id,
    bd.betweenness_centrality,
    bd.severity,
    bd.entity_domains         AS bridge_domains,
    bd.detected_at,
    bdp.sub_component_index,
    bdp.sub_component_size,
    bdp.cluster_label,
    bdp.dominant_domain,
    bdp.domain_distribution,
    bdp.member_fragment_ids
FROM bridge_discovery bd
JOIN bridge_discovery_provenance bdp
    ON bdp.bridge_discovery_id = bd.id
WHERE bd.tenant_id = :tenant_id
  AND bd.bridge_fragment_id = :fragment_id
  AND bd.classification = 'BRIDGE_DISCOVERY'
ORDER BY bd.detected_at DESC,
         bdp.sub_component_index ASC;
```

**Component fingerprint for deduplication**: The `component_fingerprint` is `sha256("|".join(sorted(str(uuid) for uuid in component_nodes)))[:32]`. When the same bridge fragment is detected in the same component (same membership), the `UNIQUE (tenant_id, bridge_fragment_id, component_fingerprint)` constraint suppresses duplicate insertion. The caller catches `IntegrityError` and skips re-insertion without logging.

---

## 6. Concrete Telecom Example

### Scenario: Power-Grid Alarm Cluster Bridged to RAN Alarm Cluster

**Background**: A major telecom operator runs passive monitoring of both power infrastructure and RAN. Two separate clusters have formed in the accumulation graph over 72 hours:

**Cluster A** (6 fragments, domain = TRANSPORT/POWER):
- F1: "Rectifier module fault at PSU-SITE-NRH-04, output voltage drop to 44.2V"
- F2: "Generator transfer switch activation, PSU-SITE-NRH-04 grid failover"
- F3: "Battery discharge alarm, PSU-SITE-NRH-04, capacity 38%"
- F4: "UPS bypass mode engaged, PSU-SITE-NRH-04"
- F5: "Thermal alarm on power cabinet, SITE-NRH-04, ambient +12°C above threshold"
- F6: "Maintenance ticket: PSU-SITE-NRH-04 generator test scheduled CHG-2026-MAR-441"

**Cluster B** (5 fragments, domain = RAN):
- F7:  "ENB-2241 S1 link degradation, packet loss 12%, TN-NORTH-0047"
- F8:  "GNB-2241 CQI drop below threshold, 8 UEs affected, SITE-NRH-04"
- F9:  "LTE-CELL-2241-03 throughput alarm, DL 4.2 Mbps vs baseline 31 Mbps"
- F10: "NR-CELL-2241-01 RACH failure spike, access attempts failed 34%"
- F11: "Capacity alarm: ENB-2241 PRB utilization 94%, interference suspected"

**Bridge fragment** (F12, ingested after both clusters formed):
- "Site power brownout impact assessment: SITE-NRH-04 power degradation correlated with RAN performance drop, TN-NORTH-0047 backhaul baseband unit on shared PDU-NRH-04-B"
- Entity refs extracted: `SITE-NRH-04` (SITE), `TN-NORTH-0047` (TRANSPORT), `ENB-2241` (RAN)
- `entity_domains` = ["SITE", "TRANSPORT", "RAN"]

**Snap engine behavior**: F12 scores affinity with F1 (shared entity `SITE-NRH-04`) and F7 (shared entities `TN-NORTH-0047`, `ENB-2241`). Two edges are added:
- `(F12, F3)` affinity = 0.62
- `(F12, F7)` affinity = 0.71

**Accumulation graph state after F12**:
- Union-find now merges Cluster A, Cluster B, and F12 into a single component of 12 nodes
- F12 is the only node with edges to both former clusters

**Bridge detection run**:
- Tarjan's DFS identifies F12 as articulation point (removing F12 disconnects A-side from B-side)
- Sub-components after removal: {F1..F6} size=6 >= 3, {F7..F11} size=5 >= 3 — both qualify
- BC[F12] = computed Brandes = 0.455 (F12 lies on 27 of 55 shortest paths between node pairs)
- Entity domains of F12: ["SITE", "TRANSPORT", "RAN"] — span >= 2 passes
- BC 0.455 >= BRIDGE_BC_THRESHOLD (0.30): passes
- Severity: BC=0.455 >= 0.45 → HIGH

**Record written**:

```json
{
  "bridge_discovery": {
    "bridge_fragment_id": "<F12-uuid>",
    "classification": "BRIDGE_DISCOVERY",
    "severity": "HIGH",
    "betweenness_centrality": 0.455,
    "sub_component_count": 2,
    "entity_domains": ["SITE", "TRANSPORT", "RAN"],
    "component_fingerprint": "a3f7c2b1e9d0...",
    "detected_at": "2026-03-16T14:22:09Z"
  },
  "provenance": [
    {
      "sub_component_index": 0,
      "sub_component_size": 6,
      "cluster_label": "power-grid-cluster-NRH04",
      "dominant_domain": "TRANSPORT",
      "domain_distribution": {"TRANSPORT": 3, "SITE": 2, "IP": 1},
      "member_fragment_ids": ["<F1>", "<F2>", "<F3>", "<F4>", "<F5>", "<F6>"]
    },
    {
      "sub_component_index": 1,
      "sub_component_size": 5,
      "cluster_label": "ran-cluster-ENB2241",
      "dominant_domain": "RAN",
      "domain_distribution": {"RAN": 4, "TRANSPORT": 1},
      "member_fragment_ids": ["<F7>", "<F8>", "<F9>", "<F10>", "<F11>"]
    }
  ]
}
```

**Discovery interpretation**: The power-grid failure cluster at SITE-NRH-04 and the RAN degradation cluster at ENB-2241/GNB-2241 are structurally disconnected in the accumulation graph — no fragment in the power cluster shares entities with any fragment in the RAN cluster directly. F12 is the sole bridge. This signals a root-cause hypothesis: RAN degradation may be caused by power brownout, a cross-domain relationship invisible to pairwise scoring.

---

## 7. Integration with Accumulation Graph (T2.1 Compatibility)

### 7.1 No Full Graph Load

Bridge detection operates exclusively on the edge set already loaded by T2.1's bounded queries:

- **Triggered path**: The edge set from `_load_edges_for_trigger()` (at most 1,000 edges) is passed directly to `BridgeDetector.analyze_component()`. No additional DB load.
- **Background path**: The edge pages from `_load_edges_paginated()` (5,000 edges per page) are accumulated per-component before `BridgeDetector.analyze_component()` is called.

Bridge detection never issues its own edge-loading queries. It consumes what T2.1 already loaded.

### 7.2 Call Site in `detect_and_evaluate_clusters()`

After the existing union-find and cluster evaluation logic, add:

```python
# Bridge detection — called only when cluster has >= MIN_CLUSTER_SIZE members
if len(component_nodes) >= MIN_CLUSTER_SIZE:
    bridge_detector = BridgeDetector(provenance=self.provenance)
    await bridge_detector.analyze_component(
        session=session,
        tenant_id=tenant_id,
        component_nodes=component_nodes,
        component_edges=component_edges,   # already-loaded bounded edge list
        trigger_fragment_id=trigger_fragment_id,
    )
```

The `BridgeDetector` is a stateless service instantiated per call; no object graph accumulation.

### 7.3 Triggered vs Background Deduplication

In triggered mode, `analyze_component()` is called after every `add_or_update_edge()`. The `component_fingerprint` uniqueness constraint prevents duplicate records for stable topology. Only new topology (different component membership) generates new records.

---

## 8. Computational Complexity Summary

| Operation | Complexity | Bound |
|---|---|---|
| Component isolation (BFS) | O(V + E) | O(50 + 1000) = O(1050) |
| Tarjan articulation points | O(V + E) | O(1050) |
| Brandes betweenness (full, V ≤ 50) | O(V(V + E)) | O(50 * 1050) = O(52,500) |
| Sub-component size check (per AP candidate) | O(V + E) | O(50 * 1050) = O(52,500) worst case |
| Domain span DB lookup (per qualifying AP) | O(entities per fragment) | 1 indexed SELECT |
| Bridge discovery INSERT | O(1) + O(sub-components) | 1 + 2 rows typical |
| **Total per triggered call** | **O(V(V + E))** | **~O(100,000) operations** |
| **Total per background page (5000 edges)** | **O(C * V(V + E))** where C = components in page | Bounded by MAX_CLUSTER_SIZE |

The algorithm is feasible inline with cluster evaluation. At 100,000 simple Python operations (no DB I/O beyond one entity-domain lookup), runtime is sub-millisecond on modern hardware.

**Memory bound**: O(V + E) = O(50 + 1000) per component. No heap accumulation across calls.

---

## 9. New File: `bridge_detector.py`

**Path**: `/Users/himanshu/Projects/Pedkai/backend/app/services/abeyance/bridge_detector.py`

**Class**: `BridgeDetector`

**Public interface**:

```python
class BridgeDetector:
    def __init__(self, provenance: ProvenanceLogger) -> None: ...

    async def analyze_component(
        self,
        session: AsyncSession,
        tenant_id: str,
        component_nodes: set[UUID],
        component_edges: list[tuple[UUID, UUID, float]],
        trigger_fragment_id: Optional[UUID] = None,
    ) -> list[BridgeDiscoveryORM]:
        """
        Run bridge detection on a pre-loaded component edge set.
        Returns list of BridgeDiscoveryORM records written (may be empty).
        Does NOT load edges from DB — consumes component_edges directly.
        """

    def _build_adjacency(
        self,
        nodes: set[UUID],
        edges: list[tuple[UUID, UUID, float]],
    ) -> dict[UUID, set[UUID]]: ...

    def _tarjan_articulation_points(
        self,
        nodes: set[UUID],
        adj: dict[UUID, set[UUID]],
    ) -> set[UUID]: ...

    def _brandes_betweenness(
        self,
        nodes: set[UUID],
        adj: dict[UUID, set[UUID]],
    ) -> dict[UUID, float]: ...

    def _sub_components_without(
        self,
        nodes: set[UUID],
        adj: dict[UUID, set[UUID]],
        exclude: UUID,
    ) -> list[frozenset[UUID]]: ...

    def _component_fingerprint(self, nodes: set[UUID]) -> str: ...

    async def _fetch_entity_domains(
        self,
        session: AsyncSession,
        tenant_id: str,
        fragment_id: UUID,
    ) -> set[str]: ...

    def _classify(
        self,
        bc: float,
        domains: set[str],
        sub_components: list[frozenset[UUID]],
    ) -> tuple[str, Optional[str]]: ...
```

**ORM Models** (add to `abeyance_orm.py`):

```python
class BridgeDiscoveryORM(Base):
    __tablename__ = "bridge_discovery"
    id                     : UUID
    tenant_id              : str
    bridge_fragment_id     : UUID  (FK abeyance_fragment.id CASCADE DELETE)
    classification         : str
    severity               : Optional[str]
    betweenness_centrality : float
    sub_component_count    : int
    entity_domains         : dict  (JSONB)
    component_fingerprint  : str
    detected_at            : datetime
    suppressed             : bool
    suppressed_reason      : Optional[str]

class BridgeDiscoveryProvenanceORM(Base):
    __tablename__ = "bridge_discovery_provenance"
    id                  : UUID
    bridge_discovery_id : UUID  (FK bridge_discovery.id CASCADE DELETE)
    tenant_id           : str
    sub_component_index : int
    sub_component_size  : int
    cluster_label       : str
    member_fragment_ids : list  (JSONB)
    dominant_domain     : Optional[str]
    domain_distribution : dict  (JSONB)
```

---

## 10. Invariants

| Invariant | Rule | Enforcement |
|---|---|---|
| BD-INV-1 | Bridge detection never loads edges from DB independently | `analyze_component()` accepts `component_edges` parameter only |
| BD-INV-2 | All DB operations are tenant-scoped | Every query includes `tenant_id = :tenant_id` |
| BD-INV-3 | Discovery record is idempotent for stable topology | `UNIQUE (tenant_id, bridge_fragment_id, component_fingerprint)` on `bridge_discovery` |
| BD-INV-4 | `betweenness_centrality` is normalized in [0.0, 1.0] | Division by `(V-1)(V-2)/2` in Brandes; clamped to 0.0 if V < 3 |
| BD-INV-5 | `sub_component_count` counts only sub-components >= MIN_CLUSTER_SIZE | Filtering applied before classification |
| BD-INV-6 | `member_fragment_ids` in provenance rows capped at BRIDGE_PROV_MAX_MEMBERS | Prevents JSONB bloat for large sub-components |
| BD-INV-7 | No bridge discovery record for components with < MIN_CLUSTER_SIZE members | Guard at call site: `if len(component_nodes) >= MIN_CLUSTER_SIZE` |

---

## 11. Files Changed

| File | Change | Status |
|---|---|---|
| `backend/app/services/abeyance/bridge_detector.py` | New file — `BridgeDetector` class | New |
| `backend/app/models/abeyance_orm.py` | Add `BridgeDiscoveryORM`, `BridgeDiscoveryProvenanceORM` | Modify |
| `backend/app/services/abeyance/accumulation_graph.py` | Add `BridgeDetector.analyze_component()` call after cluster evaluation | Modify |
| `alembic/versions/<new>.py` | Migration: create `bridge_discovery`, `bridge_discovery_provenance` tables and indexes | New |

No changes to: `snap_engine.py`, `enrichment_chain.py`, `shadow_topology.py`, `cold_storage.py`, `maintenance.py`.

---

## 12. Out of Scope

- **T2.1**: Accumulation graph remediation (unbounded edge load, N+1 pruning) — already specified in `phase_2/accumulation_graph_fix.md`. Bridge detection consumes T2.1's output.
- **LLM interpretation of bridge fragments**: That is a higher-tier discovery mechanism (Tier 2+). This spec is Tier 1 only.
- **Bridge fragment promotion / lifecycle**: What happens after a `BRIDGE_DISCOVERY` is created (e.g., escalation, notification, human review) is outside the scope of this algorithm spec.
- **Modifying the accumulation graph**: This spec reads the accumulation graph; it does not write to `accumulation_edge` or modify graph structure.
