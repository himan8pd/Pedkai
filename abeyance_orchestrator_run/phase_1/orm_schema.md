# Abeyance Memory v3.0 — ORM Schema (Phase 1: T1.2)

## Document Scope

Redesigned ORM schema for the four-column embedding architecture. This document specifies
the complete table definitions for `abeyance_fragment` (ActiveFragmentORM) and
`cold_fragment` (ColdFragmentORM), plus the updated `snap_decision_record`.

All other tables (`fragment_entity_ref`, `accumulation_edge`, `fragment_history`,
`cluster_snapshot`, `shadow_entity`, `shadow_relationship`, `cmdb_export_log`,
`discovery_ledger`, `value_event`) are UNCHANGED from v2.0 and not repeated here.

Parent reference: `/Users/himanshu/Projects/Pedkai/abeyance_orchestrator_run/research/orm_schema.md`

---

## Breaking Changes from v2.0

| Removed Column | Table(s) | Reason |
|----------------|----------|--------|
| `enriched_embedding` Vector(1536) | `abeyance_fragment`, `cold_fragment` | Replaced by four dedicated embedding columns |
| `embedding_mask` JSONB | `abeyance_fragment` | Replaced by three per-dimension boolean masks |
| `raw_embedding` Vector(768) | `abeyance_fragment` | Superseded; raw content is now embedded directly into `emb_semantic` via T-VEC |

---

## 1. ActiveFragmentORM — Table: `abeyance_fragment`

**Purpose:** Core fragment storage. Unified canonical model with four-column embedding architecture.

### 1.1 Columns

| Column Name | Type | Nullable | Default | Constraints | Notes |
|---|---|---|---|---|---|
| **-- Identity --** | | | | | |
| id | UUID | NO | uuid4() | PRIMARY KEY | Fragment ID |
| tenant_id | VARCHAR(100) | NO | - | NOT NULL | Tenant isolation (INV-7) |
| **-- Source --** | | | | | |
| source_type | VARCHAR(50) | NO | - | NOT NULL | Fragment source (ALARM, LOG, METRIC, MANUAL, SYNTHETIC) |
| source_ref | VARCHAR(500) | YES | NULL | - | Reference to source system |
| source_engineer_id | VARCHAR(255) | YES | NULL | - | Engineer identifier |
| **-- Content --** | | | | | |
| raw_content | TEXT | YES | NULL | - | Bounded by 64KB at application layer (INV-6) |
| **-- Structured Metadata --** | | | | | |
| extracted_entities | JSONB | NO | '[]'::jsonb | NOT NULL, DEFAULT | Entity extraction results |
| topological_neighbourhood | JSONB | NO | '{}'::jsonb | NOT NULL, DEFAULT | Shadow Topology neighbourhood snapshot (k-hop subgraph) |
| operational_fingerprint | JSONB | NO | '{}'::jsonb | NOT NULL, DEFAULT | Operational state: failure modes, KPIs, alarm patterns |
| failure_mode_tags | JSONB | NO | '[]'::jsonb | NOT NULL, DEFAULT | Failure classification labels |
| temporal_context | JSONB | NO | '{}'::jsonb | NOT NULL, DEFAULT | Temporal features: hour_of_day, day_of_week, recurrence_period, etc. |
| **-- Embedding Columns (v3.0) --** | | | | | |
| emb_semantic | Vector(1536) | YES | NULL | - | T-VEC embedding of raw_content + extracted_entities. NULL if T-VEC call fails. |
| emb_topological | Vector(1536) | YES | NULL | - | T-VEC embedding of topological_neighbourhood serialization. NULL if T-VEC call fails. |
| emb_temporal | Vector(256) | YES | NULL | - | Sinusoidal positional encoding of temporal_context. Pure math, no LLM. See Section 4. |
| emb_operational | Vector(1536) | YES | NULL | - | T-VEC embedding of failure_mode_tags + operational_fingerprint. NULL if T-VEC call fails. |
| **-- Embedding Validity Masks (v3.0) --** | | | | | |
| mask_semantic | BOOLEAN | NO | FALSE | NOT NULL, DEFAULT | TRUE iff emb_semantic was successfully generated. FALSE when NULL or stale. |
| mask_topological | BOOLEAN | NO | FALSE | NOT NULL, DEFAULT | TRUE iff emb_topological was successfully generated. FALSE when NULL or stale. |
| mask_operational | BOOLEAN | NO | FALSE | NOT NULL, DEFAULT | TRUE iff emb_operational was successfully generated. FALSE when NULL or stale. |
| **-- Timestamps --** | | | | | |
| event_timestamp | TIMESTAMP WITH TIME ZONE | YES | NULL | - | Evidence timestamp (when the source event occurred) |
| ingestion_timestamp | TIMESTAMP WITH TIME ZONE | NO | now() | NOT NULL, DEFAULT, server_default | Ingestion time |
| created_at | TIMESTAMP WITH TIME ZONE | NO | now() | NOT NULL, DEFAULT, server_default | Record creation |
| updated_at | TIMESTAMP WITH TIME ZONE | YES | NULL | - | Last update time (set by enrichment pipeline) |
| **-- Scoring --** | | | | | |
| base_relevance | FLOAT | NO | 1.0 | NOT NULL, DEFAULT | Initial relevance score (LLD 11) |
| current_decay_score | FLOAT | NO | 1.0 | NOT NULL, DEFAULT | Exponential decay value; recomputed on sweep |
| near_miss_count | INTEGER | NO | 0 | NOT NULL, DEFAULT | Near-miss counter (boosted on close snap failures) |
| **-- Lifecycle --** | | | | | |
| snap_status | VARCHAR(20) | NO | 'INGESTED' | NOT NULL, DEFAULT | Lifecycle state; see state machine below |
| snapped_hypothesis_id | UUID | YES | NULL | - | Hypothesis UUID when snap_status = SNAPPED |
| max_lifetime_days | INTEGER | NO | 730 | NOT NULL, DEFAULT | Hard lifetime cap in days (INV-6) |
| **-- Deduplication --** | | | | | |
| dedup_key | VARCHAR(500) | YES | NULL | - | Deduplication key (application-generated hash) |

### 1.2 Indexes

| Index Name | Columns | Type | Where Clause | Options |
|---|---|---|---|---|
| ix_abeyance_fragment_tenant_status | (tenant_id, snap_status) | BTREE | - | - |
| ix_abeyance_fragment_tenant_created | (tenant_id, created_at) | BTREE | - | - |
| ix_abeyance_fragment_tenant_decay | (tenant_id, current_decay_score) | BTREE | snap_status IN ('ACTIVE', 'NEAR_MISS') | - |
| ix_abeyance_fragment_failure_modes | (failure_mode_tags) | GIN | - | jsonb_path_ops |
| ix_abeyance_fragment_entities | (extracted_entities) | GIN | - | jsonb_path_ops |
| uq_fragment_dedup | (tenant_id, dedup_key) | UNIQUE | dedup_key IS NOT NULL | - |

**No ANN indexes on `abeyance_fragment`**: Active fragments are searched via exact distance
(`<=>` operator) because the active set is small (typically <50K per tenant). ANN indexes are
reserved for cold storage where the corpus is orders of magnitude larger.

### 1.3 State Machine (unchanged from v2.0)

```
INGESTED --> ACTIVE --> {NEAR_MISS, SNAPPED, STALE}
NEAR_MISS --> {SNAPPED, ACTIVE, STALE}
STALE --> EXPIRED
EXPIRED --> COLD
SNAPPED --> (terminal)
COLD --> (terminal)
```

### 1.4 Embedding Validity Rules

| Column | Generator | On Failure | mask Column |
|---|---|---|---|
| emb_semantic | T-VEC(raw_content + extracted_entities) | SET NULL | mask_semantic = FALSE |
| emb_topological | T-VEC(topological_neighbourhood) | SET NULL | mask_topological = FALSE |
| emb_temporal | sinusoidal_encode(temporal_context) | Always succeeds (pure math) | No mask column (always valid) |
| emb_operational | T-VEC(failure_mode_tags + operational_fingerprint) | SET NULL | mask_operational = FALSE |

**Critical rules:**
1. If a T-VEC call fails, the corresponding column MUST be set to NULL and the mask to FALSE.
2. Zero-vector fill is PROHIBITED. A NULL embedding is semantically distinct from a zero vector (zero has cosine similarity properties that would corrupt scoring).
3. Hash-based fallback embeddings are PROHIBITED. If T-VEC is unavailable, the column stays NULL.
4. `emb_temporal` has no mask column because it is generated via deterministic sinusoidal encoding and always succeeds. If `temporal_context` is empty (`{}`), the encoding produces a valid zero-activity temporal vector.
5. When a mask is FALSE, the snap scorer MUST exclude that dimension from the composite score and re-normalize weights across the remaining valid dimensions.

### 1.5 CHECK Constraints

```sql
-- Mask coherence: if embedding is NULL, mask must be FALSE
ALTER TABLE abeyance_fragment
  ADD CONSTRAINT chk_mask_semantic_coherence
    CHECK (emb_semantic IS NOT NULL OR mask_semantic = FALSE);

ALTER TABLE abeyance_fragment
  ADD CONSTRAINT chk_mask_topological_coherence
    CHECK (emb_topological IS NOT NULL OR mask_topological = FALSE);

ALTER TABLE abeyance_fragment
  ADD CONSTRAINT chk_mask_operational_coherence
    CHECK (emb_operational IS NOT NULL OR mask_operational = FALSE);

-- Note: the converse (mask=TRUE implies NOT NULL) is also enforced:
-- if mask is TRUE but embedding is NULL, the above CHECK fails.
-- However, an embedding can be NOT NULL with mask=FALSE (stale embedding pending re-enrichment).
```

---

## 2. ColdFragmentORM — Table: `cold_fragment`

**Purpose:** pgvector ANN cold storage for expired/archived fragments. Optimized for similarity search over large historical corpus.

### 2.1 Columns

| Column Name | Type | Nullable | Default | Constraints | Notes |
|---|---|---|---|---|---|
| **-- Identity --** | | | | | |
| id | UUID | NO | uuid4() | PRIMARY KEY | Cold storage record ID |
| tenant_id | VARCHAR(100) | NO | - | NOT NULL | Tenant isolation (INV-7) |
| original_fragment_id | UUID | NO | - | NOT NULL | Original fragment UUID from `abeyance_fragment` |
| **-- Content --** | | | | | |
| source_type | VARCHAR(50) | NO | - | NOT NULL | Source type at time of archival |
| raw_content_summary | TEXT | YES | NULL | - | Summarized content (may be truncated from original) |
| extracted_entities | JSONB | NO | '[]'::jsonb | NOT NULL, DEFAULT | Extracted entities (copied from active) |
| failure_mode_tags | JSONB | NO | '[]'::jsonb | NOT NULL, DEFAULT | Failure modes (copied from active) |
| topological_neighbourhood | JSONB | NO | '{}'::jsonb | NOT NULL, DEFAULT | Topology context (copied from active) |
| operational_fingerprint | JSONB | NO | '{}'::jsonb | NOT NULL, DEFAULT | Operational state (copied from active) |
| temporal_context | JSONB | NO | '{}'::jsonb | NOT NULL, DEFAULT | Temporal features (copied from active) |
| **-- Embedding Columns (v3.0) --** | | | | | |
| emb_semantic | Vector(1536) | YES | NULL | - | Copied from active fragment at archival time |
| emb_topological | Vector(1536) | YES | NULL | - | Copied from active fragment at archival time |
| emb_temporal | Vector(256) | YES | NULL | - | Copied from active fragment at archival time |
| emb_operational | Vector(1536) | YES | NULL | - | Copied from active fragment at archival time |
| **-- Embedding Validity Masks (v3.0) --** | | | | | |
| mask_semantic | BOOLEAN | NO | FALSE | NOT NULL, DEFAULT | Copied from active fragment |
| mask_topological | BOOLEAN | NO | FALSE | NOT NULL, DEFAULT | Copied from active fragment |
| mask_operational | BOOLEAN | NO | FALSE | NOT NULL, DEFAULT | Copied from active fragment |
| **-- Timestamps --** | | | | | |
| event_timestamp | TIMESTAMP WITH TIME ZONE | YES | NULL | - | Original event time |
| archived_at | TIMESTAMP WITH TIME ZONE | NO | now() | NOT NULL, DEFAULT, server_default | Archive time |
| original_created_at | TIMESTAMP WITH TIME ZONE | YES | NULL | - | Original creation time |
| **-- Archival Metadata --** | | | | | |
| original_decay_score | FLOAT | NO | 0.0 | NOT NULL, DEFAULT | Decay score at time of archival |
| snap_status_at_archive | VARCHAR(20) | NO | 'EXPIRED' | NOT NULL, DEFAULT | Status at time of archival (EXPIRED or STALE) |

### 2.2 Indexes

| Index Name | Columns | Type | Options | Notes |
|---|---|---|---|---|
| ix_cold_frag_tenant | (tenant_id) | BTREE | - | Tenant isolation scans |
| ix_cold_frag_original | (original_fragment_id) | BTREE | - | Lookup by original fragment |
| ix_cold_frag_emb_semantic_ann | (emb_semantic) | IVFFLAT | vector_cosine_ops, lists=sqrt(n) | ANN search on semantic dimension |
| ix_cold_frag_emb_topological_ann | (emb_topological) | IVFFLAT | vector_cosine_ops, lists=sqrt(n) | ANN search on topological dimension |
| ix_cold_frag_emb_temporal_ann | (emb_temporal) | IVFFLAT | vector_cosine_ops, lists=sqrt(n) | ANN search on temporal dimension |
| ix_cold_frag_emb_operational_ann | (emb_operational) | IVFFLAT | vector_cosine_ops, lists=sqrt(n) | ANN search on operational dimension |
| ix_cold_frag_failure_modes | (failure_mode_tags) | GIN | jsonb_path_ops | Failure mode filtering |
| ix_cold_frag_entities | (extracted_entities) | GIN | jsonb_path_ops | Entity filtering |

### 2.3 IVFFlat List Count Formula

The `lists` parameter for each IVFFlat index follows the pgvector recommendation:

```
lists = floor(sqrt(n))
```

Where `n` is the number of non-NULL rows for that specific embedding column at index creation time.

**Operational procedure:**
- IVFFlat indexes must be created AFTER data is loaded (they require training data).
- Reindex when the row count doubles from the count at last index creation.
- Each embedding column may have a different `lists` value because NULL rates differ across dimensions.
- Query-time `ivfflat.probes` should be set to `floor(sqrt(lists))` for recall/latency balance.

**Example for 1M cold fragments where 90% have valid semantic embeddings:**
```sql
-- n = 900,000 non-NULL emb_semantic rows
-- lists = floor(sqrt(900000)) = 948
CREATE INDEX ix_cold_frag_emb_semantic_ann
  ON cold_fragment USING ivfflat (emb_semantic vector_cosine_ops)
  WITH (lists = 948);
```

### 2.4 CHECK Constraints

```sql
-- Same mask coherence as active table
ALTER TABLE cold_fragment
  ADD CONSTRAINT chk_cold_mask_semantic_coherence
    CHECK (emb_semantic IS NOT NULL OR mask_semantic = FALSE);

ALTER TABLE cold_fragment
  ADD CONSTRAINT chk_cold_mask_topological_coherence
    CHECK (emb_topological IS NOT NULL OR mask_topological = FALSE);

ALTER TABLE cold_fragment
  ADD CONSTRAINT chk_cold_mask_operational_coherence
    CHECK (emb_operational IS NOT NULL OR mask_operational = FALSE);
```

---

## 3. Updated `snap_decision_record`

**Purpose:** Persisted snap evaluation record. Now stores per-dimension scores for all five scoring dimensions.

### 3.1 Columns

| Column Name | Type | Nullable | Default | Constraints | Notes |
|---|---|---|---|---|---|
| id | UUID | NO | uuid4() | PRIMARY KEY | Decision record ID |
| tenant_id | VARCHAR(100) | NO | - | NOT NULL | Tenant isolation (INV-7) |
| new_fragment_id | UUID | NO | - | NOT NULL | Fragment being evaluated |
| candidate_fragment_id | UUID | NO | - | NOT NULL | Fragment being compared against |
| evaluated_at | TIMESTAMP WITH TIME ZONE | NO | now() | NOT NULL, DEFAULT, server_default | Evaluation time |
| failure_mode_profile | VARCHAR(50) | NO | - | NOT NULL | Primary failure mode driving comparison |
| **-- Per-Dimension Scores (v3.0) --** | | | | | |
| score_semantic | FLOAT | YES | NULL | - | Cosine similarity on emb_semantic. NULL if either fragment lacks valid semantic embedding. |
| score_topological | FLOAT | YES | NULL | - | Cosine similarity on emb_topological. NULL if either fragment lacks valid topological embedding. |
| score_temporal | FLOAT | YES | NULL | - | Cosine similarity on emb_temporal. Always non-NULL (temporal embedding always valid). |
| score_operational | FLOAT | YES | NULL | - | Cosine similarity on emb_operational. NULL if either fragment lacks valid operational embedding. |
| score_entity_overlap | FLOAT | NO | - | NOT NULL | Jaccard overlap on extracted_entities. Always computable (set operation, no embedding). |
| **-- Weight & Composite --** | | | | | |
| masks_active | JSONB | NO | - | NOT NULL | Record of which dimensions participated: {"semantic": true, "topological": false, ...} |
| weights_used | JSONB | NO | - | NOT NULL | Actual weights applied after mask-driven re-normalization |
| raw_composite | FLOAT | NO | - | NOT NULL | Weighted sum before temporal modifier |
| temporal_modifier | FLOAT | NO | - | NOT NULL | Temporal proximity adjustment factor |
| final_score | FLOAT | NO | - | NOT NULL | raw_composite * temporal_modifier |
| threshold_applied | FLOAT | NO | - | NOT NULL | Decision threshold compared against |
| decision | VARCHAR(20) | NO | - | NOT NULL | SNAP / NEAR_MISS / AFFINITY / NONE |
| multiple_comparisons_k | INTEGER | NO | 1 | NOT NULL, DEFAULT | Bonferroni correction k value |

### 3.2 Changes from v2.0

| Change | v2.0 | v3.0 |
|---|---|---|
| `component_scores` JSONB | Single JSONB blob: `{semantic_sim, topological_prox, entity_overlap, operational_sim}` | **DROPPED** -- replaced by five explicit typed columns |
| `score_semantic` FLOAT | Did not exist | NEW -- nullable, NULL when mask_semantic is FALSE on either fragment |
| `score_topological` FLOAT | Did not exist | NEW -- nullable, NULL when mask_topological is FALSE on either fragment |
| `score_temporal` FLOAT | Did not exist | NEW -- nullable (but practically always non-NULL) |
| `score_operational` FLOAT | Did not exist | NEW -- nullable, NULL when mask_operational is FALSE on either fragment |
| `score_entity_overlap` FLOAT | Did not exist | NEW -- NOT NULL, always computable via set intersection |
| `masks_active` JSONB | Did not exist | NEW -- records which dimensions were valid for this comparison |

### 3.3 Indexes (unchanged)

| Index Name | Columns | Type |
|---|---|---|
| ix_sdr_tenant_time | (tenant_id, evaluated_at) | BTREE |
| ix_sdr_new_frag | (new_fragment_id) | BTREE |

---

## 4. Temporal Embedding Specification (emb_temporal)

The `emb_temporal` Vector(256) is NOT generated by an LLM. It is a deterministic sinusoidal
positional encoding computed from `temporal_context` JSONB fields.

### 4.1 Input Features

From `temporal_context`:
- `hour_of_day` (0-23)
- `day_of_week` (0-6)
- `day_of_month` (1-31)
- `month_of_year` (1-12)
- `minutes_since_last_event` (continuous, log-scaled)
- `recurrence_period_hours` (continuous, log-scaled, 0 if none)

### 4.2 Encoding Method

Each cyclic feature is encoded as `(sin(2*pi*x/period), cos(2*pi*x/period))` pairs across
multiple frequency bands. Continuous features use log-scaled sinusoidal encoding.

256 dimensions are allocated as:
- hour_of_day: 64 dims (32 frequency bands)
- day_of_week: 32 dims (16 frequency bands)
- day_of_month: 32 dims (16 frequency bands)
- month_of_year: 32 dims (16 frequency bands)
- minutes_since_last_event: 48 dims (24 frequency bands)
- recurrence_period_hours: 48 dims (24 frequency bands)

### 4.3 Guarantees

- Deterministic: same input always produces same output.
- No external dependency: pure math, no network calls, no LLM.
- Always valid: empty `temporal_context` ({}) produces a valid zero-activity vector (all sin/cos terms at their zero-input values).
- No mask required: `emb_temporal` never needs a validity mask.

---

## 5. Migration Notes

### 5.1 Alembic Migration Steps

```
1. ADD columns: emb_semantic, emb_topological, emb_temporal, emb_operational
               mask_semantic, mask_topological, mask_operational
   on abeyance_fragment

2. ADD columns: emb_semantic, emb_topological, emb_temporal, emb_operational
               mask_semantic, mask_topological, mask_operational
               topological_neighbourhood, operational_fingerprint, temporal_context
   on cold_fragment

3. ADD columns: score_semantic, score_topological, score_temporal,
               score_operational, score_entity_overlap, masks_active
   on snap_decision_record

4. MIGRATE existing enriched_embedding data:
   UPDATE abeyance_fragment SET emb_semantic = enriched_embedding,
     mask_semantic = (enriched_embedding IS NOT NULL)
   -- Other dimensions start as NULL/FALSE (will be populated by enrichment pipeline)

5. MIGRATE cold_fragment similarly

6. MIGRATE snap_decision_record:
   UPDATE snap_decision_record SET
     score_semantic = (component_scores->>'semantic_sim')::float,
     score_entity_overlap = (component_scores->>'entity_overlap')::float,
     score_operational = (component_scores->>'operational_sim')::float,
     score_topological = (component_scores->>'topological_prox')::float,
     masks_active = '{"semantic": true, "topological": true, "temporal": false, "operational": true, "entity_overlap": true}'::jsonb

7. DROP columns: enriched_embedding, raw_embedding, embedding_mask
   from abeyance_fragment

8. DROP column: enriched_embedding
   from cold_fragment

9. DROP column: component_scores
   from snap_decision_record

10. ADD CHECK constraints (Section 1.5, Section 2.4)

11. CREATE IVFFlat indexes on cold_fragment (Section 2.2)
    -- Must run AFTER data migration so IVFFlat has training data
```

### 5.2 Rollback Strategy

The migration is split into two Alembic revisions:
- **Revision A (additive):** Steps 1-6. Adds new columns, copies data. Fully reversible.
- **Revision B (destructive):** Steps 7-11. Drops old columns. Reversible only if Revision A data copy was verified.

Run Revision A, validate data integrity, then run Revision B.

---

## 6. Invariants (updated for v3.0)

| Invariant | Description |
|---|---|
| INV-1 | Fragment lifecycle via SnapStatus enum (deterministic state machine) |
| INV-5 | SNAPPED status is terminal for automated processes |
| INV-6 | raw_content bounded to 64KB; max_lifetime_days hard cap |
| INV-7 | tenant_id on every table, every index |
| INV-9 | MAX_EDGES_PER_FRAGMENT bounded (application layer) |
| INV-10 | fragment_history, snap_decision_record are append-only |
| INV-11 | **UPDATED:** Embedding validity tracked via per-column boolean masks (mask_semantic, mask_topological, mask_operational). No JSONB mask. emb_temporal has no mask (always valid). |
| INV-12 | **NEW:** NULL embedding = unknown. Zero-vector fill and hash fallback are prohibited. |
| INV-13 | **NEW:** CHECK constraints enforce mask/embedding coherence at DB level. |
| INV-14 | **NEW:** snap_decision_record stores five explicit per-dimension scores. NULL score = dimension excluded from comparison. |

---

## 7. Storage Estimates

Per active fragment row (worst case, all embeddings populated):
- emb_semantic: 1536 * 4 bytes = 6,144 bytes
- emb_topological: 1536 * 4 bytes = 6,144 bytes
- emb_temporal: 256 * 4 bytes = 1,024 bytes
- emb_operational: 1536 * 4 bytes = 6,144 bytes
- **Total embedding overhead: ~19.5 KB per fragment** (vs. 6 KB in v2.0)

For 100K active fragments per tenant: ~1.9 GB embedding data.
For 1M cold fragments per tenant: ~19 GB embedding data + IVFFlat index overhead (~20% additional).

---

## 8. Extensions Required

- `pgvector` >= 0.5.0 -- for Vector type, IVFFlat indexes, cosine distance operator
- PostgreSQL 15+ -- for JSONB, CHECK constraints, partial indexes

---

Generated: 2026-03-16 | Task T1.2 | Abeyance Memory v3.0
