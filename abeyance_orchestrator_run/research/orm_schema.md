# Abeyance Memory ORM Schema Extraction

## Document Scope
Complete ORM schema definitions for the Abeyance Memory subsystem as defined in:
- `/Users/himanshu/Projects/Pedkai/backend/app/models/abeyance_orm.py`

Covers all tables, columns, types, indexes, and constraints related to abeyance.

---

## Core Fragment Storage

### Table: `abeyance_fragment`
**Purpose:** Core fragment storage — unified canonical model (eliminates split-brain per Audit §3.1)

**Columns:**

| Column Name | Type | Nullable | Default | Constraints | Notes |
|-------------|------|----------|---------|-------------|-------|
| id | UUID | NO | uuid4() | PRIMARY KEY | Fragment ID |
| tenant_id | VARCHAR(100) | NO | - | - | Tenant isolation (INV-7) |
| source_type | VARCHAR(50) | NO | - | - | Fragment source (LLD §5) |
| source_ref | VARCHAR(500) | YES | NULL | - | Reference to source system |
| source_engineer_id | VARCHAR(255) | YES | NULL | - | Engineer identifier |
| raw_content | TEXT | YES | NULL | - | Bounded by 64KB (INV-6) |
| extracted_entities | JSONB | NO | [] | DEFAULT '[]' | Entity extraction results |
| topological_neighbourhood | JSONB | NO | {} | DEFAULT '{}' | Topology context |
| operational_fingerprint | JSONB | NO | {} | DEFAULT '{}' | Operational state snapshot |
| failure_mode_tags | JSONB | NO | [] | DEFAULT '[]' | Failure classifications |
| temporal_context | JSONB | NO | {} | DEFAULT '{}' | Temporal features |
| embedding_mask | JSONB | NO | [T,F,T,F] | DEFAULT '[true, false, true, false]' | Embedding validity (INV-11) |
| enriched_embedding | Vector(1536) | YES | NULL | - | Enriched embedding |
| raw_embedding | Vector(768) | YES | NULL | - | Raw embedding |
| event_timestamp | TIMESTAMP(TZ) | YES | NULL | - | Evidence timestamp |
| ingestion_timestamp | TIMESTAMP(TZ) | NO | now() | DEFAULT & server_default | Ingestion time |
| created_at | TIMESTAMP(TZ) | NO | now() | DEFAULT & server_default | Record creation |
| updated_at | TIMESTAMP(TZ) | YES | NULL | - | Last update time |
| base_relevance | FLOAT | NO | 1.0 | DEFAULT '1.0' | Initial relevance (LLD §11) |
| current_decay_score | FLOAT | NO | 1.0 | DEFAULT '1.0' | Exponential decay |
| near_miss_count | INTEGER | NO | 0 | DEFAULT '0' | Near-miss counter |
| snap_status | VARCHAR(20) | NO | INGESTED | DEFAULT 'INGESTED' | Lifecycle state (INV-1) |
| snapped_hypothesis_id | UUID | YES | NULL | - | Snap hypothesis link |
| max_lifetime_days | INTEGER | NO | 730 | DEFAULT '730' | Hard lifetime (INV-6) |
| dedup_key | VARCHAR(500) | YES | NULL | - | Deduplication key |

**Indexes:**

| Index Name | Columns | Type | Where Clause | Options |
|------------|---------|------|--------------|---------|
| ix_abeyance_fragment_tenant_status | (tenant_id, snap_status) | BTREE | - | - |
| ix_abeyance_fragment_tenant_created | (tenant_id, created_at) | BTREE | - | - |
| ix_abeyance_fragment_tenant_decay | (tenant_id, current_decay_score) | BTREE | snap_status IN ('ACTIVE', 'NEAR_MISS') | - |
| ix_abeyance_fragment_failure_modes | (failure_mode_tags) | GIN | - | jsonb_path_ops |
| ix_abeyance_fragment_entities | (extracted_entities) | GIN | - | jsonb_path_ops |
| uq_fragment_dedup | (tenant_id, dedup_key) | UNIQUE | dedup_key IS NOT NULL | - |

**State Machine (INV-1):**
```
INGESTED → ACTIVE → {NEAR_MISS, SNAPPED, STALE}
NEAR_MISS → {SNAPPED, ACTIVE, STALE}
STALE → EXPIRED
EXPIRED → COLD
SNAPPED → (terminal)
COLD → (terminal)
```

---

## Entity References

### Table: `fragment_entity_ref`
**Purpose:** Junction table linking fragments to referenced entities with topological distance

**Columns:**

| Column Name | Type | Nullable | Default | Constraints | Notes |
|-------------|------|----------|---------|-------------|-------|
| id | UUID | NO | uuid4() | PRIMARY KEY | Reference ID |
| fragment_id | UUID | NO | - | FK → abeyance_fragment(id) | Source fragment |
| entity_id | UUID | YES | NULL | - | Target entity (may not exist) |
| entity_identifier | VARCHAR(500) | NO | - | - | Entity string identifier |
| entity_domain | VARCHAR(50) | YES | NULL | - | RAN/TRANSPORT/CORE/IP/VNF/SITE |
| topological_distance | INTEGER | NO | 0 | DEFAULT '0' | Hops in topology |
| tenant_id | VARCHAR(100) | NO | - | - | Tenant isolation (INV-7) |

**Indexes:**

| Index Name | Columns | Type |
|------------|---------|------|
| ix_fer_entity_identifier_tenant | (entity_identifier, tenant_id) | BTREE |
| ix_fer_fragment_tenant | (fragment_id, tenant_id) | BTREE |
| ix_fer_entity_id_tenant | (entity_id, tenant_id) | BTREE |

---

## Accumulation Graph

### Table: `accumulation_edge`
**Purpose:** Weak affinity links between fragments (LLD §10), bounded per INV-9

**Columns:**

| Column Name | Type | Nullable | Default | Constraints | Notes |
|-------------|------|----------|---------|-------------|-------|
| id | UUID | NO | uuid4() | PRIMARY KEY | Edge ID |
| tenant_id | VARCHAR(100) | NO | - | - | Tenant isolation (INV-7) |
| fragment_a_id | UUID | NO | - | FK → abeyance_fragment(id) | Source fragment |
| fragment_b_id | UUID | NO | - | FK → abeyance_fragment(id) | Target fragment |
| affinity_score | FLOAT | NO | - | - | Similarity score |
| strongest_failure_mode | VARCHAR(50) | YES | NULL | - | Primary failure mode |
| created_at | TIMESTAMP(TZ) | NO | now() | DEFAULT & server_default | Edge creation |
| last_updated | TIMESTAMP(TZ) | NO | now() | DEFAULT & server_default | Last update |

**Indexes:**

| Index Name | Columns | Type | Notes |
|------------|---------|------|-------|
| ix_accum_edge_pair | (tenant_id, fragment_a_id, fragment_b_id) | UNIQUE | Tenant-scoped (Audit §9.2) |
| ix_accum_edge_frag_a | (tenant_id, fragment_a_id) | BTREE | - |
| ix_accum_edge_frag_b | (tenant_id, fragment_b_id) | BTREE | - |

---

## Provenance Tables (Append-Only, INV-10)

### Table: `fragment_history`
**Purpose:** Append-only fragment state change log (Audit §7.2)

**Columns:**

| Column Name | Type | Nullable | Default | Constraints | Notes |
|-------------|------|----------|---------|-------------|-------|
| id | UUID | NO | uuid4() | PRIMARY KEY | History record ID |
| fragment_id | UUID | NO | - | - | Referenced fragment |
| tenant_id | VARCHAR(100) | NO | - | - | Tenant isolation (INV-7) |
| event_type | VARCHAR(30) | NO | - | - | CREATED/ENRICHED/DECAY_UPDATE/NEAR_MISS/SNAPPED/STALE/EXPIRED/COLD_ARCHIVED/BOOST_APPLIED |
| event_timestamp | TIMESTAMP(TZ) | NO | now() | DEFAULT & server_default | Event time |
| old_state | JSONB | YES | NULL | - | Previous state snapshot |
| new_state | JSONB | YES | NULL | - | New state snapshot |
| event_detail | JSONB | YES | NULL | - | Event metadata |

**Indexes:**

| Index Name | Columns | Type |
|------------|---------|------|
| ix_fh_fragment_time | (fragment_id, event_timestamp) | BTREE |
| ix_fh_tenant_time | (tenant_id, event_timestamp) | BTREE |

---

### Table: `snap_decision_record`
**Purpose:** Persisted snap evaluation record (Audit §7.1). Stores full scoring breakdown.

**Columns:**

| Column Name | Type | Nullable | Default | Constraints | Notes |
|-------------|------|----------|---------|-------------|-------|
| id | UUID | NO | uuid4() | PRIMARY KEY | Decision record ID |
| tenant_id | VARCHAR(100) | NO | - | - | Tenant isolation (INV-7) |
| new_fragment_id | UUID | NO | - | - | Fragment being evaluated |
| candidate_fragment_id | UUID | NO | - | - | Fragment being compared to |
| evaluated_at | TIMESTAMP(TZ) | NO | now() | DEFAULT & server_default | Evaluation time |
| failure_mode_profile | VARCHAR(50) | NO | - | - | Primary failure mode |
| component_scores | JSONB | NO | - | - | {semantic_sim, topological_prox, entity_overlap, operational_sim} |
| weights_used | JSONB | NO | - | - | Component weights applied |
| raw_composite | FLOAT | NO | - | - | Unmodified composite score |
| temporal_modifier | FLOAT | NO | - | - | Temporal adjustment factor |
| final_score | FLOAT | NO | - | - | Final weighted score |
| threshold_applied | FLOAT | NO | - | - | Threshold compared against |
| decision | VARCHAR(20) | NO | - | - | SNAP/NEAR_MISS/AFFINITY/NONE |
| multiple_comparisons_k | INTEGER | NO | 1 | DEFAULT '1' | Bonferroni k value |

**Indexes:**

| Index Name | Columns | Type |
|------------|---------|------|
| ix_sdr_tenant_time | (tenant_id, evaluated_at) | BTREE |
| ix_sdr_new_frag | (new_fragment_id) | BTREE |

---

### Table: `cluster_snapshot`
**Purpose:** Persisted cluster evaluation record (Audit §7.3). Captures cluster membership and scoring.

**Columns:**

| Column Name | Type | Nullable | Default | Constraints | Notes |
|-------------|------|----------|---------|-------------|-------|
| id | UUID | NO | uuid4() | PRIMARY KEY | Snapshot ID |
| tenant_id | VARCHAR(100) | NO | - | - | Tenant isolation (INV-7) |
| evaluated_at | TIMESTAMP(TZ) | NO | now() | DEFAULT & server_default | Evaluation time |
| member_fragment_ids | JSONB | NO | - | - | Array of fragment UUIDs |
| edges | JSONB | NO | - | - | Edge definitions |
| cluster_score | FLOAT | NO | - | - | Unadjusted cluster score |
| correlation_discount | FLOAT | NO | - | - | Correlation adjustment |
| adjusted_score | FLOAT | NO | - | - | Score after discount |
| threshold | FLOAT | NO | - | - | Threshold applied |
| decision | VARCHAR(20) | NO | - | - | SNAP/NO_SNAP |

**Indexes:**

| Index Name | Columns | Type |
|------------|---------|------|
| ix_cs_tenant_time | (tenant_id, evaluated_at) | BTREE |

---

## Shadow Topology (LLD §8)

### Table: `shadow_entity`
**Purpose:** PedkAI's private topology node

**Columns:**

| Column Name | Type | Nullable | Default | Constraints | Notes |
|-------------|------|----------|---------|-------------|-------|
| id | UUID | NO | uuid4() | PRIMARY KEY | Entity ID |
| tenant_id | VARCHAR(100) | NO | - | - | Tenant isolation (INV-7) |
| entity_identifier | VARCHAR(500) | NO | - | - | Unique entity name/identifier |
| entity_domain | VARCHAR(50) | YES | NULL | - | RAN/TRANSPORT/CORE/IP/VNF/SITE |
| origin | VARCHAR(30) | NO | CMDB_DECLARED | DEFAULT 'CMDB_DECLARED' | CMDB_DECLARED/PEDKAI_DISCOVERED/PEDKAI_CORRECTED |
| discovery_hypothesis_id | UUID | YES | NULL | - | Hypothesis that discovered it |
| first_seen | TIMESTAMP(TZ) | NO | now() | DEFAULT & server_default | First evidence |
| last_evidence | TIMESTAMP(TZ) | NO | now() | DEFAULT & server_default | Most recent evidence |
| attributes | JSONB | NO | {} | DEFAULT '{}' | Current attributes |
| cmdb_attributes | JSONB | NO | {} | DEFAULT '{}' | CMDB-exported attributes |
| enrichment_value | FLOAT | NO | 0.0 | DEFAULT '0.0' | Topology enrichment value |

**Indexes:**

| Index Name | Columns | Type |
|------------|---------|------|
| ix_shadow_entity_tenant_identifier | (tenant_id, entity_identifier) | UNIQUE |

---

### Table: `shadow_relationship`
**Purpose:** PedkAI's private topology edge

**Columns:**

| Column Name | Type | Nullable | Default | Constraints | Notes |
|-------------|------|----------|---------|-------------|-------|
| id | UUID | NO | uuid4() | PRIMARY KEY | Relationship ID |
| tenant_id | VARCHAR(100) | NO | - | - | Tenant isolation (INV-7) |
| from_entity_id | UUID | NO | - | FK → shadow_entity(id) | Source entity |
| to_entity_id | UUID | NO | - | FK → shadow_entity(id) | Target entity |
| relationship_type | VARCHAR(50) | NO | - | - | Edge label |
| origin | VARCHAR(30) | NO | CMDB_DECLARED | DEFAULT 'CMDB_DECLARED' | CMDB_DECLARED/PEDKAI_DISCOVERED/PEDKAI_CORRECTED |
| discovery_hypothesis_id | UUID | YES | NULL | - | Discovery hypothesis link |
| confidence | FLOAT | NO | 1.0 | DEFAULT '1.0' | Confidence score |
| discovered_at | TIMESTAMP(TZ) | NO | now() | DEFAULT & server_default | Discovery time |
| evidence_summary | JSONB | NO | {} | DEFAULT '{}' | Supporting evidence |
| exported_to_cmdb | BOOLEAN | NO | FALSE | DEFAULT 'false' | CMDB export flag |
| exported_at | TIMESTAMP(TZ) | YES | NULL | - | CMDB export time |
| cmdb_reference_tag | VARCHAR(255) | YES | NULL | - | CMDB identifier |

**Indexes:**

| Index Name | Columns | Type |
|------------|---------|------|
| ix_shadow_rel_from_tenant | (from_entity_id, tenant_id) | BTREE |
| ix_shadow_rel_to_tenant | (to_entity_id, tenant_id) | BTREE |

---

### Table: `cmdb_export_log`
**Purpose:** Audit trail for CMDB exports

**Columns:**

| Column Name | Type | Nullable | Default | Constraints | Notes |
|-------------|------|----------|---------|-------------|-------|
| id | UUID | NO | uuid4() | PRIMARY KEY | Log record ID |
| tenant_id | VARCHAR(100) | NO | - | - | Tenant isolation (INV-7) |
| relationship_id | UUID | YES | NULL | FK → shadow_relationship(id) | Exported relationship |
| entity_id | UUID | YES | NULL | FK → shadow_entity(id) | Exported entity |
| export_type | VARCHAR(30) | NO | - | - | ENTITY/RELATIONSHIP |
| exported_at | TIMESTAMP(TZ) | NO | now() | DEFAULT & server_default | Export time |
| exported_payload | JSONB | NO | {} | DEFAULT '{}' | Data sent to CMDB |
| retained_payload | JSONB | NO | {} | DEFAULT '{}' | Retained private data |
| cmdb_reference_tag | VARCHAR(255) | YES | NULL | - | CMDB reference |

---

## Value Attribution (LLD §13)

### Table: `discovery_ledger`
**Purpose:** Permanent record of every PedkAI discovery

**Columns:**

| Column Name | Type | Nullable | Default | Constraints | Notes |
|-------------|------|----------|---------|-------------|-------|
| id | UUID | NO | uuid4() | PRIMARY KEY | Ledger entry ID |
| tenant_id | VARCHAR(100) | NO | - | Index | Tenant isolation (INV-7) |
| hypothesis_id | UUID | YES | NULL | - | Decision hypothesis link |
| discovery_type | VARCHAR(50) | NO | - | - | DARK_NODE/DARK_EDGE/PHANTOM_CI/IDENTITY_MUTATION/DARK_ATTRIBUTE |
| discovered_entities | JSONB | NO | [] | DEFAULT '[]' | Discovered entity UUIDs |
| discovered_relationships | JSONB | NO | [] | DEFAULT '[]' | Discovered relationship UUIDs |
| cmdb_reference_tag | VARCHAR(255) | YES | NULL | - | CMDB export reference |
| discovered_at | TIMESTAMP(TZ) | NO | now() | DEFAULT & server_default | Discovery time |
| cmdb_exported_at | TIMESTAMP(TZ) | YES | NULL | - | CMDB export time |
| discovery_confidence | FLOAT | NO | 0.0 | DEFAULT '0.0' | Confidence metric |
| status | VARCHAR(20) | NO | ACTIVE | DEFAULT 'ACTIVE' | ACTIVE/SUPERSEDED/INVALIDATED |

**Indexes:**

| Index Name | Columns | Type | Options |
|------------|---------|------|---------|
| ix_discovery_ledger_tenant | (tenant_id) | BTREE | - |
| ix_discovery_entities_gin | (discovered_entities) | GIN | jsonb_path_ops |

---

### Table: `value_event`
**Purpose:** Individual value realization event

**Columns:**

| Column Name | Type | Nullable | Default | Constraints | Notes |
|-------------|------|----------|---------|-------------|-------|
| id | UUID | NO | uuid4() | PRIMARY KEY | Event ID |
| tenant_id | VARCHAR(100) | NO | - | Index | Tenant isolation (INV-7) |
| ledger_entry_id | UUID | NO | - | Index, FK → discovery_ledger(id) | Parent discovery |
| event_type | VARCHAR(50) | NO | - | - | INCIDENT_RESOLUTION/MTTR_REDUCTION/LICENCE_SAVING/OUTAGE_PREVENTION/DARK_GRAPH_REDUCTION |
| event_at | TIMESTAMP(TZ) | NO | now() | DEFAULT & server_default | Event time |
| event_detail | JSONB | NO | {} | DEFAULT '{}' | Event metadata |
| attributed_value_hours | FLOAT | YES | NULL | - | MTTR hours saved |
| attributed_value_currency | FLOAT | YES | NULL | - | Monetary value |
| attribution_rationale | TEXT | YES | NULL | - | Explanation |

**Indexes:**

| Index Name | Columns | Type |
|------------|---------|------|
| ix_value_event_ledger | (ledger_entry_id) | BTREE |
| ix_value_event_tenant | (tenant_id) | BTREE |

---

## Cold Storage (Phase 5)

### Table: `cold_fragment`
**Purpose:** pgvector ANN cold storage for expired fragments

**Columns:**

| Column Name | Type | Nullable | Default | Constraints | Notes |
|-------------|------|----------|---------|-------------|-------|
| id | UUID | NO | uuid4() | PRIMARY KEY | Cold storage record ID |
| tenant_id | VARCHAR(100) | NO | - | - | Tenant isolation (INV-7) |
| original_fragment_id | UUID | NO | - | - | Original fragment UUID |
| source_type | VARCHAR(50) | NO | - | - | Source type at archival |
| raw_content_summary | TEXT | YES | NULL | - | Summarized content |
| extracted_entities | JSONB | NO | [] | DEFAULT '[]' | Extracted entities |
| failure_mode_tags | JSONB | NO | [] | DEFAULT '[]' | Failure modes |
| enriched_embedding | Vector(1536) | YES | NULL | - | Enriched embedding |
| event_timestamp | TIMESTAMP(TZ) | YES | NULL | - | Original event time |
| archived_at | TIMESTAMP(TZ) | NO | now() | DEFAULT & server_default | Archive time |
| original_created_at | TIMESTAMP(TZ) | YES | NULL | - | Original creation |
| original_decay_score | FLOAT | NO | 0.0 | DEFAULT '0.0' | Decay score at archive |
| snap_status_at_archive | VARCHAR(20) | NO | EXPIRED | DEFAULT 'EXPIRED' | Status at archival |

**Indexes:**

| Index Name | Columns | Type | Options |
|------------|---------|------|---------|
| ix_cold_frag_tenant | (tenant_id) | BTREE | - |
| ix_cold_frag_original | (original_fragment_id) | BTREE | - |
| ix_cold_frag_embedding_ann | (enriched_embedding) | IVFFLAT | vector_cosine_ops, lists=100 |

---

## Key Invariants

| Invariant | Description |
|-----------|-------------|
| INV-1 | Fragment lifecycle via SnapStatus enum (deterministic state machine) |
| INV-5 | SNAPPED status is terminal for automated processes |
| INV-6 | raw_content size bounded to 64KB; max_lifetime_days hard cap |
| INV-7 | tenant_id on every table, every index (tenant isolation) |
| INV-9 | MAX_EDGES_PER_FRAGMENT bounded (enforced at application layer) |
| INV-10 | fragment_history and snap_decision_record are append-only |
| INV-11 | embedding_mask: 4-element JSONB validity mask [semantic_valid, topo_valid, temporal_valid, operational_valid] |

---

## Size Constraints

| Constraint | Value | Enforced |
|-----------|-------|----------|
| MAX_RAW_CONTENT_BYTES | 65536 (64KB) | Application layer |
| MAX_EDGES_PER_FRAGMENT | Application-defined | Application layer |
| max_lifetime_days default | 730 (2 years) | Database default |

---

## Extensions Required

- `pgvector` — for Vector(n) column support and embedding operations
- `PostgreSQL 13+` — for JSONB and array operations

---

## Remediation Notes (Post-Forensic Audit)

1. **§3.1 Split-Brain Elimination:** Unified fragment model (single canonical source)
2. **§5.1 GIN Index Optimization:** Added GIN indexes on failure_mode_tags and extracted_entities
3. **§7.1-7.3 Provenance:** Added fragment_history, snap_decision_record, cluster_snapshot tables
4. **§9.2 Tenant Isolation:** All uniqueness constraints now tenant-scoped (accumulation_edge, shadow_entity)
5. **§11 Embedding Validity:** Added embedding_mask column to track which sub-vectors are valid
6. **Decay Index:** Changed from snap_status = 'ABEYANCE' to snap_status IN ('ACTIVE', 'NEAR_MISS')
7. **Default Status:** Changed from ABEYANCE → INGESTED (state machine clarity)

---

Generated: 2026-03-16 | Task T0.6
