# Abeyance Memory Alembic Migrations

## Migration History

All Alembic migration files related to the Abeyance Memory subsystem, located in:
`/Users/himanshu/Projects/Pedkai/backend/alembic/versions/`

---

## Migration: 008_abeyance_decay

**Revision ID:** `008_abeyance_decay`
**Revises:** `007_add_hits_tracking`
**File Location:** `/Users/himanshu/Projects/Pedkai/backend/alembic/versions/008_abeyance_decay.py`
**Create Date:** 2026-03-10 00:00:00.000000

### Purpose
Add decay scoring columns to decision_traces table for initial abeyance functionality (pre-refactoring into dedicated tables).

### Tables Affected
- `decision_traces` (modified)

### Changes: Upgrade

**Columns Added:**

1. **decay_score** (FLOAT)
   - Type: Float
   - Nullable: NO
   - Default: '1.0'
   - Purpose: Exponential decay value, starts at 1.0, approaches 0 over time
   - Usage: Tracks fragment relevance decay

2. **corroboration_count** (INTEGER)
   - Type: Integer
   - Nullable: NO
   - Default: '0'
   - Purpose: How many times this fragment has been corroborated by other evidence
   - Usage: Strength metric for fragment validity

3. **abeyance_status** (VARCHAR(20))
   - Type: String(20)
   - Nullable: NO
   - Default: 'ACTIVE'
   - Purpose: Lifecycle state machine status
   - Valid values: ACTIVE, STALE, (others defined in later migrations)
   - Note: Named 'abeyance_status' to avoid clash with existing 'status' field (incident lifecycle)

### Changes: Downgrade
- Removes: abeyance_status
- Removes: corroboration_count
- Removes: decay_score

### Historical Context
This is the initial abeyance decay implementation, added before the full Abeyance Memory subsystem refactoring. These columns are now **deprecated** in favor of the unified `abeyance_fragment` table with dedicated columns.

---

## Migration: 010_abeyance_memory_subsystem

**Revision ID:** `010_abeyance_memory_subsystem`
**Revises:** `009_create_customers_tables`
**File Location:** `/Users/himanshu/Projects/Pedkai/backend/alembic/versions/010_abeyance_memory_subsystem.py`
**Create Date:** 2026-03-15 00:00:00.000000

### Purpose
Create the complete Abeyance Memory schema as specified in ABEYANCE_MEMORY_LLD.md §14. Implements core fragment storage, entity references, accumulation graph, shadow topology, CMDB export audit trail, and value attribution framework.

### Tables Created

#### 1. abeyance_fragment (LLD §5 Fragment Model)
**Purpose:** Core fragment storage — unified canonical model

**Columns:**
- id (UUID, PK)
- tenant_id (VARCHAR(100), required)
- source_type (VARCHAR(50), required)
- raw_content (TEXT, optional)
- extracted_entities (JSONB, default: [])
- topological_neighbourhood (JSONB, default: {})
- operational_fingerprint (JSONB, default: {})
- failure_mode_tags (JSONB, default: [])
- temporal_context (JSONB, default: {})
- enriched_embedding (vector(1536), optional)
- raw_embedding (vector(768), optional)
- event_timestamp (TIMESTAMP(TZ), optional)
- ingestion_timestamp (TIMESTAMP(TZ), default: now())
- base_relevance (FLOAT, default: 1.0)
- current_decay_score (FLOAT, default: 1.0)
- near_miss_count (INTEGER, default: 0)
- snap_status (VARCHAR(20), default: 'ABEYANCE')
- snapped_hypothesis_id (UUID, optional)
- source_ref (VARCHAR(500), optional)
- source_engineer_id (VARCHAR(255), optional)
- created_at (TIMESTAMP(TZ), default: now())
- updated_at (TIMESTAMP(TZ), optional)

**Indexes Created:**
- ix_abeyance_fragment_tenant_id (tenant_id)
- ix_abeyance_fragment_tenant_status (tenant_id, snap_status)
- ix_abeyance_fragment_decay (current_decay_score) WHERE snap_status = 'ABEYANCE'
- ix_abeyance_fragment_failure_modes (failure_mode_tags) USING GIN jsonb_path_ops
- ix_abeyance_fragment_entities (extracted_entities) USING GIN jsonb_path_ops

#### 2. fragment_entity_ref (LLD §5 Entity Junction)
**Purpose:** Link fragments to referenced network entities with topological distance

**Columns:**
- id (UUID, PK)
- fragment_id (UUID, FK → abeyance_fragment(id), CASCADE)
- entity_id (UUID, optional)
- entity_identifier (VARCHAR(500), required)
- entity_domain (VARCHAR(50), optional)
- topological_distance (INTEGER, default: 0)
- tenant_id (VARCHAR(100), required)

**Indexes Created:**
- ix_fer_fragment_id (fragment_id)
- ix_fer_entity_id (entity_id, fragment_id)
- ix_fer_entity_identifier (entity_identifier, tenant_id)

#### 3. accumulation_edge (LLD §10 Accumulation Graph)
**Purpose:** Weak affinity links between fragments

**Columns:**
- id (UUID, PK)
- tenant_id (VARCHAR(100), required)
- fragment_a_id (UUID, FK → abeyance_fragment(id), required)
- fragment_b_id (UUID, FK → abeyance_fragment(id), required)
- affinity_score (FLOAT, required)
- strongest_failure_mode (VARCHAR(50), optional)
- created_at (TIMESTAMP(TZ), default: now())
- last_updated (TIMESTAMP(TZ), default: now())

**Indexes Created:**
- ix_accum_edge_fragment_a (fragment_a_id)
- ix_accum_edge_fragment_b (fragment_b_id)
- ix_accum_edge_pair (fragment_a_id, fragment_b_id) UNIQUE

#### 4. shadow_entity (LLD §8 Shadow Topology)
**Purpose:** PedkAI's private topology node

**Columns:**
- id (UUID, PK)
- tenant_id (VARCHAR(100), required)
- entity_identifier (VARCHAR(500), required)
- entity_domain (VARCHAR(50), optional)
- origin (VARCHAR(30), default: 'CMDB_DECLARED')
- discovery_hypothesis_id (UUID, optional)
- first_seen (TIMESTAMP(TZ), default: now())
- last_evidence (TIMESTAMP(TZ), default: now())
- attributes (JSONB, default: {})
- cmdb_attributes (JSONB, default: {})
- enrichment_value (FLOAT, default: 0.0)

**Indexes Created:**
- ix_shadow_entity_tenant_identifier (tenant_id, entity_identifier) UNIQUE

#### 5. shadow_relationship (LLD §8 Shadow Topology)
**Purpose:** PedkAI's private topology edge

**Columns:**
- id (UUID, PK)
- tenant_id (VARCHAR(100), required)
- from_entity_id (UUID, FK → shadow_entity(id), required)
- to_entity_id (UUID, FK → shadow_entity(id), required)
- relationship_type (VARCHAR(50), required)
- origin (VARCHAR(30), default: 'CMDB_DECLARED')
- discovery_hypothesis_id (UUID, optional)
- confidence (FLOAT, default: 1.0)
- discovered_at (TIMESTAMP(TZ), default: now())
- evidence_summary (JSONB, default: {})
- exported_to_cmdb (BOOLEAN, default: FALSE)
- exported_at (TIMESTAMP(TZ), optional)
- cmdb_reference_tag (VARCHAR(255), optional)

**Indexes Created:**
- ix_shadow_rel_from (from_entity_id, tenant_id)
- ix_shadow_rel_to (to_entity_id, tenant_id)

#### 6. cmdb_export_log (LLD §8 CMDB Export Audit)
**Purpose:** Audit trail for CMDB exports

**Columns:**
- id (UUID, PK)
- tenant_id (VARCHAR(100), required)
- relationship_id (UUID, optional, FK → shadow_relationship(id))
- entity_id (UUID, optional, FK → shadow_entity(id))
- export_type (VARCHAR(30), required)
- exported_at (TIMESTAMP(TZ), default: now())
- exported_payload (JSONB, default: {})
- retained_payload (JSONB, default: {})
- cmdb_reference_tag (VARCHAR(255), optional)

#### 7. discovery_ledger (LLD §13 Value Attribution)
**Purpose:** Permanent record of PedkAI discoveries

**Columns:**
- id (UUID, PK)
- tenant_id (VARCHAR(100), required, indexed)
- hypothesis_id (UUID, optional)
- discovery_type (VARCHAR(50), required)
- discovered_entities (JSONB, default: [])
- discovered_relationships (JSONB, default: [])
- cmdb_reference_tag (VARCHAR(255), optional)
- discovered_at (TIMESTAMP(TZ), default: now())
- cmdb_exported_at (TIMESTAMP(TZ), optional)
- discovery_confidence (FLOAT, default: 0.0)
- status (VARCHAR(20), default: 'ACTIVE')

**Indexes Created:**
- ix_discovery_ledger_tenant (tenant_id)
- ix_discovery_entities (discovered_entities) USING GIN jsonb_path_ops

#### 8. value_event (LLD §13 Value Attribution)
**Purpose:** Individual value realization events

**Columns:**
- id (UUID, PK)
- tenant_id (VARCHAR(100), required, indexed)
- ledger_entry_id (UUID, required, indexed, FK → discovery_ledger(id))
- event_type (VARCHAR(50), required)
- event_at (TIMESTAMP(TZ), default: now())
- event_detail (JSONB, default: {})
- attributed_value_hours (FLOAT, optional)
- attributed_value_currency (FLOAT, optional)
- attribution_rationale (TEXT, optional)

**Indexes Created:**
- ix_value_event_ledger (ledger_entry_id)
- ix_value_event_tenant (tenant_id)

### Prerequisites
- pgvector extension (created if not exists)

### Changes: Downgrade
Drops all Abeyance Memory tables in reverse dependency order:
1. value_event
2. discovery_ledger
3. cmdb_export_log
4. shadow_relationship
5. shadow_entity
6. accumulation_edge
7. fragment_entity_ref
8. abeyance_fragment

---

## Migration: 011_abeyance_provenance_tables

**Revision ID:** `011_abeyance_provenance_tables`
**Revises:** `010_abeyance_memory_subsystem`
**File Location:** `/Users/himanshu/Projects/Pedkai/backend/alembic/versions/011_abeyance_provenance_tables.py`
**Create Date:** 2026-03-15 12:00:00.000000

### Purpose
Add provenance tables and remediation columns per Forensic Audit findings. Implements append-only history, snap decision records, cluster snapshots, embedding validity tracking, deduplication, cold storage, and tenant-scoped uniqueness.

### Tables Created

#### 1. fragment_history (INV-10: Append-Only)
**Purpose:** Append-only fragment state change log (Audit §7.2)

**Columns:**
- id (UUID, PK)
- fragment_id (UUID, required)
- tenant_id (VARCHAR(100), required)
- event_type (VARCHAR(30), required)
  - Valid values: CREATED, ENRICHED, DECAY_UPDATE, NEAR_MISS, SNAPPED, STALE, EXPIRED, COLD_ARCHIVED, BOOST_APPLIED
- event_timestamp (TIMESTAMP(TZ), required, default: now())
- old_state (JSONB, optional)
- new_state (JSONB, optional)
- event_detail (JSONB, optional)

**Indexes Created:**
- ix_fh_fragment_time (fragment_id, event_timestamp)
- ix_fh_tenant_time (tenant_id, event_timestamp)

**Constraints:**
- Append-only enforcement: Updates/deletes prohibited via DB trigger + application guard

#### 2. snap_decision_record (Audit §7.1)
**Purpose:** Persisted snap evaluation record with full scoring breakdown

**Columns:**
- id (UUID, PK)
- tenant_id (VARCHAR(100), required)
- new_fragment_id (UUID, required)
- candidate_fragment_id (UUID, required)
- evaluated_at (TIMESTAMP(TZ), required, default: now())
- failure_mode_profile (VARCHAR(50), required)
- component_scores (JSONB, required)
  - Contains: {semantic_sim, topological_prox, entity_overlap, operational_sim}
- weights_used (JSONB, required)
- raw_composite (FLOAT, required)
- temporal_modifier (FLOAT, required)
- final_score (FLOAT, required)
- threshold_applied (FLOAT, required)
- decision (VARCHAR(20), required) — SNAP, NEAR_MISS, AFFINITY, NONE
- multiple_comparisons_k (INTEGER, default: 1)

**Indexes Created:**
- ix_sdr_tenant_time (tenant_id, evaluated_at)
- ix_sdr_new_frag (new_fragment_id)

#### 3. cluster_snapshot (Audit §7.3)
**Purpose:** Persisted cluster evaluation record with membership and scoring

**Columns:**
- id (UUID, PK)
- tenant_id (VARCHAR(100), required)
- evaluated_at (TIMESTAMP(TZ), required, default: now())
- member_fragment_ids (JSONB, required)
- edges (JSONB, required)
- cluster_score (FLOAT, required)
- correlation_discount (FLOAT, required)
- adjusted_score (FLOAT, required)
- threshold (FLOAT, required)
- decision (VARCHAR(20), required) — SNAP, NO_SNAP

**Indexes Created:**
- ix_cs_tenant_time (tenant_id, evaluated_at)

#### 4. cold_fragment (Phase 5: pgvector ANN Cold Storage)
**Purpose:** Cold storage for expired fragments with ANN index for similarity search

**Columns:**
- id (UUID, PK)
- tenant_id (VARCHAR(100), required)
- original_fragment_id (UUID, required)
- source_type (VARCHAR(50), required)
- raw_content_summary (TEXT, optional)
- extracted_entities (JSONB, default: [])
- failure_mode_tags (JSONB, default: [])
- enriched_embedding (vector(1536), optional)
- event_timestamp (TIMESTAMP(TZ), optional)
- archived_at (TIMESTAMP(TZ), required, default: now())
- original_created_at (TIMESTAMP(TZ), optional)
- original_decay_score (FLOAT, default: 0.0)
- snap_status_at_archive (VARCHAR(20), default: 'EXPIRED')

**Indexes Created:**
- ix_cold_frag_tenant (tenant_id)
- ix_cold_frag_original (original_fragment_id)
- ix_cold_frag_embedding_ann (enriched_embedding) USING IVFFLAT vector_cosine_ops, lists=100
  - Purpose: Approximate nearest neighbor search for cosine similarity

### Columns Added to Existing Tables

#### abeyance_fragment Modifications

1. **embedding_mask** (JSONB)
   - Type: JSONB
   - Default: [true, false, true, false]
   - Purpose: Embedding validity mask (INV-11)
   - Format: 4-element boolean array [semantic_valid, topo_valid, temporal_valid, operational_valid]

2. **dedup_key** (VARCHAR(500))
   - Type: String(500)
   - Nullable: YES
   - Purpose: Deduplication key (Phase 7, §7.3)

3. **max_lifetime_days** (INTEGER)
   - Type: Integer
   - Default: 730 (2 years)
   - Purpose: Hard lifetime bound (INV-6)

4. **snap_status Default Changed**
   - Old: 'ABEYANCE'
   - New: 'INGESTED'
   - Purpose: Clearer state machine semantics

#### Indexes Added to abeyance_fragment

- ix_abeyance_fragment_tenant_created (tenant_id, created_at)
- ix_abeyance_fragment_tenant_decay (tenant_id, current_decay_score) WHERE snap_status IN ('ACTIVE', 'NEAR_MISS')
  - Replaced: ix_abeyance_fragment_decay

#### Uniqueness Constraints Added

- uq_fragment_dedup (tenant_id, dedup_key) WHERE dedup_key IS NOT NULL
  - Purpose: Tenant-scoped deduplication (Audit §9.2)

#### accumulation_edge Modifications

**Index Changes (Audit §9.2 — Tenant-Scoped Uniqueness):**
- Dropped: ix_accum_edge_pair (old, non-tenant-scoped)
- Dropped: ix_accum_edge_fragment_a, ix_accum_edge_fragment_b
- Created: ix_accum_edge_pair (tenant_id, fragment_a_id, fragment_b_id) UNIQUE
- Created: ix_accum_edge_frag_a (tenant_id, fragment_a_id)
- Created: ix_accum_edge_frag_b (tenant_id, fragment_b_id)

### Changes: Downgrade
Reverses all additions in proper order:
1. Restores old decay index
2. Drops tenant-scoped accumulation_edge indexes
3. Recreates old non-tenant-scoped indexes
4. Removes tenant-created index
5. Removes dedup unique constraint
6. Drops new columns: max_lifetime_days, dedup_key, embedding_mask
7. Restores snap_status default to 'ABEYANCE'
8. Drops tables: cold_fragment, cluster_snapshot, snap_decision_record, fragment_history

---

## Migration Chain Summary

| Revision | Revises | Type | Key Tables | Status |
|----------|---------|------|-----------|--------|
| 008 | 007 | Deprecated | decision_traces (add cols) | Replaced by 010/011 |
| 010 | 009 | Core Schema | 8 tables created | Active |
| 011 | 010 | Provenance + Remediation | 4 tables + 3 columns | Active |

### Current Active Schema State
After running migration 011 (`up`), the database has:
- **Core Tables:** abeyance_fragment, fragment_entity_ref, accumulation_edge
- **Shadow Topology:** shadow_entity, shadow_relationship, cmdb_export_log
- **Value Attribution:** discovery_ledger, value_event
- **Provenance:** fragment_history, snap_decision_record, cluster_snapshot
- **Cold Storage:** cold_fragment
- **Total:** 12 tables, all tenant-isolated, with comprehensive indexing

### Remediation Lineage
- **010:** Initial schema per LLD §14
- **011:** Forensic Audit remediation per:
  - Audit §3.1 — Split-brain elimination
  - Audit §4.1, §5.3 — Cluster scoring improvements
  - Audit §5.1 — GIN indexes
  - Audit §7.1–7.3 — Provenance tables
  - Audit §9.2 — Tenant-scoped uniqueness
  - Audit §11 — Embedding validity mask

---

Generated: 2026-03-16 | Task T0.6
