# Abeyance Memory v3.0 — Core Subsystems Codebase Structure

**Task**: Extract Codebase Structure for Core Subsystems
**Date**: 2026-03-16
**Input Directory**: `/Users/himanshu/Projects/Pedkai/backend/app/`

---

## 1. ENRICHMENT_CHAIN

### File Path
`/Users/himanshu/Projects/Pedkai/backend/app/services/abeyance/enrichment_chain.py`

### Class: EnrichmentChain

#### Public Methods with Signatures
```python
async def __init__(
    self,
    provenance: ProvenanceLogger,
    llm_service: Optional[Any] = None,
    shadow_topology: Optional[Any] = None,
)

async def enrich(
    self,
    session: AsyncSession,
    tenant_id: str,
    raw_content: str,
    source_type: str,
    event_timestamp: Optional[datetime] = None,
    source_ref: Optional[str] = None,
    source_engineer_id: Optional[str] = None,
    explicit_entity_refs: Optional[list[str]] = None,
    metadata: Optional[dict] = None,
) -> AbeyanceFragmentORM

async def _resolve_entities(
    self,
    content: str,
    source_type: str,
    explicit_refs: Optional[list[str]] = None,
) -> list[dict]

async def _llm_extract_entities(self, content: str) -> list[dict]

def _regex_extract_entities(self, content: str) -> list[dict]

async def _build_operational_fingerprint(
    self,
    entities: list[dict],
    event_time: datetime,
    tenant_id: str,
    session: AsyncSession,
) -> dict

def _time_bucket(self, dt: datetime) -> str

def _classify_failure_modes(
    self,
    entities: list[dict],
    fingerprint: dict,
    content: str,
) -> list[dict]

def _build_temporal_context(self, event_time: datetime, fingerprint: dict) -> dict

async def _compute_embeddings(
    self,
    raw_content: str,
    entities: list[dict],
    neighbourhood: dict,
    fingerprint: dict,
    failure_modes: list[dict],
    temporal_context: dict,
) -> tuple[list[bool], list[float], list[float]]

def _build_temporal_vector(self, ctx: dict) -> np.ndarray

def _build_topo_text(self, entities: list[dict], neighbourhood: dict) -> str

def _build_operational_text(self, failure_modes: list[dict], fingerprint: dict) -> str

def _compute_dedup_key(
    self, tenant_id: str, source_type: str,
    source_ref: Optional[str], event_timestamp: datetime,
) -> Optional[str]
```

#### Constants/Thresholds
```python
# Embedding dimensions
SEMANTIC_DIM = 512
TOPOLOGICAL_DIM = 384
TEMPORAL_DIM = 256
OPERATIONAL_DIM = 384
ENRICHED_DIM = 1536  # sum of above
RAW_DIM = 768

# Source-type defaults (LLD §5)
SOURCE_TYPE_DEFAULTS = {
    "TICKET_TEXT": {"base_relevance": 0.9, "decay_tau": 270.0},
    "ALARM": {"base_relevance": 0.7, "decay_tau": 90.0},
    "TELEMETRY_EVENT": {"base_relevance": 0.6, "decay_tau": 60.0},
    "CLI_OUTPUT": {"base_relevance": 0.7, "decay_tau": 180.0},
    "CHANGE_RECORD": {"base_relevance": 0.8, "decay_tau": 365.0},
    "CMDB_DELTA": {"base_relevance": 0.7, "decay_tau": 90.0},
}

# Entity extraction patterns (regex-based)
ENTITY_PATTERNS = [
    (r"(?:LTE|NR|GSM|UMTS)-\w+-[A-Z0-9]+", "RAN"),
    (r"SITE-[A-Z]+-\d+", "SITE"),
    (r"ENB-\d+", "RAN"),
    (r"GNB-\d+", "RAN"),
    (r"TN-[A-Z]+-\d+", "TRANSPORT"),
    (r"S1-\d+-\d+", "TRANSPORT"),
    (r"VLAN-\d+", "IP"),
    (r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(?:/\d{1,2})?", "IP"),
    (r"CR-[A-Z]+-\d+", "CORE"),
    (r"VNF-[A-Z0-9-]+", "VNF"),
    (r"CHG-\d{4}-[A-Z]+-\d+", None),
]

# Temporal context features
_time_bucket ranges: "shoulder" (6-9, 17-21), "peak" (9-17), "off_peak" (rest)
```

#### DB Tables Touched
- `abeyance_fragment` (AbeyanceFragmentORM)
- `fragment_entity_ref` (FragmentEntityRefORM)
- `abeyance_state_change_log` (via ProvenanceLogger)

#### Dependencies on Other Abeyance Files
```python
from backend.app.models.abeyance_orm import (
    AbeyanceFragmentORM,
    FragmentEntityRefORM,
    MAX_RAW_CONTENT_BYTES,
)
from backend.app.services.abeyance.events import (
    FragmentStateChange,
    ProvenanceLogger,
)
```

#### Injection Points
- `shadow_topology`: Optional ShadowTopologyService for neighbourhood expansion (line 87)
- `llm_service`: Optional LLM service for entity extraction and embedding generation (line 86)
- `provenance`: ProvenanceLogger for state change tracking (line 85)

#### Remediation Targets Addressed
- Audit §2.3: Hash embeddings → LLM embeddings with mask tracking
- Audit §3.2: Stubbed operational fingerprinting → real computation with graceful None
- Audit §3.3: LLM entity extraction no-op → actual LLM call with regex fallback
- Audit §6.3: Embedding dimension mismatch → explicit validation

#### TODO/FIXME Comments
None

---

## 2. SNAP_ENGINE

### File Path
`/Users/himanshu/Projects/Pedkai/backend/app/services/abeyance/snap_engine.py`

### Class: SnapEngine

#### Public Methods with Signatures
```python
def __init__(
    self,
    provenance: ProvenanceLogger,
    notifier: Optional[RedisNotifier] = None,
)

async def evaluate(
    self,
    session: AsyncSession,
    new_fragment: AbeyanceFragmentORM,
    tenant_id: str,
) -> dict

async def _targeted_retrieval(
    self,
    session: AsyncSession,
    tenant_id: str,
    entity_ids: set[str],
    min_decay_score: float = 0.1,
) -> list[AbeyanceFragmentORM]

def _compute_temporal_modifier(
    self,
    new_time: Optional[datetime],
    stored_time: Optional[datetime],
    new_fp: dict,
    stored_fp: dict,
    source_type: str,
) -> float

def _operational_similarity(self, fp_a: dict, fp_b: dict) -> float

def _extract_failure_modes(self, frag: AbeyanceFragmentORM) -> set[str]

def _score_pair(
    self,
    new_frag: AbeyanceFragmentORM,
    stored_frag: AbeyanceFragmentORM,
    new_entities: set[str],
    stored_entities: set[str],
) -> list[tuple[str, float, dict]]

async def _apply_snap(
    self, session: AsyncSession,
    new_frag: AbeyanceFragmentORM, stored_frag: AbeyanceFragmentORM,
    score: float, failure_mode: str, tenant_id: str,
) -> None
```

#### Helper Functions
```python
def _clamp(value: float, lo: float, hi: float) -> float

def _cosine_similarity(a: list[float] | np.ndarray, b: list[float] | np.ndarray) -> float

def _jaccard_similarity(set_a: set, set_b: set) -> float

def _sidak_threshold(base_threshold: float, k: int) -> float
```

#### Constants/Thresholds
```python
# Weight profiles by failure mode (LLD §9)
WEIGHT_PROFILES = {
    "DARK_EDGE":         {"w_sem": 0.20, "w_topo": 0.35, "w_entity": 0.25, "w_oper": 0.20},
    "DARK_NODE":         {"w_sem": 0.30, "w_topo": 0.15, "w_entity": 0.35, "w_oper": 0.20},
    "IDENTITY_MUTATION": {"w_sem": 0.15, "w_topo": 0.20, "w_entity": 0.45, "w_oper": 0.20},
    "PHANTOM_CI":        {"w_sem": 0.25, "w_topo": 0.20, "w_entity": 0.30, "w_oper": 0.25},
    "DARK_ATTRIBUTE":    {"w_sem": 0.30, "w_topo": 0.15, "w_entity": 0.25, "w_oper": 0.30},
}

# Decision thresholds
BASE_SNAP_THRESHOLD = 0.75
NEAR_MISS_THRESHOLD = 0.55
AFFINITY_THRESHOLD = 0.40

# Retrieval limits
MAX_CANDIDATES = 200

# Temporal weight parameters
CHANGE_PROXIMITY_GAMMA = 0.3

# Source-type decay tau for temporal modifier
_TEMPORAL_TAU = {
    "TICKET_TEXT": 270, "ALARM": 90, "TELEMETRY_EVENT": 60,
    "CLI_OUTPUT": 180, "CHANGE_RECORD": 365, "CMDB_DELTA": 90,
}
```

#### DB Tables Touched
- `abeyance_fragment` (AbeyanceFragmentORM)
- `fragment_entity_ref` (FragmentEntityRefORM)
- `snap_decision_log` (via ProvenanceLogger)
- `abeyance_state_change_log` (via ProvenanceLogger)

#### Dependencies on Other Abeyance Files
```python
from backend.app.models.abeyance_orm import (
    AbeyanceFragmentORM,
    FragmentEntityRefORM,
    VALID_TRANSITIONS,
)
from backend.app.services.abeyance.events import (
    ProvenanceLogger,
    RedisNotifier,
    SnapDecision,
    FragmentStateChange,
)
```

#### Remediation Targets Addressed
- Audit §4.2: Temporal weight can override evidence → capped [0.5, 1.0]
- Audit §4.3: Multiple comparisons → Sidak correction applied (INV-13)
- Audit §4.4: Diurnal alignment → corrected range documentation
- Audit §7.1: Snap score not persisted → full scoring breakdown saved
- Audit §2.2: Unbounded near-miss boost → delegated to DecayEngine

#### TODO/FIXME Comments
None

---

## 3. ACCUMULATION_GRAPH

### File Path
`/Users/himanshu/Projects/Pedkai/backend/app/services/abeyance/accumulation_graph.py`

### Class: AccumulationGraph

#### Public Methods with Signatures
```python
def __init__(
    self,
    provenance: ProvenanceLogger,
    notifier: Optional[RedisNotifier] = None,
)

async def add_or_update_edge(
    self,
    session: AsyncSession,
    tenant_id: str,
    fragment_a_id: UUID,
    fragment_b_id: UUID,
    affinity_score: float,
    failure_mode: str,
) -> Optional[UUID]

async def _enforce_edge_limit(
    self, session: AsyncSession, tenant_id: str, fragment_id: UUID,
) -> None

async def detect_and_evaluate_clusters(
    self,
    session: AsyncSession,
    tenant_id: str,
    trigger_fragment_id: Optional[UUID] = None,
) -> list[dict]

async def _prune_cluster(
    self,
    session: AsyncSession,
    tenant_id: str,
    members: set[UUID],
    all_edges: list[AccumulationEdgeORM],
) -> set[UUID]

async def remove_fragment_edges(
    self,
    session: AsyncSession,
    tenant_id: str,
    fragment_id: UUID,
) -> int
```

#### Helper Functions
```python
def _log_mean_exp(scores: list[float], temperature: float = LME_TEMPERATURE) -> float

def _correlation_discount(num_nodes: int, num_edges: int) -> float
```

#### Constants/Thresholds
```python
# Bounds (INV-9)
MAX_EDGES_PER_FRAGMENT = 20
MAX_CLUSTER_SIZE = 50
MIN_CLUSTER_SIZE = 3

# LME parameters (Phase 4, §4.3)
LME_TEMPERATURE = 0.3
CLUSTER_SNAP_THRESHOLD = 0.70
```

#### DB Tables Touched
- `accumulation_edge` (AccumulationEdgeORM)
- `abeyance_fragment` (AbeyanceFragmentORM) — read-only
- `cluster_snapshot` (ClusterSnapshot via ProvenanceLogger)

#### Dependencies on Other Abeyance Files
```python
from backend.app.models.abeyance_orm import (
    AccumulationEdgeORM,
    AbeyanceFragmentORM,
)
from backend.app.services.abeyance.events import (
    ClusterEvaluation,
    ProvenanceLogger,
    RedisNotifier,
)
```

#### Remediation Targets Addressed
- Audit §4.1: Noisy-OR overconfident → replaced with LME + correlation discount
- Audit §5.3: Recursive CTE no cycle guard → Python-side union-find
- Audit §7.3: Cluster formation unobservable → ClusterSnapshot persisted
- Audit §9.2: No tenant check on edge queries → tenant_id on all queries

#### TODO/FIXME Comments
None

---

## 4. SHADOW_TOPOLOGY

### Service File Path
`/Users/himanshu/Projects/Pedkai/backend/app/services/abeyance/shadow_topology.py`

### API Router File Path
`/Users/himanshu/Projects/Pedkai/backend/app/api/shadow_topology.py`

### Class: ShadowTopologyService

#### Public Methods with Signatures
```python
async def get_or_create_entity(
    self,
    session: AsyncSession,
    tenant_id: str,
    entity_identifier: str,
    entity_domain: Optional[str] = None,
    origin: str = "CMDB_DECLARED",
    attributes: Optional[dict] = None,
) -> ShadowEntityORM

async def get_or_create_relationship(
    self,
    session: AsyncSession,
    tenant_id: str,
    from_entity_id: UUID,
    to_entity_id: UUID,
    relationship_type: str,
    origin: str = "CMDB_DECLARED",
    confidence: float = 1.0,
    evidence_summary: Optional[dict] = None,
) -> ShadowRelationshipORM

async def get_neighbourhood(
    self,
    session: AsyncSession,
    tenant_id: str,
    entity_ids: list[UUID],
    max_hops: int = 2,
) -> dict

async def topological_proximity(
    self,
    session: AsyncSession,
    tenant_id: str,
    entity_set_a: set[UUID],
    entity_set_b: set[UUID],
    max_hops: int = 3,
) -> float

async def enrich_on_validated_snap(
    self,
    session: AsyncSession,
    tenant_id: str,
    hypothesis_id: UUID,
    entity_ids: list[UUID],
    relationship_pairs: list[tuple[UUID, UUID, str]],
) -> None

async def export_to_cmdb(
    self,
    session: AsyncSession,
    tenant_id: str,
    relationship_id: UUID,
) -> dict
```

#### Constants/Thresholds
```python
# Expansion limits (Phase 5)
MAX_BFS_RESULT = 500
MAX_HOPS = 3
MAX_RELATIONSHIPS_PER_ENTITY = 200
```

#### DB Tables Touched
- `shadow_entity` (ShadowEntityORM)
- `shadow_relationship` (ShadowRelationshipORM)
- `cmdb_export_log` (CmdbExportLogORM)

#### Dependencies on Other Abeyance Files
```python
from backend.app.models.abeyance_orm import (
    ShadowEntityORM,
    ShadowRelationshipORM,
    CmdbExportLogORM,
)
```

#### API Endpoints (shadow_topology.py router)
```
GET /entities — List shadow entities with filters
GET /neighbourhood/{entity_identifier} — Get N-hop neighbourhood expansion
POST /export/{relationship_id} — Controlled export to CMDB
```

#### Remediation Targets Addressed
- Audit §3.4: Recursive CTE explosion → cycle-guarded BFS with visited set
- Audit §9.3: Shadow Topology BFS returns all tenant data → tenant filter on entity fetch

#### TODO/FIXME Comments
None

---

## 5. COLD_STORAGE

### File Path
`/Users/himanshu/Projects/Pedkai/backend/app/services/abeyance/cold_storage.py`

### Class: AbeyanceColdStorage

#### Public Methods with Signatures
```python
def __init__(self)

async def archive_to_db(
    self,
    session: AsyncSession,
    fragment,  # AbeyanceFragmentORM
    tenant_id: str,
) -> ColdFragmentORM

async def archive_batch_to_db(
    self,
    session: AsyncSession,
    fragments: list,
    tenant_id: str,
) -> int

async def search_db(
    self,
    session: AsyncSession,
    tenant_id: str,
    query_embedding: list[float],
    top_k: int = COLD_SEARCH_DEFAULT_K,
) -> list[ColdFragmentORM]

def cold_storage_path(self, tenant_id: str, year: int, month: int) -> Path

def archive_fragment(self, fragment: AbeyanceFragment) -> str

def search_cold(
    self,
    query_embedding: np.ndarray,
    top_k: int = 5,
    tenant_id: str | None = None,
) -> list[AbeyanceFragment]

def _load_tenant_fragments(
    self, tenant_id: str | None = None
) -> list[AbeyanceFragment]

def _cosine_similarity(
    self, query: np.ndarray, matrix: np.ndarray
) -> np.ndarray
```

#### Constants/Thresholds
```python
MAX_COLD_BATCH = 5_000
COLD_SEARCH_DEFAULT_K = 20

# Embedding dimension for pgvector Vector type
Vector(1536)  # matches ENRICHED_DIM from enrichment_chain
```

#### DB Tables Touched
- `cold_fragment` (ColdFragmentORM)

#### ORM Models Defined
```python
class ColdFragmentORM(Base):
    __tablename__ = "cold_fragment"
    # Columns:
    id, tenant_id, original_fragment_id, source_type,
    raw_content_summary, extracted_entities, failure_mode_tags,
    enriched_embedding (Vector or Text), event_timestamp,
    archived_at, original_created_at, original_decay_score,
    snap_status_at_archive
    # Indices:
    ix_cold_frag_tenant, ix_cold_frag_original
```

#### Portable Dataclass
```python
@dataclass
class AbeyanceFragment:
    fragment_id: str
    tenant_id: str
    embedding: list
    created_at: str
    decay_score: float = 1.0
    status: str = "ACTIVE"
    corroboration_count: int = 0
    metadata: dict = field(default_factory=dict)
```

#### Architecture
- **Primary path**: PostgreSQL + pgvector with IVFFlat index (ANN search via `<=>` operator, O(sqrt(N)))
- **Fallback path**: Local Parquet files (degraded mode when DB unavailable)
- **Backend selection**: Configurable via `COLD_STORAGE_BACKEND` env var
- **Base path**: Configurable via `COLD_STORAGE_BASE_PATH` env var

#### Remediation Targets Addressed
- Phase 5 §5.2: Cold storage with pgvector ANN indexing and Parquet fallback

#### TODO/FIXME Comments
None

---

## Dependency Graph

```
enrichment_chain
    ├─→ shadow_topology         (topology expansion via get_neighbourhood)
    ├─→ ProvenanceLogger        (state change tracking)
    └─→ AbeyanceFragmentORM     (persistence)
          └─→ FragmentEntityRefORM

snap_engine
    ├─→ enrichment_chain (implicit: evaluates fragments)
    ├─→ accumulation_graph (implicit: affinity edges → clustering)
    ├─→ ProvenanceLogger  (snap decisions, state changes)
    ├─→ RedisNotifier     (notifications)
    └─→ AbeyanceFragmentORM, FragmentEntityRefORM

accumulation_graph
    ├─→ snap_engine (implicit: edges from affinity scoring)
    ├─→ ProvenanceLogger (cluster evaluations)
    ├─→ RedisNotifier    (cluster snap notifications)
    └─→ AccumulationEdgeORM

shadow_topology
    ├─→ enrichment_chain (neighbourhood expansion during enrichment)
    ├─→ snap_engine (implicit: topological proximity scoring)
    └─→ ShadowEntityORM, ShadowRelationshipORM, CmdbExportLogORM

cold_storage
    ├─→ enrichment_chain (implicit: archive expired fragments)
    ├─→ accumulation_graph (implicit: cleanup on archive)
    └─→ ColdFragmentORM (pgvector-backed)
```

---

## Cross-Subsystem Call Paths

### Fragment Ingestion → Snap Evaluation → Cluster Formation
1. **enrichment_chain.enrich()** → creates AbeyanceFragmentORM + FragmentEntityRefORM
2. **snap_engine.evaluate()** → retrieves candidates via FragmentEntityRefORM
3. **snap_engine._score_pair()** → compares embeddings + operational fingerprints
4. **snap_engine._apply_snap()** → marks fragments SNAPPED with hypothesis_id
5. **accumulation_graph.add_or_update_edge()** → creates AccumulationEdgeORM with affinity score
6. **accumulation_graph.detect_and_evaluate_clusters()** → union-find + LME scoring

### Topology Enrichment
1. **enrichment_chain.enrich()** calls **shadow_topology.get_neighbourhood()**
2. **shadow_topology.get_neighbourhood()** returns entities + relationships at depth 0..max_hops
3. Results stored in **topological_neighbourhood** field of AbeyanceFragmentORM

### Validation & CMDB Export (LLD §8)
1. **snap_engine._apply_snap()** creates hypothesis_id
2. **shadow_topology.enrich_on_validated_snap()** adds discovered relationships
3. **shadow_topology.export_to_cmdb()** sanitizes and logs export to CmdbExportLogORM

### Archival & Cold Storage (Phase 7)
1. DecayEngine (external) expires fragments based on AFFINITY_THRESHOLD
2. **cold_storage.archive_to_db()** persists to ColdFragmentORM with pgvector index
3. **cold_storage.archive_batch_to_db()** batches up to MAX_COLD_BATCH
4. **accumulation_graph.remove_fragment_edges()** cleans up edges

---

## Invariants Enforced Across Core Subsystems

| Invariant | Enforcement | Subsystems |
|-----------|-------------|-----------|
| INV-3 | All scoring in [0.0, 1.0] | snap_engine (clamping), accumulation_graph (LME bounded) |
| INV-4 | Cluster membership monotonic convergent | accumulation_graph (edges only increase affinity) |
| INV-6 | Raw content bounded to MAX_RAW_CONTENT_BYTES | enrichment_chain (truncation on ingest), cold_storage (summary only) |
| INV-7 | Tenant ID verified on every operation | snap_engine, shadow_topology, cold_storage, accumulation_graph (all queries scoped) |
| INV-8 | Output in declared range | snap_engine, accumulation_graph, cold_storage |
| INV-9 | MAX_EDGES_PER_FRAGMENT, MAX_CLUSTER_SIZE bounds | accumulation_graph (edge eviction, cluster pruning) |
| INV-10 | All scoring decisions persisted | snap_engine (SnapDecision log), accumulation_graph (ClusterSnapshot) |
| INV-11 | No hash-derived embeddings; mask vector tracks valid sub-vectors | enrichment_chain (LLM-only, mask tracking) |
| INV-13 | Multiple comparisons correction applied | snap_engine (Sidak correction on snap_threshold) |

---

## File Locations Summary

| Subsystem | Type | Path |
|-----------|------|------|
| enrichment_chain | service | `/Users/himanshu/Projects/Pedkai/backend/app/services/abeyance/enrichment_chain.py` |
| snap_engine | service | `/Users/himanshu/Projects/Pedkai/backend/app/services/abeyance/snap_engine.py` |
| accumulation_graph | service | `/Users/himanshu/Projects/Pedkai/backend/app/services/abeyance/accumulation_graph.py` |
| shadow_topology | service | `/Users/himanshu/Projects/Pedkai/backend/app/services/abeyance/shadow_topology.py` |
| shadow_topology | API router | `/Users/himanshu/Projects/Pedkai/backend/app/api/shadow_topology.py` |
| cold_storage | service | `/Users/himanshu/Projects/Pedkai/backend/app/services/abeyance/cold_storage.py` |

---

## Key Remediation Status

All five core subsystems have been remediated per v2.0 forensic audit:

- ✓ Embedding computation no longer uses hash stubs (INV-11, Audit §2.3)
- ✓ Operational fingerprinting returns None for unavailable fields (Audit §3.2)
- ✓ Entity extraction uses LLM with regex fallback (Audit §3.3)
- ✓ BFS/CTE cycles guarded with visited sets (Audit §3.4, §5.3)
- ✓ Embedding dimension validation explicit (Audit §6.3)
- ✓ Snap scores bounded [0.5, 1.0] on temporal modifier (Audit §4.2)
- ✓ Sidak correction applied to snap thresholds (Audit §4.3, INV-13)
- ✓ Snap scoring decisions fully persisted (Audit §7.1)
- ✓ Cluster evaluations persisted to ClusterSnapshot (Audit §7.3)
- ✓ Noisy-OR replaced with LME + correlation discount (Audit §4.1)
- ✓ All tenant_id verifications on every DB operation (Audit §9.2, §9.3)
