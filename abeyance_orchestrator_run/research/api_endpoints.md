# Abeyance Memory API Endpoints Extraction

## Document Scope
Complete API endpoint specification for the Abeyance Memory subsystem covering:
- `/Users/himanshu/Projects/Pedkai/backend/app/api/abeyance.py`
- `/Users/himanshu/Projects/Pedkai/backend/app/api/shadow_topology.py`
- `/Users/himanshu/Projects/Pedkai/backend/app/api/value.py`

All endpoint paths, methods, handlers, file locations, and request/response models.

---

## Abeyance Core API Router

**File:** `/Users/himanshu/Projects/Pedkai/backend/app/api/abeyance.py`
**Service Factory:** `create_abeyance_services()` (creates shared ProvenanceLogger and RedisNotifier)

---

### POST /ingest

**Handler Function:** `ingest_evidence()`
**File Location:** `/Users/himanshu/Projects/Pedkai/backend/app/api/abeyance.py:84-150`

**Purpose:** Submit raw evidence for enrichment and snap evaluation. Processes evidence through enrichment chain and snap engine evaluation.

**Security:**
- Requires: `Security(get_current_user, scopes=[INCIDENT_READ])`

**Request Model:** `RawEvidence`
```
{
  "content": str (required),
  "source_type": SourceType enum (required),
    — TICKET_TEXT, ALARM, TELEMETRY_EVENT, CLI_OUTPUT, CHANGE_RECORD, CMDB_DELTA
  "source_ref": str (optional),
  "source_engineer_id": str (optional),
  "entity_refs": list[str] (default: []),
  "event_timestamp": datetime (optional),
  "metadata": dict[str, Any] (default: {})
}
```

**Response Model:** `AbeyanceFragmentResponse` (201 Created)
```
{
  "id": UUID,
  "tenant_id": str,
  "source_type": str,
  "raw_content": str | null,
  "extracted_entities": list[Any],
  "topological_neighbourhood": dict[str, Any],
  "operational_fingerprint": dict[str, Any],
  "failure_mode_tags": list[Any],
  "temporal_context": dict[str, Any],
  "event_timestamp": datetime | null,
  "ingestion_timestamp": datetime | null,
  "base_relevance": float,
  "current_decay_score": float,
  "near_miss_count": int,
  "snap_status": str,
  "snapped_hypothesis_id": UUID | null,
  "source_ref": str | null,
  "created_at": datetime | null
}
```

**Processing Steps:**
1. Enrichment chain (LLD §6):
   - Entity resolution (LLM + regex fallback)
   - Operational fingerprinting
   - Failure mode classification
   - Temporal-semantic embedding with validity mask
2. Snap engine evaluation (LLD §9)
3. Accumulation cluster detection (best-effort)

**LLD Reference:** §6 (Enrichment Chain), §9 (Snap Engine)

**Query Parameters:**
- `tenant_id` (optional, resolved from current_user if not provided)

---

### GET /fragments

**Handler Function:** `list_fragments()`
**File Location:** `/Users/himanshu/Projects/Pedkai/backend/app/api/abeyance.py:157-191`

**Purpose:** List abeyance fragments with optional filters

**Security:**
- Requires: `Security(get_current_user, scopes=[INCIDENT_READ])`

**Query Parameters:**
- `tenant_id` (Optional[str]) — defaults to current_user.tenant_id
- `snap_status` (Optional[str]) — filter by lifecycle state
- `source_type` (Optional[str]) — filter by source type
- `limit` (int, default=50, 1-500) — result limit
- `offset` (int, default=0, ≥0) — result offset

**Response Model:** `List[AbeyanceFragmentSummary]` (200 OK)
```
[
  {
    "id": UUID,
    "tenant_id": str,
    "source_type": str,
    "snap_status": str,
    "current_decay_score": float,
    "near_miss_count": int,
    "event_timestamp": datetime | null,
    "created_at": datetime | null,
    "source_ref": str | null
  }
  ...
]
```

**Filters:**
- Order by: created_at DESC
- Tenant isolation applied

**LLD Reference:** §5 (Fragment Model)

---

### GET /fragments/{fragment_id}

**Handler Function:** `get_fragment()`
**File Location:** `/Users/himanshu/Projects/Pedkai/backend/app/api/abeyance.py:198-219`

**Purpose:** Get a single fragment with full enrichment details

**Security:**
- Requires: `Security(get_current_user, scopes=[INCIDENT_READ])`
- Tenant isolation check (INV-7)

**Path Parameters:**
- `fragment_id` (UUID) — fragment identifier

**Response Model:** `AbeyanceFragmentResponse` (200 OK) or 404 Not Found

**LLD Reference:** §5 (Fragment Model)

---

### GET /snap-history

**Handler Function:** `get_snap_history()`
**File Location:** `/Users/himanshu/Projects/Pedkai/backend/app/api/abeyance.py:226-264`

**Purpose:** Query successful snaps with full scoring provenance (backed by snap_decision_record)

**Security:**
- Requires: `Security(get_current_user, scopes=[INCIDENT_READ])`

**Query Parameters:**
- `tenant_id` (Optional[str])
- `limit` (int, default=50, 1-500)
- `offset` (int, default=0, ≥0)

**Response Model:** `List[SnapHistoryEntry]` (200 OK)
```
[
  {
    "fragment_id": UUID,
    "snapped_to": UUID | null,
    "snap_score": float,
    "failure_mode": str | null,
    "snapped_at": datetime | null
  }
  ...
]
```

**Data Source:** `SnapDecisionRecordORM` (provenance-backed)
- Filtered: decision IN ("SNAP", "NEAR_MISS")
- Ordered by: evaluated_at DESC

**LLD Reference:** §9 (Snap Engine), INV-10 (provenance)

---

### GET /accumulation-graph

**Handler Function:** `get_accumulation_edges()`
**File Location:** `/Users/himanshu/Projects/Pedkai/backend/app/api/abeyance.py:271-297`

**Purpose:** Query accumulation graph edges (weak affinity links)

**Security:**
- Requires: `Security(get_current_user, scopes=[INCIDENT_READ])`

**Query Parameters:**
- `tenant_id` (Optional[str])
- `fragment_id` (Optional[UUID]) — filter edges where fragment_id is either fragment_a or fragment_b
- `limit` (int, default=100, 1-1000)

**Response Model:** `List[AccumulationEdgeResponse]` (200 OK)
```
[
  {
    "id": UUID,
    "fragment_a_id": UUID,
    "fragment_b_id": UUID,
    "affinity_score": float,
    "strongest_failure_mode": str | null,
    "created_at": datetime | null
  }
  ...
]
```

**LLD Reference:** §10 (Accumulation Graph)

---

### GET /accumulation-graph/clusters

**Handler Function:** `get_accumulation_clusters()`
**File Location:** `/Users/himanshu/Projects/Pedkai/backend/app/api/abeyance.py:304-332`

**Purpose:** List current accumulation clusters (LME-scored union-find detection, remediated per Audit §4.1, §5.3)

**Security:**
- Requires: `Security(get_current_user, scopes=[INCIDENT_READ])`

**Query Parameters:**
- `tenant_id` (Optional[str])

**Response Model:** `List[AccumulationClusterResponse]` (200 OK)
```
[
  {
    "cluster_id": str,
    "member_fragment_ids": list[UUID],
    "member_count": int,
    "cluster_score": float,
    "strongest_failure_mode": str | null
  }
  ...
]
```

**Implementation:** Calls `accumulation_graph.detect_and_evaluate_clusters()` service method

**LLD Reference:** §10 (Accumulation Graph)

---

### GET /reconstruction

**Handler Function:** `reconstruct_incident()`
**File Location:** `/Users/himanshu/Projects/Pedkai/backend/app/api/abeyance.py:339-363`

**Purpose:** Reconstruct incident timeline from provenance data

**Security:**
- Requires: `Security(get_current_user, scopes=[INCIDENT_READ])`

**Query Parameters:**
- `tenant_id` (Optional[str])
- `hypothesis_id` (Optional[UUID])
- `entity_identifier` (Optional[str])
- `time_start` (Optional[datetime])
- `time_end` (Optional[datetime])

**Response Model:** `IncidentReconstructionResponse` (200 OK)
```
{
  "incident_id": str,
  "tenant_id": str,
  "fragments": list[AbeyanceFragmentSummary],
  "snaps": list[SnapHistoryEntry],
  "clusters": list[AccumulationClusterResponse],
  "reconstructed_timeline": list[dict[str, Any]]
}
```

**Implementation:** Calls `incident_reconstruction.reconstruct()` service method

**LLD Reference:** §12 (Incident Reconstruction)

---

### POST /maintenance

**Handler Function:** `run_maintenance()`
**File Location:** `/Users/himanshu/Projects/Pedkai/backend/app/api/abeyance.py:370-386`

**Purpose:** Trigger full maintenance pass (decay, prune, expire, orphan cleanup)

**Security:**
- Requires: `Security(get_current_user, scopes=[INCIDENT_READ])`

**Query Parameters:**
- `tenant_id` (Optional[str])

**Response Model:** Dictionary with maintenance results (200 OK)

**Implementation:** Calls `maintenance.run_full_maintenance()` service method

**LLD Reference:** §11 (Decay Engine), §5 (Maintenance)

---

## Shadow Topology API Router

**File:** `/Users/himanshu/Projects/Pedkai/backend/app/api/shadow_topology.py`
**Service Function:** `get_shadow_topology(async_session_maker)`

---

### GET /shadow-topology/entities

**Handler Function:** `list_shadow_entities()`
**File Location:** `/Users/himanshu/Projects/Pedkai/backend/app/api/shadow_topology.py:31-56`

**Purpose:** List shadow entities in the private topology graph

**Security:**
- Requires: `Security(get_current_user, scopes=[INCIDENT_READ])`

**Query Parameters:**
- `tenant_id` (Optional[str])
- `origin` (Optional[str]) — CMDB_DECLARED, PEDKAI_DISCOVERED, PEDKAI_CORRECTED
- `limit` (int, default=100, 1-1000)
- `offset` (int, default=0, ≥0)

**Response Model:** `List[ShadowEntityResponse]` (200 OK)
```
[
  {
    "id": UUID,
    "tenant_id": str,
    "entity_identifier": str,
    "entity_domain": str | null,
    "origin": str,
    "enrichment_value": float,
    "first_seen": datetime | null,
    "last_evidence": datetime | null
  }
  ...
]
```

**Ordering:** created_at DESC

**LLD Reference:** §8 (Shadow Topology Graph)

---

### GET /shadow-topology/neighbourhood/{entity_identifier}

**Handler Function:** `get_neighbourhood()`
**File Location:** `/Users/himanshu/Projects/Pedkai/backend/app/api/shadow_topology.py:59-91`

**Purpose:** Get N-hop neighbourhood expansion for a shadow entity

**Security:**
- Requires: `Security(get_current_user, scopes=[INCIDENT_READ])`

**Path Parameters:**
- `entity_identifier` (str) — entity name/identifier

**Query Parameters:**
- `tenant_id` (Optional[str])
- `hops` (int, default=2, 1-5) — depth of neighbourhood exploration

**Response Model:** `ShadowNeighbourhoodResponse` (200 OK) or 404 Not Found
```
{
  "center_entity": str,
  "entities": list[ShadowEntityResponse],
  "relationships": list[ShadowRelationshipResponse],
  "max_hops": int
}
```

**ShadowRelationshipResponse:**
```
{
  "id": UUID,
  "from_entity_id": UUID,
  "to_entity_id": UUID,
  "relationship_type": str,
  "origin": str,
  "confidence": float,
  "exported_to_cmdb": bool,
  "cmdb_reference_tag": str | null
}
```

**Implementation:** Calls `shadow_topology.get_neighbourhood(tid, entity_identifier, hops)`

**LLD Reference:** §8 (Shadow Topology Graph)

---

### POST /shadow-topology/export/{relationship_id}

**Handler Function:** `export_to_cmdb()`
**File Location:** `/Users/himanshu/Projects/Pedkai/backend/app/api/shadow_topology.py:94-120`

**Purpose:** Controlled export of a shadow relationship to CMDB (sanitised, competitive intelligence retained)

**Security:**
- Requires: `Security(get_current_user, scopes=[INCIDENT_READ])`

**Path Parameters:**
- `relationship_id` (UUID) — shadow relationship identifier

**Query Parameters:**
- `tenant_id` (Optional[str])

**Response Model:** `CmdbExportResponse` (200 OK) or 404 Not Found
```
{
  "export_id": UUID,
  "cmdb_reference_tag": str,
  "exported_at": datetime
}
```

**Implementation:** Calls `shadow_topology.export_to_cmdb(tid, relationship_id)`

**LLD Reference:** §8 (Shadow Topology Graph — CMDB Export)

---

## Value Attribution API Router

**File:** `/Users/himanshu/Projects/Pedkai/backend/app/api/value.py`
**Service Factory:** `ValueAttributionService(async_session_maker)`

---

### GET /value/ledger

**Handler Function:** `get_discovery_ledger()`
**File Location:** `/Users/himanshu/Projects/Pedkai/backend/app/api/value.py:35-56`

**Purpose:** Get paginated discovery ledger entries (permanent record of PedkAI discoveries)

**Security:**
- Requires: `Security(get_current_user, scopes=[INCIDENT_READ])`

**Query Parameters:**
- `tenant_id` (Optional[str])
- `limit` (int, default=50, 1-500)
- `offset` (int, default=0, ≥0)

**Response Model:** `List[DiscoveryLedgerResponse]` (200 OK)
```
[
  {
    "id": UUID,
    "tenant_id": str,
    "hypothesis_id": UUID | null,
    "discovery_type": str,
      — DARK_NODE, DARK_EDGE, PHANTOM_CI, IDENTITY_MUTATION, DARK_ATTRIBUTE
    "discovered_entities": list[Any],
    "cmdb_reference_tag": str | null,
    "discovered_at": datetime | null,
    "discovery_confidence": float,
    "status": str
  }
  ...
]
```

**Implementation:** Calls `value_service.get_ledger(tid, limit, offset)`

**LLD Reference:** §13 (Value Attribution Framework)

---

### GET /value/events

**Handler Function:** `get_value_events()`
**File Location:** `/Users/himanshu/Projects/Pedkai/backend/app/api/value.py:59-80`

**Purpose:** Get paginated value attribution events (realised benefit tracking)

**Security:**
- Requires: `Security(get_current_user, scopes=[INCIDENT_READ])`

**Query Parameters:**
- `tenant_id` (Optional[str])
- `limit` (int, default=50, 1-500)
- `offset` (int, default=0, ≥0)

**Response Model:** `List[ValueEventResponse]` (200 OK)
```
[
  {
    "id": UUID,
    "tenant_id": str,
    "ledger_entry_id": UUID,
    "event_type": str,
      — INCIDENT_RESOLUTION, MTTR_REDUCTION, LICENCE_SAVING,
      — OUTAGE_PREVENTION, DARK_GRAPH_REDUCTION
    "event_at": datetime | null,
    "attributed_value_hours": float | null,
    "attributed_value_currency": float | null,
    "attribution_rationale": str | null
  }
  ...
]
```

**Implementation:** Calls `value_service.get_value_events(tid, limit, offset)`

**LLD Reference:** §13 (Value Attribution Framework)

---

### GET /value/report

**Handler Function:** `get_value_report()`
**File Location:** `/Users/himanshu/Projects/Pedkai/backend/app/api/value.py:83-103`

**Purpose:** Get quarterly or cumulative value attribution report

**Security:**
- Requires: `Security(get_current_user, scopes=[INCIDENT_READ])`

**Query Parameters:**
- `tenant_id` (Optional[str])
- `quarter` (Optional[str], format: YYYY-Q#, e.g., "2026-Q1")

**Response Model:** `ValueReportResponse` (200 OK)
```
{
  "tenant_id": str,
  "period": str,
  "total_discoveries": int,
  "mttr_hours_saved": float,
  "licence_savings_currency": float,
  "illumination_ratio": float,
  "dark_graph_reduction_index": float,
  "discovery_breakdown": dict[str, int],
  "value_events": list[ValueEventResponse]
}
```

**Implementation:** Calls `value_service.generate_quarterly_report(tid, period="current" or YYYY-Q#)`

**LLD Reference:** §13 (Value Attribution Framework)

---

### GET /value/illumination-ratio

**Handler Function:** `get_illumination_ratio()`
**File Location:** `/Users/himanshu/Projects/Pedkai/backend/app/api/value.py:106-124`

**Purpose:** Get current illumination ratio (incidents involving PedkAI-discovered entities / total incidents)

**Security:**
- Requires: `Security(get_current_user, scopes=[INCIDENT_READ])`

**Query Parameters:**
- `tenant_id` (Optional[str])

**Response Model:** `IlluminationRatioResponse` (200 OK)
```
{
  "tenant_id": str,
  "ratio": float,
  "incidents_with_pedkai_entities": int,
  "total_incidents": int
}
```

**Implementation:** Calls `value_service.compute_illumination_ratio(tid)`

**Metric Definition:** Higher ratio indicates greater topology illumination by PedkAI discoveries

**LLD Reference:** §13 (Value Attribution Framework — Rule 5)

---

### GET /value/dark-graph-index

**Handler Function:** `get_dark_graph_index()`
**File Location:** `/Users/himanshu/Projects/Pedkai/backend/app/api/value.py:127-146`

**Purpose:** Get Dark Graph Reduction Index (measures topology illumination progress)

**Security:**
- Requires: `Security(get_current_user, scopes=[INCIDENT_READ])`

**Query Parameters:**
- `tenant_id` (Optional[str])

**Response Model:** `DarkGraphIndexResponse` (200 OK)
```
{
  "tenant_id": str,
  "index": float,
  "current_divergences": int,
  "baseline_divergences": int
}
```

**Implementation:** Calls `value_service.compute_dark_graph_reduction_index(tid)`

**Metric Formula:** DGRI = 1 - (current_divergences / baseline_divergences)
- Value of 1.0: all divergences resolved
- Value of 0.0: no progress

**LLD Reference:** §13 (Value Attribution Framework — Rule 6)

---

## Endpoint Summary by Resource

| Resource | Method | Endpoint | Status Code | Notes |
|----------|--------|----------|-------------|-------|
| Fragment | POST | /abeyance/ingest | 201 | Ingestion & enrichment |
| Fragment | GET | /abeyance/fragments | 200 | List with filters |
| Fragment | GET | /abeyance/fragments/{id} | 200/404 | Single retrieval |
| Snap History | GET | /abeyance/snap-history | 200 | Provenance-backed |
| Accumulation | GET | /abeyance/accumulation-graph | 200 | Edge listing |
| Accumulation | GET | /abeyance/accumulation-graph/clusters | 200 | Cluster detection |
| Reconstruction | GET | /abeyance/reconstruction | 200 | Timeline assembly |
| Maintenance | POST | /abeyance/maintenance | 200 | Decay/prune/expire |
| Shadow Entity | GET | /shadow-topology/entities | 200 | Entity listing |
| Shadow Neighbourhood | GET | /shadow-topology/neighbourhood/{id} | 200/404 | N-hop expansion |
| CMDB Export | POST | /shadow-topology/export/{id} | 200/404 | Controlled export |
| Discovery | GET | /value/ledger | 200 | Ledger entries |
| Value Events | GET | /value/events | 200 | Event listing |
| Reports | GET | /value/report | 200 | Aggregated metrics |
| Illumination | GET | /value/illumination-ratio | 200 | Topology metric |
| Dark Graph | GET | /value/dark-graph-index | 200 | Reduction metric |

---

## Authentication & Authorization

**All endpoints require:**
- User authentication via `get_current_user()`
- Security scope: `INCIDENT_READ`
- Tenant isolation enforced via `tenant_id` parameter or current_user.tenant_id

**Tenant Isolation Strategy:**
```python
tid = current_user.tenant_id or query_tenant
if not tid:
    raise HTTPException(status_code=400, detail="tenant_id is required")
```

---

## Common Response Patterns

**Success (200 OK):** Requested data in response body
**Created (201 Created):** New resource with full details in response body
**Not Found (404):** Resource does not exist or tenant isolation denied access
**Bad Request (400):** Missing required parameters (e.g., tenant_id)
**Unauthorized (401 or 403):** Authentication/authorization failure

---

## Service Dependencies

All abeyance routers depend on:
1. `AsyncSession` via `get_db` dependency
2. `User` authentication via `get_current_user`
3. Service layer from respective modules:
   - Core abeyance services: `create_abeyance_services()`
   - Shadow topology: `get_shadow_topology(async_session_maker)`
   - Value attribution: `ValueAttributionService(async_session_maker)`

---

## LLD References

| Section | Topic |
|---------|-------|
| §5 | Fragment Model & Source Types |
| §6 | Enrichment Chain |
| §7 | Embedding Generation |
| §8 | Shadow Topology Graph |
| §9 | Snap Engine |
| §10 | Accumulation Graph |
| §11 | Decay Engine |
| §12 | Incident Reconstruction |
| §13 | Value Attribution Framework |

---

Generated: 2026-03-16 | Task T0.6
