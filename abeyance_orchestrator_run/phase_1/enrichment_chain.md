# Enrichment Chain v3.0 -- Per-Fragment Enrichment Flow

**Task**: T1.3 Enrichment Chain Redesign
**Status**: SPECIFICATION COMPLETE
**Date**: 2026-03-16
**Supersedes**: `backend/app/services/abeyance/enrichment_chain.py` (v2.0)

---

## 1. Problem Statement

The v2.0 enrichment chain has three critical/severe defects that block production deployment:

| Finding | Severity | Problem |
|---------|----------|---------|
| F-3.2 | CRITICAL | `get_neighbourhood()` called with `entity_ids=[]` -- topology expansion is dead code; `entity_identifiers` constructed but never passed |
| F-3.3 | SEVERE | Hash embedding fallback activates every call because `loop.is_running() == True` in async FastAPI; violates INV-11 |
| F-5.1 | CRITICAL | 4 cloud LLM calls per fragment at $0.004/call = $57.6K/day at 10K events/min |

Additional findings addressed by this redesign:

| Finding | Severity | Problem |
|---------|----------|---------|
| F-4.2 | SEVERE | Entity extraction is single point of failure; missing extraction causes silent decay to zero |
| F-5.5 | MODERATE | No rate limiting on LLM calls; burst triggers cascading fallback to hash embeddings |
| F-6.1 | SEVERE | LLM outage zeroes 75% of embedding; only temporal signal survives |
| F-6.2 | CRITICAL | Embedding mask stored but never consumed by snap engine |

---

## 2. Architecture Overview

### 2.1 Model Stack

| Component | Model | Dimensionality | Runtime | Purpose |
|-----------|-------|---------------|---------|---------|
| Entity extraction + hypothesis | TSLAM-8B | N/A (structured output) | GPU, local | Extract entity identifiers, domains, and candidate failure-mode hypotheses from fragment text |
| Semantic embedding | T-VEC 1.5B | 1536 | CPU, local | Telecom-domain semantic embedding of content + entity context |
| Topological embedding | T-VEC 1.5B | 1536 | CPU, local | Telecom-domain embedding of Shadow Topology neighbourhood description |
| Operational embedding | T-VEC 1.5B | 1536 | CPU, local | Telecom-domain embedding of failure mode + operational fingerprint text |
| Temporal encoding | Sinusoidal math | 256 | CPU, no model | Deterministic time-of-day / day-of-week / seasonal encoding |

**Cost**: All inference is local. Zero cloud LLM calls. F-5.1 fully resolved.

### 2.2 Storage Columns (per fragment)

| Column | Type | Dimension | Source |
|--------|------|-----------|--------|
| `emb_semantic` | `vector(1536)` NULL | 1536 | T-VEC call 1 |
| `emb_topological` | `vector(1536)` NULL | 1536 | T-VEC call 2 |
| `emb_temporal` | `vector(256)` NOT NULL | 256 | Sinusoidal math |
| `emb_operational` | `vector(1536)` NULL | 1536 | T-VEC call 3 |
| `mask_semantic` | `boolean DEFAULT FALSE` | 1 | Set TRUE on T-VEC call 1 success |
| `mask_topological` | `boolean DEFAULT FALSE` | 1 | Set TRUE on T-VEC call 2 success |
| `mask_operational` | `boolean DEFAULT FALSE` | 1 | Set TRUE on T-VEC call 3 success |

**Temporal has no mask column.** It is always valid (pure math, no model dependency).

**Failure semantics**: If T-VEC fails for a dimension, the column is NULL and the mask is FALSE. No zero-fill. No hash fallback. The snap engine (T1.4) must weight only dimensions where `mask_X = TRUE` when computing similarity.

---

## 3. Step-by-Step Enrichment Flow

The enrichment pipeline processes a single fragment through five sequential stages. Steps (b) through (e) can be parallelized where noted.

### 3.0 Input Validation

```
Input:
  session:               AsyncSession
  tenant_id:             str
  raw_content:           str
  source_type:           str  (TICKET_TEXT | ALARM | TELEMETRY_EVENT | CLI_OUTPUT | CHANGE_RECORD | CMDB_DELTA)
  event_timestamp:       Optional[datetime]  (defaults to UTC now)
  source_ref:            Optional[str]
  source_engineer_id:    Optional[str]
  explicit_entity_refs:  Optional[list[str]]
  metadata:              Optional[dict]

Preconditions:
  - raw_content truncated to MAX_RAW_CONTENT_BYTES (INV-6)
  - tenant_id validated non-empty
  - source_type in SOURCE_TYPE_DEFAULTS keys
```

### Step (a): TSLAM-8B Entity Extraction + Hypothesis Generation

**Model**: TSLAM-8B (GPU, local)
**Purpose**: Replace both the cloud LLM entity extraction call AND the rule-based `_classify_failure_modes()` with a single local model call.

**Input text construction**:

```
<|system|>
Extract telecom network entities and classify potential failure modes from NOC operational text.
Return JSON with two fields:
- "entities": array of {"identifier": str, "domain": str}
  where domain is one of: RAN, TRANSPORT, CORE, IP, VNF, SITE
- "hypotheses": array of {"divergence_type": str, "confidence": float, "rationale": str, "candidate_entities": [str]}
  where divergence_type is one of: DARK_EDGE, DARK_NODE, IDENTITY_MUTATION, PHANTOM_CI, DARK_ATTRIBUTE
<|user|>
Source type: {source_type}
Content: {raw_content[:4000]}
<|end|>
```

**Output processing**:

```python
tslam_result = await tslam_client.generate(input_text, max_tokens=1024, temperature=0.0)
parsed = json.loads(tslam_result)

# Entity list
tslam_entities: list[dict] = parsed.get("entities", [])

# Failure mode hypotheses
failure_modes: list[dict] = parsed.get("hypotheses", [])
```

**Fallback on TSLAM failure**:

If TSLAM-8B is unavailable or returns unparseable output:

1. Entity extraction falls back to regex-only via `_regex_extract_entities()` (existing patterns preserved from v2.0).
2. Failure mode classification falls back to keyword-based `_classify_failure_modes()` (existing rule engine preserved from v2.0).
3. A warning is logged: `"TSLAM-8B unavailable; regex entity extraction + rule-based classification used"`.
4. Enrichment continues -- this is NOT a fatal error. F-4.2 is addressed: even without TSLAM, regex extraction produces entities, and the fragment proceeds to embedding.

**Entity merging** (same as v2.0 but with TSLAM replacing LLM):

```python
# Regex always runs as supplement (catches structured identifiers TSLAM may miss)
regex_entities = _regex_extract_entities(raw_content)

# Merge: TSLAM entities first, then regex without duplicates
seen = {e["identifier"] for e in tslam_entities}
for re_ent in regex_entities:
    if re_ent["identifier"] not in seen:
        tslam_entities.append(re_ent)
        seen.add(re_ent["identifier"])

# Add explicit refs
if explicit_entity_refs:
    for ref in explicit_entity_refs:
        if ref not in seen:
            tslam_entities.append({"identifier": ref, "domain": None, "distance": 0})
            seen.add(ref)

entities = tslam_entities
```

---

### Step (b): T-VEC Semantic Embedding -> `emb_semantic` (1536)

**Model**: T-VEC 1.5B (CPU, local)
**Column**: `emb_semantic vector(1536)`
**Mask**: `mask_semantic boolean`

**Input text construction**:

```python
def build_semantic_text(raw_content: str, entities: list[dict], source_type: str) -> str:
    entity_text = "; ".join(
        f"{e['identifier']} [{e.get('domain', 'UNKNOWN')}]"
        for e in entities[:30]
    )
    return (
        f"[{source_type}] {raw_content[:3000]}\n"
        f"Entities: {entity_text}"
    )
```

**Rationale**: The source_type prefix gives T-VEC domain context (alarm text reads differently from ticket text). Entity identifiers with domain tags anchor the semantic space to the specific network elements mentioned.

**Execution**:

```python
semantic_text = build_semantic_text(raw_content, entities, source_type)
try:
    emb_semantic = await tvec_client.embed(semantic_text)  # Returns list[float] len 1536
    assert len(emb_semantic) == 1536
    mask_semantic = True
except Exception:
    logger.warning("T-VEC semantic embedding failed", exc_info=True)
    emb_semantic = None    # Column stores NULL
    mask_semantic = False   # Mask stays FALSE
```

**No zero-fill. No hash fallback. No truncation-and-pad.**

---

### Step (c): T-VEC Topological Embedding -> `emb_topological` (1536)

**Model**: T-VEC 1.5B (CPU, local)
**Column**: `emb_topological vector(1536)`
**Mask**: `mask_topological boolean`

**Precondition**: Shadow Topology service is injected and available.

**F-3.2 FIX -- entity_ids actually passed to get_neighbourhood()**:

The v2.0 code constructs `entity_identifiers` but then calls `get_neighbourhood(entity_ids=[])`. This is the root cause of F-3.2. The fix:

```python
# v2.0 BUG (F-3.2):
#   entity_identifiers = [e["identifier"] for e in entities]
#   neighbourhood = await shadow_topology.get_neighbourhood(
#       session, tenant_id, entity_ids=[], max_hops=2)  # <-- ALWAYS EMPTY

# v3.0 FIX:
# Step 1: Resolve entity identifiers to Shadow Topology UUIDs
entity_uuids: list[UUID] = []
for e in entities:
    shadow_entity = await shadow_topology.get_or_create_entity(
        session, tenant_id,
        entity_identifier=e["identifier"],
        entity_domain=e.get("domain"),
        origin="ABEYANCE_OBSERVED",
    )
    entity_uuids.append(shadow_entity.id)

# Step 2: Call get_neighbourhood with ACTUAL entity UUIDs
neighbourhood: dict = {}
if entity_uuids:
    neighbourhood = await shadow_topology.get_neighbourhood(
        session, tenant_id,
        entity_ids=entity_uuids,   # <-- ACTUAL UUIDs, NOT empty list
        max_hops=2,
    )
```

**Input text construction**:

```python
def build_topological_text(entities: list[dict], neighbourhood: dict) -> str:
    """Build natural-language description of the topological neighbourhood.

    The neighbourhood dict (from ShadowTopologyService.get_neighbourhood) has:
      - "entities": list of {id, identifier, domain, origin, ...}
      - "relationships": list of {from_id, to_id, type, confidence, ...}
      - "depth_map": dict mapping entity_id -> hop distance from seed set
    """
    parts = []

    # Seed entities (hop 0)
    seed_ids = [e["identifier"] for e in entities[:20]]
    parts.append(f"Seed entities: {', '.join(seed_ids)}")

    # Neighbourhood entities grouped by hop distance
    depth_map = neighbourhood.get("depth_map", {})
    neighbour_entities = neighbourhood.get("entities", [])
    for hop in [1, 2]:
        at_hop = [
            ne for ne in neighbour_entities
            if depth_map.get(str(ne.get("id", ""))) == hop
        ]
        if at_hop:
            hop_names = [f"{ne['identifier']} [{ne.get('domain', '?')}]" for ne in at_hop[:15]]
            parts.append(f"Hop-{hop} neighbours: {', '.join(hop_names)}")

    # Relationship types summary
    relationships = neighbourhood.get("relationships", [])
    if relationships:
        rel_types = {}
        for r in relationships[:50]:
            rtype = r.get("type", "UNKNOWN")
            rel_types[rtype] = rel_types.get(rtype, 0) + 1
        rel_summary = ", ".join(f"{k}({v})" for k, v in sorted(rel_types.items()))
        parts.append(f"Relationship types: {rel_summary}")

    return "Topological context: " + "; ".join(parts)
```

**Rationale**: Unlike v2.0's `_build_topo_text` which only listed seed entities (because neighbourhood was always empty due to F-3.2), this version includes the full BFS expansion: hop-1 and hop-2 neighbours with their domains, and a summary of relationship types. T-VEC can encode the graph structure into a semantic space where topologically similar fragments cluster.

**Execution**:

```python
if shadow_topology and entities:
    try:
        # Resolve UUIDs and get neighbourhood (F-3.2 fix above)
        entity_uuids = await _resolve_entity_uuids(session, tenant_id, entities, shadow_topology)
        neighbourhood = await shadow_topology.get_neighbourhood(
            session, tenant_id, entity_ids=entity_uuids, max_hops=2)
        topo_text = build_topological_text(entities, neighbourhood)
        emb_topological = await tvec_client.embed(topo_text)
        assert len(emb_topological) == 1536
        mask_topological = True
    except Exception:
        logger.warning("T-VEC topological embedding failed", exc_info=True)
        emb_topological = None
        mask_topological = False
else:
    # No shadow topology service or no entities extracted
    emb_topological = None
    mask_topological = False
```

---

### Step (d): Sinusoidal Temporal Encoding -> `emb_temporal` (256)

**Model**: None (pure math)
**Column**: `emb_temporal vector(256)` NOT NULL
**Mask**: No mask column. Always valid.

**Design**: 256-dimensional vector built from sinusoidal encodings of temporal features at multiple frequencies. This replaces the v2.0 approach of 10 features zero-padded to 256.

**Encoding scheme**:

The 256 dimensions are partitioned into frequency bands:

| Feature | Dim range | Period basis | Encoding |
|---------|-----------|-------------|----------|
| Time of day | 0-63 | 24h cycle | sin/cos at 32 frequencies |
| Day of week | 64-127 | 7-day cycle | sin/cos at 32 frequencies |
| Day of year (seasonal) | 128-191 | 365-day cycle | sin/cos at 32 frequencies |
| Operational context | 192-255 | Mixed | change_proximity, upgrade_recency, load_ratio, padding |

**Implementation**:

```python
def build_temporal_vector(event_time: datetime, fingerprint: dict) -> np.ndarray:
    """Build 256-dim temporal embedding using sinusoidal position encoding.

    Always succeeds. No model dependency. No failure mode.
    """
    vec = np.zeros(256, dtype=np.float32)

    hour = event_time.hour + event_time.minute / 60.0
    dow = event_time.weekday()
    doy = event_time.timetuple().tm_yday

    # Time-of-day: 32 frequency pairs (dims 0-63)
    for i in range(32):
        freq = 1.0 / (24.0 * (1.5 ** i / 32))
        vec[2 * i]     = math.sin(2 * math.pi * hour * freq)
        vec[2 * i + 1] = math.cos(2 * math.pi * hour * freq)

    # Day-of-week: 32 frequency pairs (dims 64-127)
    for i in range(32):
        freq = 1.0 / (7.0 * (1.5 ** i / 32))
        vec[64 + 2 * i]     = math.sin(2 * math.pi * dow * freq)
        vec[64 + 2 * i + 1] = math.cos(2 * math.pi * dow * freq)

    # Day-of-year (seasonal): 32 frequency pairs (dims 128-191)
    for i in range(32):
        freq = 1.0 / (365.0 * (1.5 ** i / 32))
        vec[128 + 2 * i]     = math.sin(2 * math.pi * doy * freq)
        vec[128 + 2 * i + 1] = math.cos(2 * math.pi * doy * freq)

    # Operational context features (dims 192-255)
    change_hours = (fingerprint.get("change_proximity") or {}).get("nearest_change_hours")
    upgrade_days = (fingerprint.get("vendor_upgrade") or {}).get("days_since_upgrade")
    load_ratio   = (fingerprint.get("traffic_cycle") or {}).get("load_ratio_vs_baseline")

    # Gaussian decay for change proximity (sigma=24h)
    vec[192] = math.exp(-(change_hours ** 2) / (2 * 24 ** 2)) if change_hours is not None else 0.0
    # Exponential decay for upgrade recency (tau=30d)
    vec[193] = math.exp(-upgrade_days / 30.0) if upgrade_days is not None else 0.0
    # Load ratio (clamped 0-2, normalised to 0-1)
    vec[194] = min(load_ratio / 2.0, 1.0) if load_ratio is not None else 0.0
    # Remaining dims 195-255 are zero (reserved for future operational signals)

    return vec
```

**Rationale for multi-frequency sinusoidal encoding**: The v2.0 `_build_temporal_vector` used 10 scalar features padded to 256, wasting 246 dimensions. Multi-frequency sinusoidal encoding (following transformer positional encoding patterns) provides:
- Smooth interpolation between adjacent time points
- Discrimination at multiple granularities (minute-level to seasonal)
- Bounded values in [-1, 1] without normalisation
- No model dependency; deterministic; always valid

---

### Step (e): T-VEC Operational Embedding -> `emb_operational` (1536)

**Model**: T-VEC 1.5B (CPU, local)
**Column**: `emb_operational vector(1536)`
**Mask**: `mask_operational boolean`

**Input text construction**:

```python
def build_operational_text(
    failure_modes: list[dict],
    fingerprint: dict,
    entities: list[dict],
    raw_content: str,
) -> str:
    """Build text for operational fingerprint embedding.

    Combines failure-mode hypotheses from TSLAM with operational context
    from the fingerprint to create a text that T-VEC can embed into
    an operational similarity space.
    """
    parts = []

    # Failure mode hypotheses (from TSLAM-8B or rule-based fallback)
    for fm in failure_modes[:5]:
        if isinstance(fm, dict):
            dtype = fm.get("divergence_type", "UNKNOWN")
            conf = fm.get("confidence", 0.0)
            rationale = fm.get("rationale", "")
            candidates = fm.get("candidate_entities", [])
            parts.append(
                f"Hypothesis {dtype} (conf={conf:.2f}): {rationale}. "
                f"Entities: {', '.join(candidates[:5])}"
            )

    # Operational fingerprint context
    tc = fingerprint.get("traffic_cycle") or {}
    time_bucket = tc.get("time_bucket", "unknown")
    hour = tc.get("hour_utc", "?")
    day = tc.get("day_of_week", "?")
    parts.append(f"Traffic regime: {time_bucket} (hour={hour}, day={day})")

    change_info = fingerprint.get("change_proximity") or {}
    change_hours = change_info.get("nearest_change_hours")
    if change_hours is not None:
        parts.append(f"Nearest change record: {change_hours:.1f}h ago")

    alarm_count = (fingerprint.get("concurrent_alarms") or {}).get("count_1h_window")
    if alarm_count is not None:
        parts.append(f"Concurrent alarms (1h): {alarm_count}")

    # Entity domains summary for operational context
    domains = {}
    for e in entities:
        d = e.get("domain", "UNKNOWN")
        domains[d] = domains.get(d, 0) + 1
    if domains:
        domain_summary = ", ".join(f"{k}({v})" for k, v in sorted(domains.items()))
        parts.append(f"Entity domains: {domain_summary}")

    return "Operational fingerprint: " + "; ".join(parts)
```

**Rationale**: The operational embedding captures the "how and when is this failing" signal. By including TSLAM-8B hypotheses (which are richer than v2.0's keyword rules), traffic regime, change proximity, and alarm context, T-VEC produces embeddings where operationally similar failures cluster even when the raw text differs.

**Execution**:

```python
try:
    oper_text = build_operational_text(failure_modes, fingerprint, entities, raw_content)
    emb_operational = await tvec_client.embed(oper_text)
    assert len(emb_operational) == 1536
    mask_operational = True
except Exception:
    logger.warning("T-VEC operational embedding failed", exc_info=True)
    emb_operational = None
    mask_operational = False
```

---

## 4. Per-Dimension Failure Handling

### 4.1 Failure Isolation Guarantee

Each dimension's embedding is computed independently. A failure in one dimension MUST NOT prevent the others from completing. This is the core fix for F-6.1 (LLM outage degenerates system to temporal-only).

```
Step (a) TSLAM-8B fails:
  -> entities = regex fallback (always produces results for structured content)
  -> failure_modes = rule-based fallback
  -> Steps (b)-(e) proceed normally

Step (b) T-VEC semantic fails:
  -> emb_semantic = NULL, mask_semantic = FALSE
  -> Steps (c), (d), (e) unaffected

Step (c) T-VEC topological fails (or shadow topology unavailable):
  -> emb_topological = NULL, mask_topological = FALSE
  -> Steps (b), (d), (e) unaffected

Step (d) Sinusoidal temporal:
  -> CANNOT FAIL (pure math, no external dependency)
  -> emb_temporal always populated, no mask needed

Step (e) T-VEC operational fails:
  -> emb_operational = NULL, mask_operational = FALSE
  -> Steps (b), (c), (d) unaffected
```

### 4.2 Failure Matrix

| Failure scenario | emb_semantic | emb_topological | emb_temporal | emb_operational | Fragment usable? |
|-----------------|-------------|----------------|-------------|----------------|-----------------|
| All systems healthy | 1536-vec | 1536-vec | 256-vec | 1536-vec | Full fidelity |
| T-VEC down entirely | NULL | NULL | 256-vec | NULL | Temporal-only; snap engine weights temporal at 100% of available signal |
| Shadow topology unavailable | 1536-vec | NULL | 256-vec | 1536-vec | 3 of 4 dimensions; snap engine excludes topological weight |
| TSLAM-8B down | 1536-vec* | 1536-vec* | 256-vec | 1536-vec* | Full fidelity but with regex entities and rule-based hypotheses |
| T-VEC semantic fails only | NULL | 1536-vec | 256-vec | 1536-vec | 3 of 4 dimensions |

*When TSLAM-8B fails, T-VEC still receives text (just built from regex entities and rule-based failure modes instead of TSLAM output). T-VEC itself may still succeed.

### 4.3 Invariant: No Hash Embedding Fallback (F-3.3 resolution)

The v2.0 code contained a hash-based embedding fallback triggered when `loop.is_running() == True`, which is ALWAYS true in an async FastAPI server. This fallback is **deleted entirely** in v3.0.

There is no code path in v3.0 that produces a hash-derived embedding. The only outcomes for a T-VEC embedding dimension are:
1. **Valid vector** (1536 floats) with mask = TRUE
2. **NULL** with mask = FALSE

No intermediate state. No zero-fill. No deterministic hash. INV-11 is enforced structurally, not by convention.

---

## 5. Async Execution Strategy

The enrichment flow assumes the serving layer from T1.1 provides:
- `tvec_client`: async wrapper around T-VEC 1.5B inference (connection pool, circuit breaker)
- `tslam_client`: async wrapper around TSLAM-8B inference (connection pool, circuit breaker)

### 5.1 Parallelisation

Steps (b), (d), and (e) are independent of each other and can run concurrently via `asyncio.gather`. Step (c) depends on the Shadow Topology lookup (which itself depends on entity UUIDs from step (a)), but is otherwise independent of (b), (d), (e).

**Execution DAG**:

```
Step (a): TSLAM-8B entity extraction
   |
   v
   +---------- entity_uuids resolved via Shadow Topology -------+
   |                                                             |
   v                                                             v
Step (b): T-VEC semantic     Step (d): Sinusoidal        Step (c): Shadow Topology
          (parallel)           temporal (parallel)         get_neighbourhood()
                               (instant)                        |
                                                                v
                                                         Step (c) cont: T-VEC
                                                           topological
                                                                |
Step (e): T-VEC operational  <-- depends on failure_modes       |
          (parallel with c)     from step (a)                   |
   |                                                             |
   v                                                             v
   +--------- asyncio.gather collects all results ---------------+
   |
   v
 Persist fragment with embeddings + masks
```

**Implementation sketch**:

```python
async def _compute_all_embeddings(
    self,
    session: AsyncSession,
    tenant_id: str,
    raw_content: str,
    source_type: str,
    entities: list[dict],
    failure_modes: list[dict],
    fingerprint: dict,
    event_time: datetime,
) -> dict:
    """Compute all four embedding dimensions with independent failure handling."""

    # Temporal is synchronous and instant
    emb_temporal = build_temporal_vector(event_time, fingerprint)

    # Build input texts
    semantic_text = build_semantic_text(raw_content, entities, source_type)
    oper_text = build_operational_text(failure_modes, fingerprint, entities, raw_content)

    # Shadow Topology lookup (may fail independently)
    topo_task = self._compute_topological(session, tenant_id, entities)

    # Fire T-VEC calls concurrently
    semantic_task = self._safe_tvec_embed(semantic_text, "semantic")
    oper_task = self._safe_tvec_embed(oper_text, "operational")

    sem_result, topo_result, oper_result = await asyncio.gather(
        semantic_task, topo_task, oper_task,
        return_exceptions=False,  # exceptions handled inside each task
    )

    return {
        "emb_semantic": sem_result["embedding"],
        "mask_semantic": sem_result["valid"],
        "emb_topological": topo_result["embedding"],
        "mask_topological": topo_result["valid"],
        "emb_temporal": emb_temporal.tolist(),
        # no mask_temporal -- always valid
        "emb_operational": oper_result["embedding"],
        "mask_operational": oper_result["valid"],
        "neighbourhood": topo_result.get("neighbourhood", {}),
    }

async def _safe_tvec_embed(self, text: str, dimension_name: str) -> dict:
    """T-VEC embed with failure isolation. Returns NULL + FALSE on any error."""
    try:
        vec = await self._tvec_client.embed(text)
        if vec is not None and len(vec) == 1536:
            return {"embedding": vec, "valid": True}
        else:
            logger.warning(
                "T-VEC %s returned unexpected dimension: %s",
                dimension_name, len(vec) if vec else "None",
            )
            return {"embedding": None, "valid": False}
    except Exception:
        logger.warning("T-VEC %s embedding failed", dimension_name, exc_info=True)
        return {"embedding": None, "valid": False}

async def _compute_topological(
    self, session: AsyncSession, tenant_id: str, entities: list[dict],
) -> dict:
    """Resolve entity UUIDs, get neighbourhood, embed. F-3.2 fix."""
    if not self._shadow_topology or not entities:
        return {"embedding": None, "valid": False, "neighbourhood": {}}

    try:
        # Resolve identifiers to UUIDs (F-3.2 fix: no more empty list)
        entity_uuids = []
        for e in entities:
            shadow_ent = await self._shadow_topology.get_or_create_entity(
                session, tenant_id,
                entity_identifier=e["identifier"],
                entity_domain=e.get("domain"),
                origin="ABEYANCE_OBSERVED",
            )
            entity_uuids.append(shadow_ent.id)

        # Get neighbourhood with ACTUAL UUIDs
        neighbourhood = await self._shadow_topology.get_neighbourhood(
            session, tenant_id,
            entity_ids=entity_uuids,
            max_hops=2,
        )

        # Build text and embed
        topo_text = build_topological_text(entities, neighbourhood)
        vec = await self._tvec_client.embed(topo_text)
        if vec is not None and len(vec) == 1536:
            return {"embedding": vec, "valid": True, "neighbourhood": neighbourhood}
        else:
            return {"embedding": None, "valid": False, "neighbourhood": neighbourhood}

    except Exception:
        logger.warning("Topological embedding pipeline failed", exc_info=True)
        return {"embedding": None, "valid": False, "neighbourhood": {}}
```

---

## 6. Enrichment Chain Public Interface (v3.0)

### 6.1 Constructor

```python
class EnrichmentChain:
    def __init__(
        self,
        provenance: ProvenanceLogger,
        tvec_client: TVecClient,              # T-VEC 1.5B async wrapper (from T1.1 serving layer)
        tslam_client: Optional[TSlamClient],   # TSLAM-8B async wrapper (from T1.1 serving layer)
        shadow_topology: Optional[ShadowTopologyService],
    ):
```

**Change from v2.0**: `llm_service: Optional[Any]` replaced by two typed clients. The generic LLM service (which made cloud calls) is eliminated entirely.

### 6.2 Main Entry Point

```python
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
) -> AbeyanceFragmentORM:
```

Signature unchanged from v2.0 for backward compatibility.

### 6.3 Internal Methods (changed)

| v2.0 Method | v3.0 Replacement | Reason |
|-------------|-----------------|--------|
| `_llm_extract_entities()` | TSLAM-8B call in step (a) | Local model replaces cloud LLM |
| `_classify_failure_modes()` | TSLAM-8B call in step (a), retained as fallback | Local model produces richer hypotheses |
| `_compute_embeddings()` -> single method, 4 LLM calls | `_compute_all_embeddings()` -> 3 T-VEC + 1 sinusoidal, parallelised | Per-dimension failure isolation |
| `_build_topo_text()` | `build_topological_text()` | Richer text from actual neighbourhood (F-3.2 fix) |
| `_build_operational_text()` | `build_operational_text()` | Includes TSLAM hypotheses |
| `_build_temporal_vector()` | `build_temporal_vector()` | Multi-frequency sinusoidal encoding |

### 6.4 Removed

| v2.0 Component | Reason for removal |
|----------------|-------------------|
| `llm_service` injection | Replaced by `tvec_client` + `tslam_client` |
| Hash embedding fallback (implicit via loop check) | F-3.3: deleted entirely; INV-11 enforced structurally |
| `raw_embedding` (768-dim) computation | No longer needed; 4 separate typed columns replace the single concatenated vector |
| L2 normalisation of concatenated enriched vector | Each column is stored independently; normalisation happens per-column if needed by snap engine |
| `SEMANTIC_DIM=512`, `TOPOLOGICAL_DIM=384`, `OPERATIONAL_DIM=384` | All three now 1536 (native T-VEC output dimension) |
| `ENRICHED_DIM=1536` (sum of sub-vectors) | No longer a single concatenated vector |
| `RAW_DIM=768` | No raw embedding in v3.0 |

---

## 7. Data Flow Summary

```
raw_content + source_type + event_timestamp
       |
       v
   [Step a] TSLAM-8B (or regex+rules fallback)
       |
       +---> entities: list[dict]         (identifier, domain)
       +---> failure_modes: list[dict]    (divergence_type, confidence, rationale)
       |
       v
   [Operational Fingerprint]  (unchanged from v2.0)
       |
       +---> fingerprint: dict
       |
       v
   [Parallel embedding computation]
       |
       +---> [Step b] T-VEC(semantic_text)    -> emb_semantic(1536)  / NULL
       +---> [Step c] Shadow Topo + T-VEC     -> emb_topological(1536) / NULL
       +---> [Step d] Sinusoidal(event_time)  -> emb_temporal(256)   (always)
       +---> [Step e] T-VEC(operational_text) -> emb_operational(1536) / NULL
       |
       v
   [Persist]
       AbeyanceFragmentORM {
           emb_semantic, emb_topological, emb_temporal, emb_operational,
           mask_semantic, mask_topological, mask_operational,
           extracted_entities, failure_mode_tags, operational_fingerprint,
           topological_neighbourhood, temporal_context,
           ...existing fields...
       }
```

---

## 8. Dimension Constants (v3.0)

```python
# Embedding dimensions -- v3.0
SEMANTIC_DIM = 1536       # T-VEC native output
TOPOLOGICAL_DIM = 1536    # T-VEC native output
TEMPORAL_DIM = 256        # Sinusoidal encoding
OPERATIONAL_DIM = 1536    # T-VEC native output
# No ENRICHED_DIM -- columns are separate, not concatenated
# No RAW_DIM -- raw embedding removed
```

---

## 9. Migration Notes

### 9.1 Schema Changes Required (reference for T1.2)

The v2.0 `abeyance_fragment` table stores:
- `embedding_mask` (JSON array of 4 booleans)
- `enriched_embedding` (single 1536-dim vector)
- `raw_embedding` (768-dim vector)

v3.0 requires:
- `emb_semantic` vector(1536) NULL
- `emb_topological` vector(1536) NULL
- `emb_temporal` vector(256) NOT NULL
- `emb_operational` vector(1536) NULL
- `mask_semantic` boolean DEFAULT FALSE
- `mask_topological` boolean DEFAULT FALSE
- `mask_operational` boolean DEFAULT FALSE
- DROP: `embedding_mask`, `enriched_embedding`, `raw_embedding`

### 9.2 Snap Engine Changes Required (reference for T1.4)

The snap engine must:
1. Read individual `mask_*` columns instead of the JSON `embedding_mask` array.
2. Compute per-dimension cosine similarity only when BOTH fragments have `mask_X = TRUE` for dimension X.
3. Re-weight the WEIGHT_PROFILES dynamically: if a dimension is unavailable for either fragment in a pair, redistribute its weight proportionally across available dimensions.
4. Use separate pgvector indexes per embedding column for ANN retrieval.

---

## 10. Acceptance Criteria Verification

| Criterion | Section | Status |
|-----------|---------|--------|
| Step-by-step enrichment flow with all 5 stages | Section 3 | Specified: (a) TSLAM entity extraction, (b) T-VEC semantic, (c) T-VEC topological, (d) sinusoidal temporal, (e) T-VEC operational |
| Input text construction per T-VEC call | Sections 3 steps (b), (c), (e) | `build_semantic_text`, `build_topological_text`, `build_operational_text` fully specified |
| F-3.2 fix: entity_identifiers passed to get_neighbourhood() | Section 3 step (c) | Entity identifiers resolved to UUIDs via `get_or_create_entity()`, then passed as `entity_ids` parameter |
| Per-dimension failure handling | Section 4 | Each dimension fails independently to NULL + mask FALSE; failure matrix provided |
| No hash embedding fallback (F-3.3) | Section 4.3 | Hash fallback deleted entirely; only two outcomes per dimension: valid vector or NULL |
| Async-compatible | Section 5 | `asyncio.gather` parallelisation; assumes T1.1 serving layer clients |
