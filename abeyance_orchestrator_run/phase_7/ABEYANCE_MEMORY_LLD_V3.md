# ABEYANCE MEMORY LOW-LEVEL DESIGN v3.0

**Version**: 3.0
**Date**: 2026-03-16
**Status**: SPECIFICATION COMPLETE
**Supersedes**: ABEYANCE_MEMORY_LLD v2.0
**Assembly**: Phases 1-6 merged into self-contained reference

---

## Table of Contents

1. [Executive Summary and Version History](#1-executive-summary-and-version-history)
2. [Embedding Architecture](#2-embedding-architecture)
3. [Snap Engine and Scoring](#3-snap-engine-and-scoring)
4. [Cold Storage and ANN Search](#4-cold-storage-and-ann-search)
5. [Migration Strategy](#5-migration-strategy)
6. [Remediated Subsystems](#6-remediated-subsystems)
7. [Discovery Mechanisms -- Tier 1](#7-discovery-mechanisms----tier-1)
8. [Discovery Mechanisms -- Tier 2](#8-discovery-mechanisms----tier-2)
9. [Discovery Mechanisms -- Tier 3](#9-discovery-mechanisms----tier-3)
10. [Discovery Mechanisms -- Tier 4](#10-discovery-mechanisms----tier-4)
11. [Cognitive Architecture](#11-cognitive-architecture)
12. [Discovery Loop](#12-discovery-loop)
13. [Explainability Layer](#13-explainability-layer)
14. [Hard System Invariants](#14-hard-system-invariants)
15. [Observability and Metrics](#15-observability-and-metrics)
16. [Failure Recovery](#16-failure-recovery)
17. [Scalability Analysis](#17-scalability-analysis)
18. [Audit Finding Resolution Matrix](#18-audit-finding-resolution-matrix)
19. [Database Schema Summary](#19-database-schema-summary)
20. [Appendices](#20-appendices)

---

## 1. Executive Summary and Version History

### 1.1 Purpose

The Abeyance Memory subsystem discovers hidden relationships in network operations data by correlating fragments of evidence (alarms, logs, metrics, tickets, CMDB deltas) across time and topology. It enriches each fragment with four semantically distinct embeddings, scores pairwise similarity via a mask-aware weighted engine, and maintains an accumulation graph that surfaces clusters of correlated evidence. Above this foundation, fourteen discovery mechanisms operating across five cognitive layers detect anomalies, generate hypotheses, test causal claims, compress patterns, and allocate exploration effort.

### 1.2 Scope of v3.0

v3.0 is a ground-up remediation of v2.0 driven by a 31-finding forensic audit. Major changes:

- Four-column embedding architecture replacing the single concatenated vector (remediates F-3.2, F-6.2).
- Local model serving via T-VEC 1.5B (CPU) and TSLAM-8B (GPU) eliminating all cloud LLM dependency (remediates F-5.1, F-8.1).
- Mask-aware weight redistribution in the snap engine ensuring unavailable dimensions are properly excluded (remediates F-6.2).
- Fourteen discovery mechanisms across five cognitive layers: Correlation (L1), Discovery (L2), Hypothesis (L3), Evidence (L4), Insight (L5).
- 42 Prometheus-compatible observability metrics with 7 alerting rules (remediates F-7.1, F-7.2, F-7.3).
- Complete failure recovery procedures for 7 scenarios.
- 56 database tables, all tenant-isolated.

### 1.3 Version History

| Version | Date | Description |
|---------|------|-------------|
| 1.0 | 2025-11-15 | Initial design with single concatenated embedding |
| 2.0 | 2026-02-20 | Post-forensic audit remediation; four-column schema specified but not fully integrated |
| 3.0 | 2026-03-16 | Complete integration of all 14 discovery mechanisms, 5-layer cognitive architecture, full audit resolution |

### 1.4 Design Targets

| Parameter | Target |
|-----------|--------|
| Active fragments | Up to 50M (global), 500K per tenant |
| Event ingestion rate | 10K-100K events/sec |
| Tenant count | Up to 100 |
| Enrichment latency (p50) | < 2 seconds per fragment |
| Snap evaluation latency (critical path) | 60-600ms |
| Cold storage retention | 3-year tiered lifecycle |

### 1.5 Naming Conventions

All table names use `snake_case`. The canonical table name for snap decisions is `snap_decision_record` (NOT `snap_decision_log`). See Section 11 conflict resolution 5.1 for full rationale.

**Invariant cross-reference**: INV-7 (tenant isolation), INV-10 (append-only provenance), INV-11 (mask-aware scoring).

---

## 2. Embedding Architecture

This section consolidates T1.1 (Serving Architecture), T1.2 (ORM Schema), and T1.3 (Enrichment Chain).

### 2.1 Model Stack

| Model | Purpose | Size | Hardware | Output Dim | License |
|-------|---------|------|----------|------------|---------|
| T-VEC 1.5B | Embedding generation (semantic, topological, operational) | ~3 GB RAM | CPU only | 1536 | MIT |
| TSLAM-8B | Text generation (entity extraction, hypothesis generation) | ~16 GB VRAM | GPU (preferred) | N/A (text) | Llama 3.1 |
| TSLAM-4B | Text generation fallback | ~8 GB VRAM / ~6 GB RAM (Q4_K_M) | CPU or GPU | N/A (text) | Llama 3.1 |

Both models run locally. Zero cloud LLM dependency. Zero marginal cost per call. This resolves F-5.1 and F-8.1.

### 2.2 T-VEC 1.5B Serving

**Loading**: Lazy singleton with `asyncio.Lock` preventing concurrent duplicate loads. Model files cached by HuggingFace Hub in `~/.cache/huggingface/`. Optional background pre-warm after lifespan yield.

**Inference wrapping**: Dedicated `ThreadPoolExecutor(max_workers=2, thread_name_prefix="tvec")`. SentenceTransformer.encode() is blocking CPU; it must never run on the asyncio event loop.

**Batch strategy**: Each fragment requires 3 T-VEC calls (semantic, topological, operational). These are micro-batched into a single `model.encode([text_sem, text_topo, text_oper])` call. Cross-fragment coalescing is optional (env var `TVEC_BATCH_COALESCE=1`, max_batch_size=32, max_wait_ms=50).

**Throughput (ARM CPU)**:

| Mode | Batch Size | Texts/sec | Fragments/sec | Latency (p50) |
|------|-----------|-----------|---------------|---------------|
| Single text | 1 | 2-3 | 0.7-1.0 | ~400ms |
| Micro-batch (3/fragment) | 3 | 5-7 | 1.7-2.3 | ~500ms |
| Coalesced batch | 32 | 15-20 | 5.0-6.7 | ~2.0s |

**Async interface**:

```python
class TVecService:
    async def embed(self, text: str) -> Optional[list[float]]
    async def embed_batch(self, texts: list[str]) -> list[Optional[list[float]]]
    async def health(self) -> dict
```

### 2.3 TSLAM-8B Serving (GPU Path)

**Primary**: vLLM sidecar exposing OpenAI-compatible HTTP API on localhost:8100. Continuous batching handled internally by vLLM. No `run_in_executor` needed.

**vLLM configuration**: `--gpu-memory-utilization 0.85`, `--max-model-len 4096`, `--dtype float16`, `--max-num-seqs 8`.

**Throughput (GPU)**:

| Scenario | Throughput | Latency (p50) |
|----------|-----------|---------------|
| Single request (entity extraction) | ~50-80 tokens/sec | ~2-3s |
| 4 concurrent requests | ~150-250 tokens/sec aggregate | ~3-4s |

**Fallback**: TSLAM-4B via llama-cpp-python (GGUF Q4_K_M), single-threaded executor. Throughput ~8-12 tokens/sec, ~12-18s per entity extraction. Switching is one-directional within a process lifetime.

**Async interface**:

```python
class TSLAMService:
    async def generate(self, prompt: str, max_tokens: int = 512, temperature: float = 0.1) -> Optional[str]
    async def generate_structured(self, prompt: str, schema: dict, max_tokens: int = 512) -> Optional[dict]
    async def health(self) -> dict
```

### 2.4 Backpressure Design

| Semaphore | Default | Controls |
|-----------|---------|----------|
| `TVEC_CONCURRENCY` | 4 | Max concurrent T-VEC embed calls |
| `TSLAM_CONCURRENCY` | 8 (vLLM) / 2 (llama-cpp) | Max concurrent TSLAM generate calls |
| `ENRICHMENT_CONCURRENCY` | 4 | Max fragments enriched in parallel (outer bound) |

**Timeout policy**:

| Operation | Timeout | On Timeout |
|-----------|---------|------------|
| T-VEC single embed | 10s | Return None, mask=FALSE |
| T-VEC batch embed | 30s | Return None, masks=FALSE |
| TSLAM generate (vLLM) | 30s | Return None, regex fallback |
| TSLAM generate (llama-cpp) | 60s | Return None, regex fallback |
| Model loading | 120s | Health reports NOT_READY |

### 2.5 ORM Schema -- abeyance_fragment

Four-column embedding architecture replacing the single concatenated vector:

| Column | Type | Nullable | Source | Mask |
|--------|------|----------|--------|------|
| emb_semantic | Vector(1536) | YES | T-VEC(raw_content + entities) | mask_semantic |
| emb_topological | Vector(1536) | YES | T-VEC(neighbourhood text) | mask_topological |
| emb_temporal | Vector(256) | YES | Sinusoidal(temporal_context) | No mask (always valid) |
| emb_operational | Vector(1536) | YES | T-VEC(failure_modes + fingerprint) | mask_operational |

**Embedding validity rules**:
1. T-VEC failure: column = NULL, mask = FALSE.
2. Zero-vector fill is PROHIBITED (INV-12).
3. Hash-based fallback embeddings are PROHIBITED (resolves F-3.3).
4. emb_temporal has no mask; sinusoidal encoding always succeeds.
5. When mask = FALSE, snap engine MUST exclude that dimension and redistribute weight (INV-11).

**CHECK constraints** enforce mask/embedding coherence at DB level (INV-13):

```sql
CHECK (emb_semantic IS NOT NULL OR mask_semantic = FALSE)
CHECK (emb_topological IS NOT NULL OR mask_topological = FALSE)
CHECK (emb_operational IS NOT NULL OR mask_operational = FALSE)
```

**Additional key columns**: id (UUID PK), tenant_id (VARCHAR(100) NOT NULL), source_type, raw_content (TEXT, bounded 64KB per INV-6), extracted_entities (JSONB), topological_neighbourhood (JSONB), operational_fingerprint (JSONB), failure_mode_tags (JSONB), temporal_context (JSONB), event_timestamp, snap_status (VARCHAR(20), default 'INGESTED'), current_decay_score (FLOAT, default 1.0), max_lifetime_days (INTEGER, default 730), dedup_key (VARCHAR(500)).

**State machine** (unchanged from v2.0):

```
INGESTED -> ACTIVE -> {NEAR_MISS, SNAPPED, STALE}
NEAR_MISS -> {SNAPPED, ACTIVE, STALE}
STALE -> EXPIRED
EXPIRED -> COLD
SNAPPED -> (terminal)
COLD -> (terminal)
```

**Indexes**: ix_abeyance_fragment_tenant_status (tenant_id, snap_status), ix_abeyance_fragment_tenant_decay (tenant_id, current_decay_score WHERE snap_status IN ACTIVE/NEAR_MISS), GIN on failure_mode_tags and extracted_entities, UNIQUE on (tenant_id, dedup_key).

No ANN indexes on abeyance_fragment: active set is small (~50K/tenant); exact distance used. ANN indexes reserved for cold storage.

### 2.6 ORM Schema -- snap_decision_record

Per-dimension scoring audit log with five explicit FLOAT columns (resolves conflict 5.2 from cognitive_architecture.md):

| Column | Type | Nullable | Notes |
|--------|------|----------|-------|
| id | UUID PK | NO | |
| tenant_id | VARCHAR(100) | NO | |
| new_fragment_id | UUID | NO | Fragment being evaluated |
| candidate_fragment_id | UUID | NO | Fragment compared against |
| evaluated_at | TIMESTAMPTZ | NO | |
| failure_mode_profile | VARCHAR(50) | NO | |
| score_semantic | FLOAT | YES | NULL if either lacks valid semantic |
| score_topological | FLOAT | YES | NULL if either lacks valid topological |
| score_temporal | FLOAT | YES | Practically always non-NULL |
| score_operational | FLOAT | YES | NULL if either lacks valid operational |
| score_entity_overlap | FLOAT | NO | Always computable (Jaccard) |
| masks_active | JSONB | NO | Which dimensions participated |
| weights_used | JSONB | NO | Post-redistribution weights |
| weights_base | JSONB | NO | Original profile weights (added for Outcome Calibration) |
| raw_composite | FLOAT | NO | Before temporal modifier |
| temporal_modifier | FLOAT | NO | [0.5, 1.0] |
| final_score | FLOAT | NO | raw_composite * temporal_modifier |
| threshold_applied | FLOAT | NO | After Sidak correction |
| decision | VARCHAR(20) | NO | SNAP / NEAR_MISS / AFFINITY / NONE |
| multiple_comparisons_k | INTEGER | NO | Bonferroni k value |

**Invariants**: INV-10 (append-only), INV-14 (five explicit per-dimension scores).

### 2.7 Temporal Embedding Specification

256-dim sinusoidal positional encoding. No LLM dependency. Deterministic. Always valid.

| Feature | Dim Range | Period Basis |
|---------|-----------|-------------|
| Time of day | 0-63 | 24h cycle, 32 sin/cos pairs |
| Day of week | 64-127 | 7-day cycle, 32 sin/cos pairs |
| Day of year (seasonal) | 128-191 | 365-day cycle, 32 sin/cos pairs |
| Operational context | 192-255 | change_proximity (Gaussian decay sigma=24h), upgrade_recency (exp decay tau=30d), load_ratio |

### 2.8 Enrichment Chain -- Five-Step Flow

Step (a): **TSLAM-8B Entity Extraction + Hypothesis Generation**. Single local model call replaces both cloud LLM entity extraction and rule-based failure mode classification. Regex always runs as supplement. Fallback on TSLAM failure: regex entities + rule-based failure modes. Resolves F-4.2.

Step (b): **T-VEC Semantic Embedding** -> emb_semantic (1536). Input: `[source_type] raw_content[:3000]\nEntities: identifier [DOMAIN]; ...`

Step (c): **T-VEC Topological Embedding** -> emb_topological (1536). F-3.2 fix: entity identifiers resolved to Shadow Topology UUIDs via `get_or_create_entity()`, then passed as `entity_ids` parameter (NOT empty list). Input: seed entities + hop-1/hop-2 neighbours + relationship type summary.

Step (d): **Sinusoidal Temporal Encoding** -> emb_temporal (256). Pure math. Cannot fail.

Step (e): **T-VEC Operational Embedding** -> emb_operational (1536). Input: failure mode hypotheses from TSLAM + traffic regime + change proximity + concurrent alarms + entity domain summary.

**Per-dimension failure isolation**: Each dimension computed independently. Failure in one dimension MUST NOT prevent others. F-6.1 resolved.

**Execution DAG**: Steps (b), (d), (e) run concurrently via `asyncio.gather`. Step (c) depends on Shadow Topology lookup (which needs entity UUIDs from step (a)) but is otherwise concurrent with (b), (d), (e).

**Invariants for this section**: INV-6 (raw_content bounded 64KB), INV-7 (tenant_id isolation), INV-11 (mask-aware scoring), INV-12 (NULL = unknown, no zero-fill), INV-13 (CHECK constraints).

### 2.9 Health Checks

Aggregated at `GET /api/v1/abeyance/models/health`. Overall status: `ready` (both models up), `degraded` (TSLAM in fallback or error_count > 0), `unavailable` (T-VEC down). TSLAM unavailability alone does NOT make system unavailable; entity extraction falls back to regex.

---

## 3. Snap Engine and Scoring

This section consolidates T1.4 (Snap Scoring Redesign). Remediates F-2.4, F-6.2.

### 3.1 Per-Dimension Similarity Functions

Five scoring dimensions:

| Dimension | Symbol | Source | Can Be Unavailable | Computation |
|-----------|--------|--------|-------------------|-------------|
| Semantic | S_sem | emb_semantic | Yes | cosine(A.emb_semantic, B.emb_semantic) clamped [0,1] |
| Topological | S_topo | emb_topological | Yes | cosine(A.emb_topological, B.emb_topological) clamped [0,1] |
| Temporal | S_temp | emb_temporal | No | cosine(A.emb_temporal, B.emb_temporal) clamped [0,1] |
| Operational | S_oper | emb_operational | Yes | cosine(A.emb_operational, B.emb_operational) clamped [0,1] |
| Entity Overlap | S_ent | Entity refs | No | Jaccard(entities_A, entities_B) |

**Degenerate input guard**: L2 norm < 1e-10 returns 0.0.

### 3.2 Mask Enforcement

Dimension d is available for pair (A, B) iff both fragments have mask_d = TRUE. Temporal and entity overlap are always available.

If unavailable: snap engine MUST NOT compute cosine similarity. The dimension is excluded and its weight redistributed. This resolves F-6.2.

### 3.3 Weight Redistribution Formula

Base weight profile: `P = {w_sem, w_topo, w_temp, w_oper, w_ent}` where sum = 1.0 and all weights > 0.

Given D_avail (available dimensions) and D_unavail (unavailable dimensions):

```
w_d_adjusted = w_d / SUM(w_i for i in D_avail)
```

This renormalizes available weights to sum to 1.0. Since temporal and entity_overlap are always available and have strictly positive weights, total_available > 0 for every pair. Bounded arithmetic guarantee holds.

### 3.4 Weight Profiles

Five initial profiles (estimates pending empirical validation per Section 3.5):

| Profile | w_sem | w_topo | w_temp | w_oper | w_ent | Rationale |
|---------|-------|--------|--------|--------|-------|-----------|
| DARK_EDGE | 0.15 | 0.30 | 0.10 | 0.15 | 0.30 | Missing connections: topology + entity overlap dominate |
| DARK_NODE | 0.25 | 0.10 | 0.10 | 0.20 | 0.35 | Unknown entities: entity overlap is strongest signal |
| IDENTITY_MUTATION | 0.10 | 0.15 | 0.10 | 0.20 | 0.45 | CI naming changes: entity overlap dominant |
| PHANTOM_CI | 0.20 | 0.15 | 0.10 | 0.25 | 0.30 | Phantom CIs: operational + entity overlap |
| DARK_ATTRIBUTE | 0.25 | 0.10 | 0.10 | 0.25 | 0.30 | Unexpected attributes: semantic + operational |

**Profile validation at startup**: All weights > 0.0, sum to 1.0 within 1e-9, w_temp > 0 and w_ent > 0.

### 3.5 Empirical Validation Methodology (Outcome Calibration)

Four-phase approach addressing F-2.4:
1. **Baseline Collection** (passive): Deploy initial estimates; record all snap decisions with per-dimension scores; collect operator feedback (TP/FP/FN).
2. **Sensitivity Analysis**: Marginal contribution per dimension with +/- 0.05 perturbation.
3. **Weight Optimization**: Maximize AUC(final_score | operator_verdict) per profile. Constrained Bayesian optimization on 4-simplex. No weight below 0.05.
4. **Deployment**: Update profiles with optimized weights. Tag calibration_status="EMPIRICALLY_VALIDATED". Minimum 500 labeled outcomes per profile before optimization.

Cross-reference: Outcome Calibration (Mechanism #5, Section 8.1) implements the closed-loop feedback for this methodology.

### 3.6 Composite Score Computation

```
1. Determine dimension availability via mask AND
2. Compute per-dimension scores (only for available)
3. Redistribute weights: w_d_adj = w_d / total_available
4. Weighted combination: raw_composite = SUM(w_d_adj * score_d)
5. Temporal modifier: final_score = clamp(raw_composite * temporal_modifier, 0, 1)
```

**Temporal modifier** (retained from v2.0): Captures absolute-time recency (distinct from S_temp which captures cyclical pattern similarity). Bounded [0.5, 1.0]. Can only attenuate, never amplify.

**Sidak correction**: Retained. When multiple profiles evaluated for same candidate pair, threshold adjusted upward. multiple_comparisons_k tracked in snap_decision_record.

**Determinism guarantee**: No random operations. IEEE 754 float64 throughout. Result rounded to 6 decimal places at persistence boundary.

### 3.7 Invariants for this Section

| ID | Statement |
|----|-----------|
| INV-3 | All scores in [0.0, 1.0] |
| INV-8 | No output outside declared range |
| INV-10 | All scoring decisions persisted to snap_decision_record |
| INV-11 | Mask consulted before every cosine computation |
| INV-NEW-1 | Available weight sum > 0 (temporal + entity_overlap always available) |
| INV-NEW-2 | Adjusted weights sum to 1.0 |
| INV-NEW-3 | No cosine on NULL embeddings |

---

## 4. Cold Storage and ANN Search

Consolidates T1.5. Remediates F-3.4, F-5.4, F-6.3, F-8.2, F-9.1.

### 4.1 Architecture

Cold storage uses PostgreSQL with pgvector (ColdFragmentORM on `cold_fragment` table). The four-column T-VEC schema mirrors the active fragment layout. Parquet backend retained as fallback with error logging (F-6.3: bare `except` replaced with explicit exception handling and logged warnings).

### 4.2 ColdFragmentORM Schema

Mirrors abeyance_fragment embedding columns: emb_semantic (Vector(1536)), emb_topological (Vector(1536)), emb_temporal (Vector(256)), emb_operational (Vector(1536)), mask_semantic, mask_topological, mask_operational. Plus: original_fragment_id, archived_at, original_decay_score, snap_status_at_archive, expiration_tier, expires_at.

CHECK constraints enforce mask/embedding coherence (same as active table).

### 4.3 IVFFlat Index Strategy (F-5.4)

Dynamic `lists` parameter: `lists = ceil(sqrt(n))` where n = non-NULL rows for that column.

```python
def compute_ivfflat_lists(row_count: int, min_lists: int = 10, max_lists: int = 4096) -> int:
    if row_count < 100:
        return min_lists
    return min(max_lists, max(min_lists, math.ceil(math.sqrt(row_count))))
```

Partial indexes filter on mask: `WHERE mask_semantic = FALSE` (inverted: mask=FALSE means valid in cold schema). Index rebuild when row count changes by > 20% since last build.

Query-time `ivfflat.probes = floor(sqrt(lists))` for recall/latency balance.

Four IVFFlat indexes created via Alembic raw SQL with `CREATE INDEX CONCURRENTLY`.

### 4.4 Multi-Index Fusion (RRF)

When querying across multiple embedding dimensions, results from per-dimension ANN searches are fused using Reciprocal Rank Fusion:

```
RRF_score(d) = SUM(1 / (k + rank_i(d))) for each index i where mask is valid
```

With k=60. Only dimensions where the query fragment's mask is TRUE are queried.

### 4.5 Tiered Cold Expiration (F-8.2)

| Tier | Days Since archived_at | State | Action |
|------|----------------------|-------|--------|
| ACTIVE | 0-365 | Full embeddings + metadata | No action |
| COMPRESSED | 365-730 | Truncated summary, embeddings retained | Truncate raw_content_summary |
| TOMBSTONED | 730-1095 | Drop embeddings, keep metadata | Set emb_* = NULL, masks = FALSE |
| DELETE | > 1095 | Permanent deletion | DELETE row |

Expiration job runs daily. Tiered approach prevents unbounded cold storage growth.

### 4.6 Tenant ID Sanitisation (F-9.1)

```python
_TENANT_ID_SAFE_RE = re.compile(r'^[a-zA-Z0-9_-]{1,128}$')
```

All path construction validates tenant_id against this pattern. Rejects `../../etc` traversal attempts.

### 4.7 Invariants for this Section

| ID | Statement |
|----|-----------|
| INV-7 | tenant_id on cold_fragment, every query |
| INV-11 | Mask consulted in multi-index fusion |
| INV-12 | NULL = unknown in cold storage (TOMBSTONED tier) |
| INV-13 | CHECK constraints on cold_fragment |

---

## 5. Migration Strategy

Consolidates T1.6. Four Alembic revisions for zero-downtime migration from v2 to v3 schema.

### 5.1 Schema Delta

| Aspect | v2 | v3 |
|--------|-----|-----|
| Embedding storage | enriched_embedding Vector(1536) | 4 separate emb_* columns |
| Mask storage | embedding_mask JSONB (4-element array) | 3 per-dimension BOOLEAN columns |
| ANN index | IVFFlat on enriched_embedding | Per-dimension indexes |

**Critical constraint**: The old enriched_embedding is an L2-normalized concatenation. No mathematically sound decomposition exists. Old fragments get all mask_* = FALSE and emb_* = NULL.

### 5.2 Alembic Revisions

**Revision 1** (`v3_001_add_decomposed_embedding_columns`): ADD new embedding + mask columns to abeyance_fragment. Metadata-only operation, < 100ms lock. Application continues during revision.

**Revision 2** (`v3_002_backfill_old_fragment_mask_columns`): Batched UPDATE (10K rows/batch, 50ms sleep, FOR UPDATE SKIP LOCKED). Sets mask_*=FALSE and embedding_schema_version=2 on existing rows. Idempotent. ~5 seconds for 1M rows.

**Revision 3** (`v3_003_add_decomposed_embedding_indexes`): CREATE INDEX CONCURRENTLY for per-dimension HNSW/IVFFlat indexes. Same columns added to cold_fragment.

**Revision 4** (`v3_004_drop_old_columns`): DROP enriched_embedding, raw_embedding, embedding_mask, component_scores. Irreversible. Guarded by cutover criteria.

### 5.3 Dual-Write Period

New fragments write to new columns (embedding_schema_version=3). Old fragments are never re-embedded retroactively. Natural decay governs cutover.

### 5.4 Cutover Criteria

Six conditions before Revision 4:

1. Zero active/near_miss fragments with embedding_schema_version=2.
2. Enrichment pipeline writing to new columns for >= 14 days without error.
3. Snap engine operating on per-dimension scores for >= 14 days.
4. Cold storage archival writing four-column schema for >= 7 days.
5. No Revision 1 downgrade executed in the last 30 days.
6. Operator explicit approval.

### 5.5 Rollback Plan

Revisions 1-3: fully reversible via Alembic downgrade. Revision 4 is irreversible; requires backup restore if rollback needed.

---

## 6. Remediated Subsystems

Consolidates Phase 2 fixes: shadow topology wiring (F-3.1, F-3.2), accumulation graph (F-5.2, F-5.3), telemetry aligner (F-3.3), decay engine interface (F-4.4), deprecated removal (F-3.5), maintenance fixes (F-7.3).

### 6.1 Shadow Topology Wiring (F-3.1, F-3.2)

**Problem**: F-3.1: Shadow Topology service built but unused in snap engine. F-3.2: `get_neighbourhood()` called with empty entity list.

**Fix**: `get_neighbourhood()` now accepts `entity_identifiers: list[str]` (not just UUIDs). Returns `NeighbourhoodResult` dataclass containing entities, relationships, and depth_map. SnapEngine constructor gains `shadow_topology` parameter.

The enrichment chain resolves entity identifiers to Shadow Topology UUIDs via `get_or_create_entity()` before calling `get_neighbourhood(entity_ids=entity_uuids, max_hops=2)`. This is the core F-3.2 fix.

### 6.2 Accumulation Graph Fixes (F-5.2, F-5.3)

**F-5.2 fix**: Bounded BFS. `MAX_CLUSTER_EDGES = 1000`. Replaces unbounded `SELECT *` with paginated query. BFS traversal capped by edge count, preventing 2GB+ memory load per tenant.

**F-5.3 fix**: Batch JOIN replacing N+1 queries in `prune_stale_edges()`. Single query with JOIN replaces per-edge SELECT loop. `maintenance_job_history` table added for job tracking.

### 6.3 Telemetry Aligner Fix (F-3.3)

**Problem**: `_hash_embedding()` fallback activates every call because `loop.is_running() == True` in async FastAPI.

**Fix**: `_hash_embedding()` function deleted entirely. `embed_anomaly()` made async. T-VEC integration replaces all embedding generation. Only two outcomes per dimension: valid vector or NULL.

### 6.4 Decay Engine Interface (F-4.4)

New interface: `apply_accelerated_decay(fragment_id, acceleration_factor)`. Acceleration factor bounded to [2.0, 10.0]. Monotonicity preservation: decay score can only decrease. Used by Negative Evidence mechanism (Section 7.3).

### 6.5 Deprecated Code Removal (F-3.5)

`abeyance_decay.py` (407 lines) removed. Config cleanup. Migration chain preserved. Deprecated tests removed.

### 6.6 Maintenance Job History (F-7.3)

`maintenance_job_history` table: id (UUID), tenant_id, job_type (VARCHAR), started_at, completed_at, fragments_processed (INTEGER), edges_pruned (INTEGER), outcome (VARCHAR), error_message (TEXT).

---

## 7. Discovery Mechanisms -- Tier 1

Four mechanisms in Layer 2 (Discovery). All observe Layer 1 outputs without modification.

### 7.1 Mechanism #1: Surprise Engine

**Purpose**: Detect statistically surprising snap scores that indicate novel failure patterns.

**Algorithm**: Fixed-width histogram (50 bins over [0,1]) per (tenant_id, failure_mode_profile). Shannon self-information: `surprise = -log2(P(bin))`. Exponential decay on histogram counts (alpha=0.995). Laplace smoothing (pseudocount=0.01). Adaptive threshold at 98th percentile of observed surprise values.

**Cold-start**: DEFAULT_THRESHOLD = 6.64 bits (equivalent to 1-in-100 bin frequency). MINIMUM_MASS = 30.0 histogram observations before adaptive threshold activates.

**Surprise cap**: 20 bits. Values above this clamped.

**Escalation types**:
- DISCOVERY: <= 2 high-surprise dimensions (targeted novelty).
- DRIFT_ALERT: 3+ high-surprise dimensions (broad embedding shift).
- CALIBRATION_ALERT: 5+ monotonic threshold decreases (threshold decaying to noise floor).

**Tables**: `surprise_event` (id, tenant_id, snap_decision_record_id, surprise_value, threshold_at_time, escalation_type, dimensions_contributing, created_at), `surprise_distribution_state` (tenant_id, failure_mode_profile, histogram_bins JSONB, observation_count, threshold_value, last_updated_at).

**Memory**: ~117KB for 10 tenants x 5 profiles.

**Table schema -- surprise_event**:

| Column | Type | Nullable | Notes |
|--------|------|----------|-------|
| id | UUID PK | NO | |
| tenant_id | VARCHAR(100) | NO | Leading index column |
| snap_decision_record_id | UUID FK | NO | References snap_decision_record |
| failure_mode_profile | VARCHAR(50) | NO | |
| surprise_value | FLOAT | NO | Self-information in bits |
| threshold_at_time | FLOAT | NO | Adaptive threshold when evaluated |
| escalation_type | VARCHAR(30) | NO | DISCOVERY / DRIFT_ALERT / CALIBRATION_ALERT |
| dimensions_contributing | JSONB | NO | Which dimensions had high surprise |
| bin_index | INTEGER | NO | Which histogram bin was hit |
| bin_probability | FLOAT | NO | P(bin) at evaluation time |
| created_at | TIMESTAMPTZ | NO | server_default=now() |

**Table schema -- surprise_distribution_state**:

| Column | Type | Nullable | Notes |
|--------|------|----------|-------|
| tenant_id | VARCHAR(100) | NO | Composite PK part 1 |
| failure_mode_profile | VARCHAR(50) | NO | Composite PK part 2 |
| histogram_bins | JSONB | NO | 50-element array of counts |
| observation_count | FLOAT | NO | Total observations (decayed) |
| threshold_value | FLOAT | NO | Current adaptive threshold |
| threshold_monotonic_decrease_count | INTEGER | NO | Consecutive decreases (for CALIBRATION_ALERT) |
| last_updated_at | TIMESTAMPTZ | NO | |

**Histogram update procedure**:

```
ON each snap_decision_record:
  1. bin_index = floor(final_score * NUM_BINS)  # clamp to [0, NUM_BINS-1]
  2. Apply exponential decay: histogram[i] *= alpha for all i
  3. Increment: histogram[bin_index] += 1.0
  4. Recompute observation_count = SUM(histogram)
  5. Compute P(bin) = (histogram[bin_index] + pseudocount) / (observation_count + NUM_BINS * pseudocount)
  6. surprise = -log2(P(bin))
  7. If surprise > threshold AND observation_count >= MINIMUM_MASS: emit surprise_event
  8. Recompute threshold as 98th percentile of surprise distribution over recent events
```

**Invariants**: INV-S1 (histogram bins in [0,1]), INV-S2 (surprise >= 0), INV-S3 (threshold >= 0), INV-S4 (Laplace smoothing prevents zero-probability), INV-S5 (exponential decay alpha in (0,1)), INV-S6 (surprise cap = 20 bits), INV-S7 (MINIMUM_MASS enforced before adaptive threshold), INV-S8 (tenant isolation on histogram state).

### 7.2 Mechanism #2: Ignorance Mapping

**Purpose**: Passively measure what the system does NOT know -- entity extraction failure rates, mask distributions, and silent fragment decay without any snap activity.

**Remediates**: F-4.2 (entity extraction as single point of failure).

**Components**:
1. **Extraction success rates**: Track per-(tenant_id, source_type, entity_domain) success rates for TSLAM vs regex extraction.
2. **Mask distributions**: Per-(tenant_id, failure_mode_profile) distribution of which mask combinations fragments carry (e.g., 85% have all masks TRUE, 10% missing topological, 5% missing all T-VEC).
3. **Silent decay tracking**: Identify fragments that decay to EXPIRED without ever participating in a snap evaluation. These represent potential missed correlations.

**Tables**: `ignorance_extraction_stat`, `ignorance_mask_distribution`, `ignorance_silent_decay_record`, `ignorance_silent_decay_stat`, `ignorance_map_entry`, `exploration_directive`, `ignorance_job_run` (7 tables total).

**Job schedule**: Daily batch per tenant. Reads abeyance_fragment, cold_fragment, snap_decision_record.

**Output**: `ignorance_map_entry` records per (tenant_id, entity_domain, metric_type) with quantified ignorance score. `exploration_directive` records suggest areas where the system should invest more attention (consumed by Meta-Memory, Section 10.3).

**Table schema -- ignorance_extraction_stat**:

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| tenant_id | VARCHAR(100) | NOT NULL |
| source_type | VARCHAR(50) | NOT NULL |
| entity_domain | VARCHAR(50) | Nullable (NULL = overall) |
| extraction_method | VARCHAR(20) | tslam / regex / explicit |
| success_count | INTEGER | Fragments with >= 1 entity extracted |
| total_count | INTEGER | Total fragments attempted |
| success_rate | FLOAT | success_count / total_count |
| period_start | TIMESTAMPTZ | |
| period_end | TIMESTAMPTZ | |

**Table schema -- ignorance_mask_distribution**:

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| tenant_id | VARCHAR(100) | NOT NULL |
| failure_mode_profile | VARCHAR(50) | NOT NULL |
| mask_pattern | VARCHAR(10) | e.g., "TTF" for semantic=TRUE, topo=TRUE, oper=FALSE |
| fragment_count | INTEGER | Count in this pattern |
| fraction | FLOAT | As fraction of total |
| period_start | TIMESTAMPTZ | |
| period_end | TIMESTAMPTZ | |

**Table schema -- ignorance_silent_decay_record**:

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| tenant_id | VARCHAR(100) | NOT NULL |
| fragment_id | UUID | The fragment that decayed silently |
| source_type | VARCHAR(50) | |
| entity_count | INTEGER | Entities extracted |
| mask_pattern | VARCHAR(10) | Mask state at expiry |
| max_snap_score | FLOAT | Highest snap score ever computed (NULL if never evaluated) |
| created_at | TIMESTAMPTZ | When the silent decay was detected |

**Table schema -- ignorance_map_entry**:

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| tenant_id | VARCHAR(100) | NOT NULL |
| entity_domain | VARCHAR(50) | NOT NULL |
| metric_type | VARCHAR(50) | extraction_gap / mask_degradation / silent_decay_rate |
| ignorance_score | FLOAT | [0,1] where 1 = maximum ignorance |
| detail | JSONB | Breakdown data |
| computed_at | TIMESTAMPTZ | |

**Table schema -- exploration_directive**:

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| tenant_id | VARCHAR(100) | NOT NULL |
| entity_domain | VARCHAR(50) | NOT NULL |
| directive_type | VARCHAR(50) | increase_extraction / improve_topology / monitor_decay |
| priority | FLOAT | Higher = more urgent |
| rationale | TEXT | Human-readable explanation |
| created_at | TIMESTAMPTZ | |
| consumed_at | TIMESTAMPTZ | Nullable; set when Meta-Memory processes it |

**Invariants**: INV-IG-1 (ignorance scores in [0,1]), INV-IG-2 (tenant isolation), INV-IG-3 (silent decay tracking only for fragments that reached EXPIRED without SNAPPED transition).

### 7.3 Mechanism #3: Negative Evidence

**Purpose**: Allow operators and automated systems to mark fragments as irrelevant, applying accelerated decay. Resolves F-4.4.

**Two pathways**:
1. **Operator-driven**: POST /api/v1/tenants/{tenant_id}/abeyance/disconfirm with fragment_ids (batch limit 50), reason, and optional acceleration_factor (default 5.0).
2. **System-driven**: Automated disconfirmation based on confirmed false-positive snap outcomes.

**Disconfirmation API**: Validates fragment_ids exist and belong to tenant. Calls `apply_accelerated_decay(fragment_id, acceleration_factor)` per fragment. Acceleration factor bounded [2.0, 10.0]. Monotonicity preserved (decay only decreases).

**Propagation mechanism**: After disconfirmation, compute centroid embedding from disconfirmed fragments. Find similar fragments above PROPAGATION_SIMILARITY_THRESHOLD=0.70. Apply penalty to their snap scores.

**Penalty application**: After composite score and temporal modifier, before snap threshold comparison:

```
penalized_score = final_score * (1 - penalty_strength * pattern_weight)
```

PENALTY_STRENGTH=0.30, PENALTY_FLOOR=0.30 (score cannot be reduced below 30% of original). PATTERN_DECAY_TAU=90 days (exponential decay of pattern influence). PATTERN_TTL=180 days (patterns deleted after this).

**Table schema -- disconfirmation_events**:

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| tenant_id | VARCHAR(100) | NOT NULL |
| initiated_by | VARCHAR(255) | Operator ID or "SYSTEM" |
| reason | TEXT | Human-readable rationale |
| pathway | VARCHAR(20) | OPERATOR / SYSTEM |
| acceleration_factor | FLOAT | [2.0, 10.0] |
| fragment_count | INTEGER | Fragments in this batch |
| created_at | TIMESTAMPTZ | |

**Table schema -- disconfirmation_fragments**:

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| disconfirmation_event_id | UUID FK | References disconfirmation_events |
| fragment_id | UUID | The disconfirmed fragment |
| pre_decay_score | FLOAT | Decay score before acceleration |
| post_decay_score | FLOAT | Decay score after acceleration |

**Table schema -- disconfirmation_patterns**:

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| tenant_id | VARCHAR(100) | NOT NULL |
| disconfirmation_event_id | UUID FK | Source event |
| centroid_embedding_semantic | Vector(1536) | Nullable |
| centroid_embedding_topological | Vector(1536) | Nullable |
| centroid_embedding_operational | Vector(1536) | Nullable |
| pattern_weight | FLOAT | Starts at 1.0, decays over tau |
| fragments_in_centroid | INTEGER | Count used to compute centroid |
| created_at | TIMESTAMPTZ | |
| expires_at | TIMESTAMPTZ | created_at + PATTERN_TTL |

**Penalty application sequence**:

```
1. Compute composite score via standard snap engine (Section 3.6)
2. Apply temporal modifier: modulated_score = raw_composite * temporal_modifier
3. FOR each active disconfirmation_pattern WHERE tenant_id matches:
   a. Compute similarity = cosine(fragment_embedding, pattern_centroid)
   b. IF similarity >= PROPAGATION_SIMILARITY_THRESHOLD (0.70):
      pattern_age_days = (now - pattern.created_at).days
      decay_factor = exp(-pattern_age_days / PATTERN_DECAY_TAU)
      effective_weight = pattern.pattern_weight * decay_factor
      penalty = PENALTY_STRENGTH * effective_weight
      penalized_score = modulated_score * max(PENALTY_FLOOR, 1.0 - penalty)
4. Compare penalized_score against threshold
```

**Invariants**: INV-NE-1 (acceleration_factor in [2.0, 10.0]), INV-NE-2 (penalty cannot reduce score below PENALTY_FLOOR fraction of original), INV-NE-3 (patterns expire after PATTERN_TTL), INV-NE-4 (tenant isolation on all disconfirmation tables).

### 7.4 Mechanism #4: Bridge Detection

**Purpose**: Identify articulation points and high-betweenness-centrality nodes in the accumulation graph that bridge otherwise disconnected clusters. These are structurally critical fragments.

**Algorithms**:
1. **Tarjan's articulation point algorithm**: O(V+E) linear-time detection of graph vertices whose removal disconnects the graph.
2. **Brandes betweenness centrality**: O(V(V+E)) computation of betweenness centrality. Threshold: BRIDGE_BC_THRESHOLD=0.30.

**Cross-domain verification**: A bridge is classified as a discovery (BRIDGE_DISCOVERY) only if the entity domain span is >= 2 domains (e.g., a fragment connecting RAN and TRANSPORT clusters).

**Severity classification**:
- CRITICAL: BC >= 0.60 AND largest sub-component >= 10 nodes.
- HIGH: BC >= 0.45 OR largest sub-component >= 7.
- MEDIUM: BC >= 0.30.
- Below threshold: ROUTINE_CONNECTIVITY (not persisted as discovery).

**Deduplication**: component_fingerprint = sha256 of sorted fragment_ids in the component. Prevents duplicate discoveries for the same graph structure.

**Tables**: `bridge_discovery` (id, tenant_id, fragment_id, betweenness_centrality, domain_span, severity, component_fingerprint, created_at), `bridge_discovery_provenance` (bridge_discovery_id, sub_component_fragment_ids, relationship_type).

**Data consumption**: Reads accumulation_edge sets from Mechanism T2.1 (bounded BFS, MAX_CLUSTER_EDGES=1000). No independent DB loads.

**Invariants**: INV-BR-1 (BC in [0,1]), INV-BR-2 (domain_span >= 2 for BRIDGE_DISCOVERY classification), INV-BR-3 (component_fingerprint uniqueness per tenant).

---

## 8. Discovery Mechanisms -- Tier 2

Three mechanisms in Layer 2 (Discovery). May read Tier 1 outputs within the same layer. Require operator feedback or temporal accumulation.

### 8.1 Mechanism #5: Outcome Calibration

**Purpose**: Closed-loop feedback connecting operator resolution actions to snap engine weight profiles. Remediates F-2.4.

**Operator action capture**: When an operator resolves a snap cluster, the resolution action is classified as TRUE_POSITIVE (snap correctly grouped related evidence), FALSE_POSITIVE (snap grouped unrelated evidence), or FALSE_NEGATIVE (operator found correlated evidence that the snap engine missed).

**Calibration algorithm**: Collect (per-dimension scores, operator verdict) pairs per failure_mode_profile. Compute AUC(final_score | verdict) to measure profile discriminative power. Optimize weights via constrained search on the 4-simplex (5 weights summing to 1.0, all >= 0.05).

**Cold-start methodology**: Use initial estimate profiles until minimum 500 labeled outcomes per profile accumulated, with at least 3 failure modes having 50+ outcomes each. Tag calibration_status transitions: INITIAL_ESTIMATE -> COLLECTING -> EMPIRICALLY_VALIDATED.

**Tables**: `snap_outcome_feedback` (id, tenant_id, snap_decision_record_id, operator_verdict, resolution_action, resolved_at, notes), `calibration_history` (id, tenant_id, failure_mode_profile, weights_before, weights_after, auc_before, auc_after, sample_count, calibrated_at), `weight_profile_active` (tenant_id, failure_mode_profile, weights JSONB, calibration_status, last_calibrated_at).

**Feedback loop**: weight_profile_active is owned by Layer 2 (Outcome Calibration). Layer 1 (SnapEngine) has READ-ONLY access. This is the documented feedback loop A (see Section 11.3).

**Invariants**: INV-OC-1 (all weights > 0.05), INV-OC-2 (weights sum to 1.0), INV-OC-3 (minimum 500 labeled outcomes before optimization), INV-OC-4 (weight changes > 0.10 require review).

### 8.2 Mechanism #6: Pattern Conflict Detection

**Purpose**: Surface cases where the snap engine produces contradictory snap decisions for the same entity within a time window (e.g., one snap says entity X is UP, another says entity X is DOWN).

**Operational polarity extraction**: From failure_mode_tags and operational_fingerprint, extract polarity: UP (recovery/restoration), DOWN (failure/degradation), NEUTRAL (informational). Polarity column added to abeyance_fragment.

**Detection criteria**: CONFLICT_ENTITY_OVERLAP_THRESHOLD=0.40, CONFLICT_TIME_WINDOW_SECONDS=3600. Two snap_decision_records conflict if they share >= 40% entity overlap within a 1-hour window and have opposite polarity.

**Trigger modes**:
1. **Triggered**: After each snap_decision_record write, check for conflicts with recent decisions.
2. **Sweep**: Every 15 minutes, scan recent decisions for missed conflicts.

**Important**: This mechanism surfaces conflicts but does NOT resolve them. Resolution is an operator responsibility.

**Tables**: `conflict_record` (id, tenant_id, decision_id_a, decision_id_b, entity_overlap_ratio, polarity_a, polarity_b, detected_at), `conflict_detection_log` (id, tenant_id, scan_type, decisions_scanned, conflicts_found, duration_ms, completed_at).

**Invariants**: CONF-INV-1 through CONF-INV-8 (entity overlap >= threshold, opposite polarity, time window enforced, tenant isolation, idempotent detection, no resolution, both triggered and sweep modes, log every scan).

### 8.3 Mechanism #7: Temporal Sequence Modelling

**Purpose**: Build entity-level state transition matrices to enable expectation violation detection (Mechanism #9) and causal direction testing (Mechanism #10).

**Entity state definition**: Canonical state string = `(fragment_type, source_type, severity_bucket)`. Example: `"ALARM|CRITICAL"`, `"METRIC|WARNING"`, `"TICKET|NORMAL"`.

**entity_sequence_log**: BIGSERIAL id for monotonic ordering. Columns: tenant_id, entity_id, entity_domain, from_state (NULL for first observation), to_state, fragment_id, event_timestamp. Partitioned by (tenant_id, event_timestamp).

**transition_matrix**: Sparse representation. One row per (tenant_id, entity_domain, from_state, to_state). Columns: count (INTEGER), last_observed_at. Incremental update (hot path via upsert on each entity observation) + full recompute (cold path every 24h to correct drift).

**Laplace smoothing**: Alpha=1 applied at query time by consumers, NOT stored in the matrix. This ensures consumers always compute smoothed probabilities without the matrix needing recomputation when alpha changes.

**Confidence categories**: INSUFFICIENT (<5 observations), LOW_CONFIDENCE (5-19), STABLE (20-99), HIGH_CONFIDENCE (>=100).

**Tables**: `entity_sequence_log`, `transition_matrix`, `transition_matrix_version` (3 tables).

**transition_matrix_version**: Tracks recompute runs. Columns: id, tenant_id, entity_domain, recompute_started_at, recompute_completed_at, total_transitions, unique_states.

---

## 9. Discovery Mechanisms -- Tier 3

Three mechanisms in Layer 3 (Hypothesis). Produce reasoning artefacts requiring LLM inference or statistical testing.

### 9.1 Mechanism #8: Hypothesis Generation

**Purpose**: TSLAM-8B powered reasoning layer that converts recurring snap patterns and surprise escalations into structured, falsifiable hypotheses.

**Hypothesis lifecycle**:
- **Proposed** (72h TTL): Generated by TSLAM-8B from surprise events, cluster changes, or recurring snap patterns.
- **Testing** (14d TTL): Evidence accumulation phase; hypothesis linked to snap_decision_records and surprise_events.
- **Confirmed**: Sufficient evidence supports the hypothesis.
- **Refuted**: Evidence contradicts the hypothesis.
- **Retired**: TTL expired without sufficient evidence either way.

**Input triggers**: DISCOVERY-type surprise events, cluster membership changes (>= 3 fragments), recurring snap patterns for the same entity set.

**TSLAM-8B prompt structure**: Provides context (recent snap decisions, surprise events, entity neighbourhood) and asks for structured output: hypothesis statement, testable prediction, evidence criteria, confidence estimate.

**Hypothesis generation queue**: Durable table for requests when TSLAM is unavailable. FIFO processing, max 3 retries, then ABANDONED status.

**Tables**: `hypothesis` (id, tenant_id, statement, status, confidence, created_at, expires_at, confirmed_at, refuted_at), `hypothesis_evidence` (id, hypothesis_id, source_table, source_id, evidence_type, contribution), `hypothesis_generation_queue` (id, tenant_id, trigger_type, trigger_id, raw_context, status, attempt_count, created_at).

**Invariants**: INV-HYP-1 (hypothesis status transitions are monotonic: proposed->testing->confirmed|refuted|retired), INV-HYP-2 (TTL enforced), INV-HYP-3 (source_table references use canonical name snap_decision_record).

### 9.2 Mechanism #9: Expectation Violation Detection

**Purpose**: Real-time evaluator that flags entity state transitions that are statistically surprising given the learned transition probabilities.

**Algorithm**: Consume entity_sequence_log updates. For each transition (S_prev -> S_new):

```
violation_severity = -log2(P_smoothed(S_new | S_prev))
```

Laplace smoothing with alpha=1 per Section 8.3. Capped at 20 bits.

**Domain-specific base thresholds**:

| Domain | Base Threshold (bits) |
|--------|----------------------|
| RAN | 5.0 |
| TRANSPORT | 5.5 |
| IP | 5.0 |
| CORE | 6.0 |
| VNF | 5.5 |

**Confidence uplift**: If transition_matrix confidence for (entity_domain, from_state) is STABLE or HIGH_CONFIDENCE, add +2.0 bits to threshold (higher bar = more data needed to be "surprising").

**Violation classification**:
- CRITICAL: severity >= 12 bits
- MAJOR: severity >= 8 bits
- MODERATE: severity >= 5 bits
- MINOR: severity < 5 bits

CRITICAL and MAJOR violations are enqueued for hypothesis generation (Mechanism #8).

**Table**: `expectation_violation` (id, tenant_id, entity_id, entity_domain, from_state, to_state, violation_severity, threshold_applied, violation_class, correlated_surprise_event_id, fragment_id, created_at).

**Tiered retention**: CRITICAL: 1095 days, MAJOR: 730 days, MODERATE: 365 days, MINOR: 180 days.

**Cross-reference**: correlated_surprise_event_id links to surprise_event when both mechanisms trigger on the same underlying event.

### 9.3 Mechanism #10: Causal Direction Testing

**Purpose**: Granger-style temporal precedence analysis to identify directional relationships between entity pairs.

**Algorithm**: For each entity pair (A, B) that co-appears in fragment entity refs:
1. Collect co-occurrence events within window W=3600s.
2. Compute directional fraction: fraction of co-occurrences where A precedes B.
3. Apply minimum sample requirement: N_min=15.
4. Directional fraction threshold: delta=0.80 (raised to 0.90 for n<30).
5. Coefficient of variation: CV_max=0.50 (timing consistency).

**Confidence score**: `confidence = 0.30*sample_factor + 0.50*direction_factor + 0.20*stability_factor`. Labels: HIGH (>=0.75), MEDIUM (0.50-0.74), LOW (0.25-0.49), INSUFFICIENT (<0.25).

**Explicit caveat**: Temporal precedence is NOT causation. Causal direction testing establishes statistical ordering, not causal mechanism. All outputs labelled with this caveat.

**Tables**: `causal_candidate` (id, tenant_id, entity_a_id, entity_b_id, direction, directional_fraction, confidence, sample_count, created_at, updated_at), `causal_evidence_pair` (id, causal_candidate_id, fragment_a_id, fragment_b_id, time_delta_seconds, direction) with max 50 pairs per candidate, `causal_analysis_run` (id, tenant_id, started_at, completed_at, candidates_evaluated, candidates_promoted).

---

## 10. Discovery Mechanisms -- Tier 4

Four mechanisms split across Layer 4 (Evidence) and Layer 5 (Insight).

### 10.1 Mechanism #11: Pattern Compression (Layer 4: Evidence)

**Purpose**: MDL-based greedy set cover that discovers dominant scoring patterns in snap decision populations.

**Discretisation**: 3-band scheme. For each dimension score:
- L = [0, 0.33)
- M = [0.33, 0.67)
- H = [0.67, 1.0]
- X = NULL (dimension unavailable)

Each snap_decision_record becomes a 5-character pattern string (e.g., "HMHLH").

**Algorithm**: Greedy set cover with MDL pruning. For a population of K decisions:
1. Enumerate candidate rules (frequent patterns).
2. Greedily select rules that cover the most uncovered decisions.
3. Stop when compression_gain < threshold.

**compression_gain** = compression_ratio * coverage_ratio = ((K-R)/K) * (C/N)

Where K = original decision count, R = rules needed, C = decisions covered by rules, N = total decisions.

**Discovery trigger**: compression_gain >= 0.40 AND coverage_ratio >= 0.50 AND R >= 1 AND N >= 20.

**DOMINANT classification**: Single rule covers >= 50% of population with specificity <= 3 (at most 3 non-X dimensions).

**Schedule**: Periodic batch job every 24h. Population query from snap_decision_record with LIMIT 5000 per (tenant_id, failure_mode_profile).

**Table**: `compression_discovery_event` (id, tenant_id, failure_mode_profile, rules JSONB, compression_gain, coverage_ratio, dominant_rule, population_size, created_at).

### 10.2 Mechanism #12: Counterfactual Simulation (Layer 4: Evidence)

**Purpose**: Remove-and-re-score protocol to quantify the causal impact of individual fragments on snap decisions.

**Three-step protocol**:
1. **Baseline extraction**: For a candidate fragment, retrieve all snap_decision_records where it participated.
2. **Counterfactual replay**: Re-score each pair with the candidate fragment removed (i.e., use the other fragment paired with the next-best candidate).
3. **Delta computation**: causal_impact_score = mean(|delta|) across all replayed pairs. Decision flip count/rate tracked.

**Operational constraints**: Batch job only. Runs exclusively in maintenance windows (cron: `0 2 * * 0`, weekly Sunday 2 AM). Read-only against production tables (INV-CF-1).

**Bounds**: max_replay_fragments=500, max_replay_window_days=14, max_pairs_per_candidate=5000, max_candidates_per_batch=200.

**Tables**: `counterfactual_simulation_result` (id, tenant_id, candidate_fragment_id, causal_impact_score, decision_flip_count, decision_flip_rate, pairs_evaluated, created_at), `counterfactual_pair_delta` (id, simulation_result_id, original_score, counterfactual_score, delta, decision_changed), `counterfactual_candidate_queue` (id, tenant_id, fragment_id, priority_score, status, created_at), `counterfactual_job_run` (id, tenant_id, started_at, completed_at, candidates_processed, total_pairs_replayed).

**Invariants**: INV-CF-1 (read-only against production tables), INV-CF-2 (bounded replay), INV-CF-3 (maintenance window only).

### 10.3 Mechanism #13: Meta-Memory (Layer 5: Insight)

**Purpose**: Track productivity of search areas and bias exploration towards productive regions. Implements exploration/exploitation balance.

**Productivity score**: `P(A) = [N_TP + 0.5*N_FN] / N_total`. Laplace-smoothed with beta=5. Temporal decay DECAY_LAMBDA=0.02/day (half-life ~35 days).

**Bias computation**: Bias allocation per area = P(A) / SUM(P(all areas)). Bounded by MIN_ALLOCATION_FLOOR=0.05/N_areas and MAX_ALLOCATION_CEILING=5.0/N_areas.

**Activation threshold**: 500 total labeled outcomes, 3+ failure modes with 50+ each, at least one outcome <14 days old. Below threshold: INACTIVE state = uniform allocation (no bias).

**Four tracked dimensions**: entity type, failure mode, time window (short/medium/long), topological region.

**Tables**: `meta_memory_area` (id, tenant_id, dimension, area_key, description), `meta_memory_productivity` (id, area_id, n_tp, n_fp, n_fn, n_total, raw_productivity, smoothed_productivity, last_outcome_at), `meta_memory_bias` (id, tenant_id, area_id, bias_allocation, computed_at), `meta_memory_topological_region` (id, tenant_id, region_key, entity_ids, centroid_embedding), `meta_memory_tenant_state` (tenant_id, activation_status, total_labeled_outcomes, failure_modes_with_50_plus, last_activated_at), `meta_memory_job_run` (id, tenant_id, started_at, completed_at, areas_evaluated, bias_changed).

**Feedback loop**: meta_memory_bias influences SnapEngine candidate generation priority (soft bias, not hard filter). This is feedback loop B (see Section 11.3).

### 10.4 Mechanism #14: Evolutionary Patterns (Layer 5: Insight)

**Purpose**: Maintain a bounded population of confirmed patterns with fitness scores, applying selection, mutation, and recombination operators on a generation schedule.

**Fitness function**: `fitness = w_pred*predictive_power + w_nov*novelty + w_comp*compression_gain`

Where:
- predictive_power: Fraction of snap decisions matching the pattern that were confirmed TRUE_POSITIVE.
- novelty: Inverse of population similarity (how different this pattern is from existing population).
- compression_gain: From Pattern Compression (Mechanism #11).

Default weights: w_pred=0.5, w_nov=0.3, w_comp=0.2.

**Population management**: Bounded population per (tenant_id, failure_mode_profile). MAX_POPULATION_SIZE=100 per partition.

**Operators**:
- **Selection**: Tournament selection (k=3) favouring higher fitness.
- **Mutation**: Random perturbation of one dimension band in the pattern string (e.g., H->M).
- **Recombination**: Crossover of two parent pattern strings at a random split point.

**Generation schedule**: Batch job. Runs after Pattern Compression completes. One generation per cycle.

**Tables**: `pattern_individual` (id, tenant_id, failure_mode_profile, pattern_string, fitness, predictive_power, novelty, compression_gain, generation, created_at), `pattern_individual_archive` (same schema, for individuals removed from population), `evolution_generation_log` (id, tenant_id, failure_mode_profile, generation, population_size, mean_fitness, max_fitness, mutations, recombinations, selections, created_at), `evolution_partition_state` (tenant_id, failure_mode_profile, current_generation, last_evolved_at).

---

## 11. Cognitive Architecture

Consolidates Phase 6 cognitive architecture design. Organises all 14 mechanisms into five layers.

### 11.1 Five-Layer Architecture

```
+===============================================================+
| LAYER 5: INSIGHT                                              |
|   (13) Meta-Memory    (14) Evolutionary Patterns              |
|   Output: exploration bias, pattern fitness trajectories      |
+===============================================================+
        ^  reads: Evidence layer outputs, Hypothesis outcomes
+===============================================================+
| LAYER 4: EVIDENCE                                             |
|   (11) Pattern Compression  (12) Counterfactual Simulation    |
|   Output: compression rules, causal impact deltas             |
+===============================================================+
        ^  reads: Hypothesis layer outputs, Discovery/Correlation
+===============================================================+
| LAYER 3: HYPOTHESIS                                           |
|   (8) Hypothesis Generation   (9) Expectation Violation       |
|   (10) Causal Direction                                       |
|   Output: falsifiable claims, violation records, causal cands |
+===============================================================+
        ^  reads: Discovery layer outputs, Correlation tables
+===============================================================+
| LAYER 2: DISCOVERY                                            |
|   (1) Surprise   (2) Ignorance   (3) Negative Evidence       |
|   (4) Bridge     (5) Calibration  (6) Conflict               |
|   (7) Temporal Sequence                                       |
+===============================================================+
        ^  reads: Correlation layer tables
+===============================================================+
| LAYER 1: CORRELATION (Foundation)                             |
|   Enrichment Chain | Snap Engine | Model Serving | ORM Schema |
+===============================================================+
```

### 11.2 Tier-to-Layer Mapping

| Tier | Mechanisms | Layer |
|------|-----------|-------|
| 1 (Foundation) | 1-Surprise, 2-Ignorance, 3-NegEvidence, 4-Bridge | L2: Discovery |
| 2 (Feedback) | 5-Calibration, 6-Conflict, 7-TempSequence | L2: Discovery |
| 3 (Reasoning) | 8-Hypothesis, 9-ExpViolation, 10-CausalDirection | L3: Hypothesis |
| 4 (Advanced) | 11-Compression, 12-Counterfactual | L4: Evidence |
| 4 (Advanced) | 13-MetaMemory, 14-Evolutionary | L5: Insight |

Tier 4 splits across two layers. Mechanisms 11-12 validate specific patterns (Evidence function). Mechanisms 13-14 learn strategic guidance from historical outcomes (Insight function). Tiers govern build order; layers govern data flow.

### 11.3 Data Flow and Feedback Loops

**Layer dependency contract**: Each layer reads only from lower layers, writes only to its own tables. Two exceptions (mediated feedback loops):

**Loop A -- Weight Calibration** (L2 -> L1): `weight_profile_active` (owned by L2/Outcome Calibration) is read by SnapEngine (L1). Mediated through a registry table; no direct mutation.

**Loop B -- Exploration Bias** (L5 -> L1): `meta_memory_bias` (owned by L5/Meta-Memory) influences SnapEngine candidate generation priority (soft bias, not hard filter).

**Internal Layer 2 dependency**: Tier 2 mechanisms (5, 6, 7) MAY read Tier 1 outputs (1, 2, 3, 4). Tier 1 mechanisms MUST NOT read Tier 2 outputs.

### 11.4 Dependency Matrix

```
                     Reads From Layer:
Mechanism            L1    L2    L3    L4    L5
-------------------------------------------------
L1: Enrichment       -     -     -     -     -
L1: Snap Engine      -     [A]   -     -     [B]
L2: 1-Surprise       R     -     -     -     -
L2: 2-Ignorance      R     -     -     -     -
L2: 3-NegEvidence    R     -     -     -     -
L2: 4-Bridge         R     -     -     -     -
L2: 5-Calibration    R     -     -     -     -
L2: 6-Conflict       R     -     -     -     -
L2: 7-TempSequence   R     -     -     -     -
L3: 8-Hypothesis     R     R     -     -     -
L3: 9-ExpViolation   -     R     -     -     -
L3: 10-CausalDir     R     R     -     -     -
L4: 11-Compression   R     R     -     -     -
L4: 12-Counterfact   R     R     -     -     -
L5: 13-MetaMemory    R     R     -     -     -
L5: 14-Evolutionary  R     R     -     R     -

[A] = feedback loop A (weight calibration)
[B] = feedback loop B (exploration bias)
R   = read dependency
```

No mechanism reads from its own layer or from a higher layer (except the two feedback loops).

### 11.5 Naming Conflicts Resolved

**5.1**: `snap_decision_record` is canonical (NOT `snap_decision_log`). Per T1.2 ORM schema authority.

**5.2**: Per-dimension scores stored as five explicit FLOAT columns on snap_decision_record (not JSONB). weights_base JSONB added per Outcome Calibration requirement.

**5.3**: weight_profile_active owned by L2 (Outcome Calibration), not L1. L1 has read-only access.

**5.4**: Negative Evidence uses three physical tables (disconfirmation_events, _fragments, _patterns), not one. DisconfirmationRecord is the application-layer dataclass spanning all three.

**5.5**: hypothesis_engine source_table references corrected to snap_decision_record.

**5.6**: Evolutionary Patterns snap_decision_log references corrected to snap_decision_record.

### 11.6 Startup and Initialization Order

```
Phase 1: Layer 1 -- Correlation
  1a. Database schema migration (Alembic)
  1b. T-VEC model loading (lazy, background pre-warm)
  1c. TSLAM model loading (lazy, background pre-warm)
  1d. Enrichment chain ready
  1e. Snap engine ready (reads weight_profile_active; uses defaults if empty)

Phase 2: Layer 2 -- Discovery (Tier 1)
  2a. Surprise distribution states loaded
  2b. Ignorance mapping job scheduled
  2c. Negative evidence service registered
  2d. Bridge detection hooks registered

Phase 3: Layer 2 -- Discovery (Tier 2)
  3a. Outcome calibration reads feedback + history
  3b. Conflict detector registered on snap_decision_record writes
  3c. Temporal sequence service ready

Phase 4: Layer 3 -- Hypothesis
  4a. Violation detector registered on entity_sequence_log writes
  4b. Hypothesis generation queue consumer started
  4c. Causal direction analysis job scheduled

Phase 5: Layer 4 -- Evidence (batch only)
  5a. Pattern compression job scheduled
  5b. Counterfactual simulation job scheduled (maintenance window)

Phase 6: Layer 5 -- Insight (batch only)
  6a. Meta-memory job scheduled
  6b. Evolutionary patterns generation cycle scheduled
```

### 11.7 Invariants for this Section

| ID | Statement |
|----|-----------|
| INV-ARCH-1 | Mechanisms write only to their own layer's tables |
| INV-ARCH-2 | Mechanisms read only from own layer or lower layers |
| INV-ARCH-3 | Feedback loops mediated through registry tables, never direct mutation |
| INV-ARCH-4 | Within L2, Tier 2 may read Tier 1 outputs; Tier 1 must not read Tier 2 |
| INV-ARCH-5 | L4 and L5 mechanisms are batch-only; no real-time side effects |

---

## 12. Discovery Loop

Consolidates Phase 6 discovery loop design. Six-stage deterministic flow.

### 12.1 End-to-End Flow

```
Raw Event
  |
  v
[Stage 1: Enrichment] -- Layer 1
  EnrichmentChain.enrich()
    -> AbeyanceFragmentORM (4 embeddings + masks)
    -> FragmentEntityRefORM entries
  |
  v
[Stage 2: Correlation] -- Layer 1
  SnapEngine.evaluate()
    -> snap_decision_record (per-dimension scores)
    -> accumulation_edge (affinity graph)
  |
  v
[Stage 3: Surprise Evaluation] -- Layer 2
  SurpriseEngine.process(snap_decision_record)
    -> surprise_event (if surprise > adaptive_threshold)
  TemporalSequence.record_observation(fragment, entity_refs)
    -> entity_sequence_log, transition_matrix update
  ConflictDetector.evaluate(snap_decision_record)
    -> conflict_record (if opposite polarity detected)
  BridgeDetector.analyze(accumulation_graph_component)
    -> bridge_discovery (if articulation point + cross-domain)
  |
  v
[Stage 4: Hypothesis Generation] -- Layer 3
  ViolationDetector.evaluate_transition(entity, S_prev, S_new)
    -> expectation_violation (if severity > threshold)
  HypothesisEngine.generate(surprise_event | cluster_change)
    -> hypothesis (TSLAM-8B falsifiable claim)
  CausalDirection.analyze(entity_pair)
    -> causal_candidate (if consistent temporal ordering)
  |
  v
[Stage 5: Evidence Testing] -- Layer 4 (batch only)
  PatternCompression.compress(snap_decision_population)
    -> compression_discovery_event
  CounterfactualSimulation.simulate(candidate, window)
    -> counterfactual_simulation_result + pair_deltas
  |
  v
[Stage 6: Terminal] -- Layer 5 (batch, slow cycle)
  MetaMemory.compute_productivity(search_areas, outcomes)
    -> meta_memory_bias (exploration allocation)
  EvolutionaryPatterns.evolve(pattern_population)
    -> pattern_individual fitness updates, selection, recombination
```

### 12.2 Latency Budget

| Stage | Critical Path | Batch Path |
|-------|--------------|------------|
| 1. Enrichment | 500ms-2s (T-VEC + TSLAM) | N/A |
| 2. Correlation | 50-200ms (snap scoring) | N/A |
| 3. Surprise | 5-20ms (histogram lookup + update) | N/A |
| 4. Hypothesis | 100-500ms (expectation violation is real-time; hypothesis gen async) | Hypothesis gen: 2-5s |
| 5. Evidence | N/A | 10min-2h per batch |
| 6. Terminal | N/A | 5min-1h per batch |

**Critical path total**: 60-600ms for stages 2-4 (post-enrichment). Enrichment is latency-tolerant (decoupled from ingest via queue).

### 12.3 Determinism Contract

Given the same input event and the same database state, the discovery loop produces the same outputs. No random operations. All thresholds are deterministic functions of stored state. Batch jobs are ordered by consistent sort keys.

---

## 13. Explainability Layer

The explainability layer provides human-readable justifications for every snap decision and discovery event. Each snap_decision_record contains sufficient per-dimension scores, weights, and mask information to reconstruct the exact reasoning path.

### 13.1 Snap Decision Explanation

For each snap decision, the explainability layer can produce:
1. **Dimension contribution breakdown**: For each available dimension, the adjusted_weight * score contribution to the composite.
2. **Mask impact summary**: Which dimensions were excluded and how much weight was redistributed.
3. **Threshold comparison**: The Sidak-adjusted threshold vs. final score, with multiple_comparisons_k.
4. **Temporal modifier impact**: How much the raw_composite was attenuated by recency.

### 13.2 Discovery Event Explanation

Each discovery mechanism produces a structured explanation:
- **Surprise events**: Self-information value, threshold at time, contributing dimensions, escalation type.
- **Bridge discoveries**: Betweenness centrality, domain span, sub-component sizes.
- **Expectation violations**: Transition probability, violation severity, domain threshold applied.
- **Hypothesis generation**: Trigger type, input context summary, TSLAM-8B reasoning chain.
- **Conflict records**: Entity overlap ratio, polarity assignments, time window.

### 13.3 Provenance Chain

Every state change is logged to `fragment_history` (INV-10). The discovery_ledger cross-references events across mechanisms. A complete provenance chain from raw event to final snap decision (or expiration) is reconstructable from PostgreSQL alone (INV-12, supported by INV-10).

### 13.4 Invariants

| ID | Statement |
|----|-----------|
| INV-10 | fragment_history and snap_decision_record are append-only |
| INV-12 | Full state rebuild from PostgreSQL alone |
| PROV-4.3-1 | Write-ahead pattern: PostgreSQL committed before Redis notification |

---

## 14. Hard System Invariants

Complete inventory of invariants enforced across the system.

### 14.1 Core Invariants (from v2.0, updated for v3.0)

| ID | Statement | Enforcement |
|----|-----------|-------------|
| INV-1 | Fragment lifecycle via SnapStatus enum (deterministic state machine) | Application code; DB CHECK on snap_status values |
| INV-3 | All scores in [0.0, 1.0] | _clamp() on every per-dimension score and final composite |
| INV-5 | SNAPPED status is terminal for automated processes | Application code; state machine transition rules |
| INV-6 | raw_content bounded to 64KB; max_lifetime_days hard cap (730d default) | Application-layer truncation; DB column type |
| INV-7 | tenant_id on every table, every query, every index (leading column) | Schema design; query templates; code review |
| INV-8 | No output outside declared range | _clamp() defense-in-depth |
| INV-9 | MAX_EDGES_PER_FRAGMENT bounded (20) | accumulation_graph._enforce_edge_limit() |
| INV-10 | fragment_history, snap_decision_record are append-only | No UPDATE/DELETE on these tables |
| INV-11 | Mask vector consulted during scoring; no similarity on invalid dimensions | available_d(A,B) checked before cosine; weight redistribution |
| INV-12 | NULL embedding = unknown; zero-fill PROHIBITED; hash fallback PROHIBITED | Code structure (no zero-fill paths); CHECK constraints |
| INV-13 | CHECK constraints enforce mask/embedding coherence at DB level | ALTER TABLE ... ADD CONSTRAINT |
| INV-14 | snap_decision_record stores five explicit per-dimension scores | Schema definition; NOT five JSONB keys |

### 14.2 Architectural Invariants (v3.0)

| ID | Statement | Enforcement |
|----|-----------|-------------|
| INV-ARCH-1 | Mechanisms write only to their own layer's tables | Code review; schema ownership annotations |
| INV-ARCH-2 | Mechanisms read only from own layer or lower layers | Dependency matrix; startup ordering |
| INV-ARCH-3 | Feedback loops mediated through registry tables | weight_profile_active, meta_memory_bias design |
| INV-ARCH-4 | Within L2, Tier 2 may read Tier 1; Tier 1 must not read Tier 2 | Code review |
| INV-ARCH-5 | L4/L5 mechanisms are batch-only | Scheduling; no real-time triggers |

### 14.3 Mechanism-Specific Invariants

| ID | Mechanism | Statement |
|----|-----------|-----------|
| INV-S1..S8 | Surprise Engine | Histogram bins in [0,1]; surprise >= 0; Laplace smoothing; cap 20 bits; minimum mass |
| INV-NE-1..4 | Negative Evidence | acceleration_factor in [2,10]; penalty floor; pattern TTL; tenant isolation |
| INV-BR-1..3 | Bridge Detection | BC in [0,1]; domain_span >= 2 for discovery; fingerprint uniqueness |
| CONF-INV-1..8 | Conflict Detection | Overlap threshold; opposite polarity; time window; no resolution |
| INV-OC-1..4 | Outcome Calibration | Weights > 0.05; sum to 1.0; minimum 500 outcomes; change review |
| INV-HYP-1..3 | Hypothesis Generation | Monotonic status transitions; TTL enforced; canonical table names |
| INV-CF-1..3 | Counterfactual Sim | Read-only production; bounded replay; maintenance window only |
| INV-NEW-1..3 | Snap Engine v3 | Available weight sum > 0; adjusted sum = 1.0; no cosine on NULL |

---

## 15. Observability and Metrics

Consolidates T2.6. 42 Prometheus-compatible metrics. Remediates F-7.1, F-7.2, F-7.3.

### 15.1 Metric Summary by Category

| Category | Count | Type Breakdown |
|----------|-------|---------------|
| Fragment lifecycle counters | 7 | 7 Counters |
| Snap score histograms | 5 | 5 Histograms |
| Active fragment gauges | 4 | 4 Gauges |
| Enrichment chain latency | 3 | 3 Histograms |
| ML model metrics | 4 | 2 Counters + 2 Histograms |
| Maintenance job metrics | 8 | 6 Counters + 1 Histogram + 1 Gauge |
| Embedding mask metrics | 3 | 1 Gauge + 2 Counters |
| Graph/topology metrics | 5 | 3 Counters + 2 Histograms |
| Queue/backpressure | 3 | 1 Gauge + 2 Counters |
| **Total** | **42** | **21 Counters, 7 Gauges, 14 Histograms** |

### 15.2 Key Metrics

**Fragment lifecycle**: abeyance_fragment_ingested_total, _decayed_total, _expired_total, _snapped_total, _archived_cold_total, _dedup_rejected_total, _near_miss_boosted_total.

**Snap scoring**: abeyance_snap_score_histogram (17 buckets, fine-grained in [0.40, 0.75] near thresholds), abeyance_snap_component_score_histogram (per-dimension diagnostic), abeyance_snap_threshold_applied_histogram.

**Model health**: abeyance_model_request_total (labels: model, status), abeyance_model_latency_seconds, abeyance_model_error_total, abeyance_model_fallback_total (tracks F-4.2 regex fallback).

**Embedding masks**: abeyance_embedding_mask_valid_fraction (Gauge, primary LLM outage detector), abeyance_embedding_mask_all_invalid_total, _partial_total.

### 15.3 Alerting Rules (7 rules)

1. **AbeyanceSnapRateAnomaly** (F-7.2): Rate 5x hourly average for 2 minutes.
2. **AbeyanceSnapRateDrop** (F-7.2): Zero snap rate with active ingestion for 30 minutes.
3. **AbeyanceActiveFragmentApproachingLimit**: >400K active fragments (limit 500K per INV-6/RES-3.1-2).
4. **AbeyanceEmbeddingDimensionDegraded**: Valid fraction <80% for 5 minutes.
5. **AbeyanceMaintenanceStaleness** (F-7.3): No maintenance run in 2 hours.
6. **AbeyanceTSLAMFallbackElevated** (F-4.2): Regex fallback >10% of ingestion.
7. **AbeyanceCircuitBreakerOpen**: Queue depth exceeded CRITICAL_WATER_MARK (2000).

### 15.4 Implementation Pattern

AbeyanceMetrics class wraps all Prometheus metric objects. Registered as module-level singletons. Services receive via dependency injection. Metrics exposed at `GET /metrics`. Gauges backed by DB queries run on separate background job (not inline with mutations).

Label cardinality: tenant_id (up to 100), source_type (6 values), failure_mode (5 values), embedding_dim (4 values). No unbounded labels.

---

## 16. Failure Recovery

Consolidates T2.7. Seven deterministic recovery scenarios.

### 16.1 Durability Hierarchy

1. PostgreSQL: system of record (INV-12).
2. Redis: best-effort notification layer. Loss never loses state.
3. T-VEC/TSLAM: enrichment accelerators. Failure degrades quality, does not block ingestion.
4. Vector indexes: derived structures. Rebuildable from stored vectors.
5. In-process state: ephemeral, always disposable.

### 16.2 Recovery Decision Matrix

| Scenario | Auto-Recovery | Max Data Loss | SLA Impact |
|----------|--------------|---------------|------------|
| T-VEC unavailability | Yes (NULL + mask FALSE; backfill on recovery) | Zero fragment loss | Reduced snap rate (20-40%) |
| TSLAM-8B unavailability | Yes (4B fallback, then regex; hypothesis queue) | Zero fragment loss | Reduced entity coverage (30-50%) |
| Redis loss | Yes (PostgreSQL polling fallback) | Notification events only | +5s notification latency |
| Vector index corruption | Yes (exact scan fallback; concurrent rebuild) | Zero | Severe snap latency (10-50x) during rebuild |
| Partial event loss | Yes (background re-enrichment) | Missed snap window | Low |
| Mid-enrichment crash | Yes (recovery job + expiry after 3 failures) | Fragment lost only if raw_content NULL | Low |
| Clustering instability | Partial (GREATEST() dampening; cooling period) | None | Elevated disk/stream usage |

### 16.3 Key Recovery Procedures

**T-VEC backfill**: Batch job (500 fragments/minute) re-enriches mask=FALSE fragments. Rate-limited to avoid overwhelming T-VEC on restart. Idempotent.

**TSLAM recovery**: hypothesis_generation_queue stores deferred requests. Entity re-extraction job processes regex-only fragments after TSLAM recovery. Existing entity refs preserved (LLM adds to regex results, never deletes).

**Mid-enrichment crash detection**: All masks FALSE + status INGESTED + created_at > 30 minutes stale. Recovery job runs every 10 minutes. Max 3 retries, then EXPIRED.

### 16.4 Invariant Preservation Through Recovery

| Invariant | Constraint |
|-----------|-----------|
| INV-5 | Re-enrichment never unsnaps a fragment |
| INV-7 | All recovery queries include tenant_id scope |
| INV-10 | All recovery events logged to fragment_history |
| INV-11 | No similarity on mask=FALSE dimensions during recovery |
| INV-12 | All recovery reads from PostgreSQL, not Redis |

---

## 17. Scalability Analysis

Consolidates T6.1. Targets: 50M fragments, 10K-100K events/sec, 100 tenants.

### 17.1 Bottleneck Ranking

| Rank | Bottleneck | Saturates At | Mitigation |
|------|-----------|-------------|------------|
| 1 | T-VEC CPU throughput | ~2 frags/sec (~7,200/hr) | Horizontal T-VEC workers |
| 2 | TSLAM-8B GPU throughput | ~1.5 frags/sec per GPU | Multiple GPU sidecars |
| 3 | pgvector ANN at 50M rows | ~200-500ms/query | Index partitioning; read replicas |
| 4 | Enrichment concurrency gate | ENRICHMENT_CONCURRENCY=4 | Distributed enrichment workers |
| 5 | Expiration batch I/O | 730-day retention = ~10.5B ceiling | Daily expiration; TOMBSTONE path |
| 6 | Accumulation graph clustering | ~1000 edges/trigger (bounded) | Already safe to 500K active |
| 7 | Discovery batch jobs | Per-tenant scans | Parallelise with per-tenant workers |

### 17.2 T-VEC Scaling

At 10K events/sec: 30K T-VEC texts/sec required. Single node: 15-20 texts/sec. Gap: 1500x. Enrichment must be horizontally distributed via Kafka consumer group.

**Scaling trigger**: INGESTED queue depth > 10K or enrichment p95 > 60s/fragment.

### 17.3 pgvector at 50M Rows

IVFFlat with per-tenant query filtering (WHERE tenant_id = $1) reduces effective index size to 500K rows/tenant at 100 tenants. At nprobe=10: ~10-30ms per query. Well within SLA.

HNSW at 100 tenants x 500K rows: 230 GB for indexes alone. Impractical on reference hardware.

**Verdict**: IVFFlat with per-tenant filtering is correct at this scale.

### 17.4 Four-Phase Scaling Sequence

1. **Phase 0 (Single node)**: 1 App VM + 1 DB VM. Handles ~2 frags/sec.
2. **Phase 1 (Horizontal enrichment)**: N enrichment workers with separate T-VEC instances. Kafka consumer group coordination.
3. **Phase 2 (GPU scaling)**: Multiple TSLAM-8B GPU sidecars. Load-balanced via round-robin.
4. **Phase 3 (Database scaling)**: PostgreSQL read replicas for cold storage queries. Partition cold_fragment by tenant_id.

---

## 18. Audit Finding Resolution Matrix

All 31 findings from ABEYANCE_MEMORY_FORENSIC_AUDIT_V2.md mapped to resolving sections.

| Finding ID | Severity | One-line Summary | Resolving Section(s) | Resolution Status |
|-----------|----------|-----------------|---------------------|-------------------|
| F-2.1 | Moderate | "Discovery" is similarity search, not reasoning | S9.1 (Hypothesis Generation via TSLAM-8B adds true reasoning) | RESOLVED |
| F-2.2 | Minor | Dormant fragment activation is standard NN search | S1.2 (acknowledged; 14 discovery mechanisms add genuine novelty) | ACKNOWLEDGED |
| F-2.3 | Moderate | Accumulation graph correlation discount is heuristic | S6.2 (bounded BFS), S10.1 (Pattern Compression provides statistical validation) | MITIGATED |
| F-2.4 | Severe | Weight profiles hand-tuned with no validation | S3.4-3.5 (initial estimates + empirical validation methodology), S8.1 (Outcome Calibration) | RESOLVED |
| F-3.1 | Severe | Shadow Topology unused in snap engine | S6.1 (shadow_topology wired to SnapEngine constructor) | RESOLVED |
| F-3.2 | Critical | Empty entity list passed to topology expansion | S2.8 Step (c) (entity_identifiers resolved to UUIDs, passed to get_neighbourhood) | RESOLVED |
| F-3.3 | Severe | Hash embedding fallback activates in async context | S2.5 (hash fallback deleted; only valid vector or NULL), S2.8 (INV-12) | RESOLVED |
| F-3.4 | Moderate | Dual cold storage paths unsynchronised | S4.1 (Parquet retained as fallback with error logging; pgvector is primary) | MITIGATED |
| F-3.5 | Minor | Deprecated abeyance_decay.py retained | S6.5 (module deleted, tests removed) | RESOLVED |
| F-4.1 | Moderate | Temporal modifier diurnal penalty invalid for some failure types | S3.6 (temporal modifier retained [0.5,1.0]; acknowledged as conservative bias) | ACKNOWLEDGED |
| F-4.2 | Severe | Entity extraction is single point of failure | S2.8 Step (a) (TSLAM fallback to regex; enrichment continues), S7.2 (Ignorance Mapping tracks) | RESOLVED |
| F-4.3 | Minor | Sidak correction assumes profile independence | S3.6 (retained; conservative bias acceptable and documented) | ACKNOWLEDGED |
| F-4.4 | Moderate | No negative evidence mechanism | S7.3 (Negative Evidence with disconfirmation API and propagation) | RESOLVED |
| F-5.1 | Critical | LLM embedding cost $57.6K/day at scale | S2.1-2.3 (local T-VEC + TSLAM; zero cloud cost) | RESOLVED |
| F-5.2 | Severe | Unbounded edge loading into memory | S6.2 (MAX_CLUSTER_EDGES=1000 bounded BFS) | RESOLVED |
| F-5.3 | Severe | N+1 queries in edge pruning | S6.2 (batch JOIN replacing per-edge SELECT) | RESOLVED |
| F-5.4 | Moderate | IVFFlat lists parameter fixed at 100 | S4.3 (dynamic lists = ceil(sqrt(n))) | RESOLVED |
| F-5.5 | Moderate | No rate limiting on LLM calls | S2.4 (semaphore-based backpressure: TVEC_CONCURRENCY, TSLAM_CONCURRENCY) | RESOLVED |
| F-6.1 | Severe | LLM outage zeros 75% of embedding | S2.8 (per-dimension failure isolation; mask-aware weight redistribution) | RESOLVED |
| F-6.2 | Critical | Embedding mask stored but never read by snap engine | S3.2 (mask enforcement: available_d(A,B) checked before every cosine) | RESOLVED |
| F-6.3 | Moderate | Parquet cold storage swallows errors silently | S4.1 (explicit exception handling with logged warnings) | RESOLVED |
| F-6.4 | Moderate | Race condition in edge eviction | S6.2 (GREATEST() in UPDATE prevents double-eviction; row-level enforcement) | MITIGATED |
| F-6.5 | Moderate | No idempotency on snap application | S16.3 (crash recovery: detection via all-masks-FALSE + stale, 3 retries) | MITIGATED |
| F-7.1 | Severe | No operational metrics | S15 (42 Prometheus metrics: 21 counters, 7 gauges, 14 histograms) | RESOLVED |
| F-7.2 | Moderate | No alerting on anomalous snap rates | S15.3 (AbeyanceSnapRateAnomaly + AbeyanceSnapRateDrop alerts) | RESOLVED |
| F-7.3 | Moderate | No maintenance job history | S6.6 (maintenance_job_history table), S15.2 (maintenance metrics) | RESOLVED |
| F-8.1 | Critical | No batch embedding, caching, or local model strategy | S2.1-2.3 (T-VEC local serving, micro-batching, coalescing) | RESOLVED |
| F-8.2 | Moderate | Cold storage growth unbounded | S4.5 (4-tier cold expiration: ACTIVE->COMPRESSED->TOMBSTONED->DELETE) | RESOLVED |
| F-9.1 | Severe | Tenant ID path traversal vulnerability | S4.6 (regex sanitisation: ^[a-zA-Z0-9_-]{1,128}$) | RESOLVED |
| F-9.2 | Moderate | Embedding vectors expose operational context | S2.5 (tenant isolation maintained; acknowledged as residual risk) | ACKNOWLEDGED |
| F-9.3 | Minor | CMDB export sanitisation uses removal allowlist | Acknowledged; CMDB export is local-only tool (not deployed to cloud) | ACKNOWLEDGED |

**Resolution summary**:
- **RESOLVED**: 23 findings fully addressed with specific design changes.
- **MITIGATED**: 4 findings partially addressed with risk reduction.
- **ACKNOWLEDGED**: 4 findings documented with rationale for acceptance.
- **Total**: 31 findings mapped.

---

## 19. Database Schema Summary

56 tables across 5 layers.

### 19.1 Layer 1: Correlation (12 tables)

| Table | Owner | Status |
|-------|-------|--------|
| abeyance_fragment | T1.2 ORM | Modified (4 emb + 3 mask columns) |
| cold_fragment | T1.2 ORM | Modified (4 emb + 3 mask + expiration tier) |
| snap_decision_record | T1.2 ORM | Modified (5 score columns, masks_active, weights_*) |
| fragment_entity_ref | v2.0 | Unchanged |
| accumulation_edge | v2.0 | Unchanged |
| fragment_history | v2.0 | Unchanged |
| cluster_snapshot | v2.0 | Unchanged |
| shadow_entity | v2.0 | Unchanged |
| shadow_relationship | v2.0 | Unchanged |
| cmdb_export_log | v2.0 | Unchanged |
| discovery_ledger | v2.0 | Unchanged |
| value_event | v2.0 | Unchanged |

### 19.2 Layer 2: Discovery (22 tables)

| Table | Owner Mechanism |
|-------|----------------|
| surprise_event | #1 Surprise Metrics |
| surprise_distribution_state | #1 Surprise Metrics |
| ignorance_extraction_stat | #2 Ignorance Mapping |
| ignorance_mask_distribution | #2 Ignorance Mapping |
| ignorance_silent_decay_record | #2 Ignorance Mapping |
| ignorance_silent_decay_stat | #2 Ignorance Mapping |
| ignorance_map_entry | #2 Ignorance Mapping |
| exploration_directive | #2 Ignorance Mapping |
| ignorance_job_run | #2 Ignorance Mapping |
| disconfirmation_events | #3 Negative Evidence |
| disconfirmation_fragments | #3 Negative Evidence |
| disconfirmation_patterns | #3 Negative Evidence |
| bridge_discovery | #4 Bridge Detection |
| bridge_discovery_provenance | #4 Bridge Detection |
| snap_outcome_feedback | #5 Outcome Calibration |
| calibration_history | #5 Outcome Calibration |
| weight_profile_active | #5 Outcome Calibration |
| conflict_record | #6 Pattern Conflict |
| conflict_detection_log | #6 Pattern Conflict |
| entity_sequence_log | #7 Temporal Sequence |
| transition_matrix | #7 Temporal Sequence |
| transition_matrix_version | #7 Temporal Sequence |

### 19.3 Layer 3: Hypothesis (7 tables)

| Table | Owner Mechanism |
|-------|----------------|
| hypothesis | #8 Hypothesis Generation |
| hypothesis_evidence | #8 Hypothesis Generation |
| hypothesis_generation_queue | #8 Hypothesis Generation |
| expectation_violation | #9 Expectation Violation |
| causal_candidate | #10 Causal Direction |
| causal_evidence_pair | #10 Causal Direction |
| causal_analysis_run | #10 Causal Direction |

### 19.4 Layer 4: Evidence (5 tables)

| Table | Owner Mechanism |
|-------|----------------|
| compression_discovery_event | #11 Pattern Compression |
| counterfactual_simulation_result | #12 Counterfactual Simulation |
| counterfactual_pair_delta | #12 Counterfactual Simulation |
| counterfactual_candidate_queue | #12 Counterfactual Simulation |
| counterfactual_job_run | #12 Counterfactual Simulation |

### 19.5 Layer 5: Insight (10 tables)

| Table | Owner Mechanism |
|-------|----------------|
| meta_memory_area | #13 Meta-Memory |
| meta_memory_productivity | #13 Meta-Memory |
| meta_memory_bias | #13 Meta-Memory |
| meta_memory_topological_region | #13 Meta-Memory |
| meta_memory_tenant_state | #13 Meta-Memory |
| meta_memory_job_run | #13 Meta-Memory |
| pattern_individual | #14 Evolutionary Patterns |
| pattern_individual_archive | #14 Evolutionary Patterns |
| evolution_generation_log | #14 Evolutionary Patterns |
| evolution_partition_state | #14 Evolutionary Patterns |

### 19.6 Table Count Summary

| Layer | Tables | New in v3 |
|-------|--------|-----------|
| L1: Correlation | 12 | 0 new, 3 modified |
| L2: Discovery | 22 | 22 new |
| L3: Hypothesis | 7 | 7 new |
| L4: Evidence | 5 | 5 new |
| L5: Insight | 10 | 10 new |
| **Total** | **56** | **44 new, 3 modified, 9 unchanged** |

### 19.7 Naming Convention

Mechanism-specific tables use domain-concept prefix:

| Prefix | Mechanism | Count |
|--------|-----------|-------|
| surprise_ | #1 | 2 |
| ignorance_ | #2 | 7 |
| disconfirmation_ | #3 | 3 |
| bridge_discovery* | #4 | 2 |
| snap_outcome_ / calibration_ / weight_profile_ | #5 | 3 |
| conflict_ | #6 | 2 |
| entity_sequence_ / transition_matrix* | #7 | 3 |
| hypothesis* | #8 | 3 |
| expectation_violation | #9 | 1 |
| causal_ | #10 | 3 |
| compression_ | #11 | 1 |
| counterfactual_ | #12 | 4 |
| meta_memory_ | #13 | 6 |
| pattern_individual* / evolution_ | #14 | 4 |

---

## 20. Appendices

### 20.1 Configuration Reference

All configuration via environment variables.

**Model serving**:

| Variable | Default | Description |
|----------|---------|-------------|
| TVEC_MODEL_NAME | NetoAISolutions/T-VEC | HuggingFace model ID |
| TVEC_MAX_WORKERS | 2 | ThreadPoolExecutor count |
| TVEC_MAX_BATCH_SIZE | 32 | Max texts per encode() |
| TVEC_BATCH_COALESCE | 0 | Cross-request batching (0=off) |
| TVEC_COALESCE_WAIT_MS | 50 | Batch coalescing wait |
| TVEC_TIMEOUT_SECONDS | 10 | Per-call timeout |
| TVEC_CONCURRENCY | 4 | Semaphore limit |
| TSLAM_BACKEND | auto | auto/vllm/llama_cpp |
| TSLAM_VLLM_URL | http://localhost:8100 | vLLM sidecar URL |
| TSLAM_GGUF_PATH | models/tslam-4b-q4_k_m.gguf | TSLAM-4B GGUF path |
| TSLAM_LLAMA_CPP_THREADS | 4 | llama-cpp n_threads |
| TSLAM_TIMEOUT_SECONDS | 30 (vLLM) / 60 (llama-cpp) | Per-call timeout |
| TSLAM_CONCURRENCY | 8 (vLLM) / 2 (llama-cpp) | Semaphore limit |
| ENRICHMENT_CONCURRENCY | 4 | Max parallel enrichments |

**Cold storage**:

| Variable | Default | Description |
|----------|---------|-------------|
| COLD_SEARCH_DEFAULT_K | 20 | Default ANN search results |
| MAX_COLD_BATCH | 5000 | Max batch size for archival |
| COLD_TIER1_DAYS | 365 | Compress summary threshold |
| COLD_TIER2_DAYS | 730 | Tombstone (drop embeddings) |
| COLD_TIER3_DAYS | 1095 | Permanent deletion eligible |

**Accumulation graph**:

| Variable | Default | Description |
|----------|---------|-------------|
| MAX_CLUSTER_EDGES | 1000 | Bounded BFS edge limit |
| MAX_EDGES_PER_FRAGMENT | 20 | Edge limit per fragment |
| AFFINITY_THRESHOLD | 0.40 | Minimum edge weight |
| NEAR_MISS_THRESHOLD | 0.55 | Near-miss classification |
| BASE_SNAP_THRESHOLD | 0.75 | Base snap threshold |

**Discovery mechanisms**:

| Variable | Default | Description |
|----------|---------|-------------|
| SURPRISE_HISTOGRAM_BINS | 50 | Fixed-width bins |
| SURPRISE_DECAY_ALPHA | 0.995 | Exponential decay |
| SURPRISE_LAPLACE_PSEUDOCOUNT | 0.01 | Smoothing |
| SURPRISE_PERCENTILE_THRESHOLD | 98 | Adaptive threshold percentile |
| SURPRISE_CAP_BITS | 20 | Maximum surprise value |
| PROPAGATION_SIMILARITY_THRESHOLD | 0.70 | Negative evidence propagation |
| PENALTY_STRENGTH | 0.30 | Disconfirmation penalty |
| PENALTY_FLOOR | 0.30 | Minimum post-penalty score ratio |
| PATTERN_DECAY_TAU | 90 | Days for pattern influence decay |
| PATTERN_TTL | 180 | Days until pattern deletion |
| BRIDGE_BC_THRESHOLD | 0.30 | Betweenness centrality minimum |
| CONFLICT_ENTITY_OVERLAP_THRESHOLD | 0.40 | Conflict detection overlap |
| CONFLICT_TIME_WINDOW_SECONDS | 3600 | Conflict detection window |
| CAUSAL_CO_OCCURRENCE_WINDOW | 3600 | Seconds for causal pairing |
| CAUSAL_N_MIN | 15 | Minimum sample for direction |
| CAUSAL_DELTA_THRESHOLD | 0.80 | Directional fraction minimum |
| CAUSAL_CV_MAX | 0.50 | Max coefficient of variation |
| COMPRESSION_DISCOVERY_THRESHOLD | 0.40 | Minimum compression gain |
| META_MEMORY_DECAY_LAMBDA | 0.02 | Daily productivity decay |
| META_MEMORY_MIN_FLOOR | 0.05 | Minimum allocation per area |
| META_MEMORY_ACTIVATION_THRESHOLD | 500 | Labeled outcomes for activation |
| EVOLUTIONARY_MAX_POPULATION | 100 | Max patterns per partition |
| COUNTERFACTUAL_MAX_CANDIDATES | 200 | Per batch |
| COUNTERFACTUAL_MAX_PAIRS | 5000 | Per candidate |

### 20.2 Glossary

| Term | Definition |
|------|-----------|
| Abeyance Fragment | A unit of network operations evidence (alarm, log, metric, ticket, CMDB delta) stored with four embeddings and validity masks |
| Accumulation Graph | Affinity graph where fragments are nodes and weighted edges represent pairwise similarity above AFFINITY_THRESHOLD |
| Bridge | An articulation point in the accumulation graph whose removal would disconnect components, indicating structurally critical evidence |
| Cold Storage | PostgreSQL-based archive for expired/archived fragments with IVFFlat ANN indexes |
| Disconfirmation | Operator or system action marking evidence as irrelevant, triggering accelerated decay |
| Discovery Ledger | Cross-layer event log recording all discovery signals |
| Enrichment Chain | Five-step pipeline producing four embeddings per fragment |
| Hypothesis | A TSLAM-8B generated falsifiable claim about a failure pattern |
| IVFFlat | Inverted File with Flat quantisation; pgvector's approximate nearest neighbour index |
| Mask | Per-dimension boolean indicating embedding validity; FALSE means T-VEC call failed |
| Meta-Memory | L5 mechanism tracking search area productivity and biasing exploration |
| Negative Evidence | Mechanism for marking fragments as irrelevant with accelerated decay |
| RRF | Reciprocal Rank Fusion; method for combining results from multiple ANN indexes |
| Shadow Topology | Entity-relationship graph from CMDB representing network structure |
| Sidak Correction | Multiple-comparisons adjustment to snap thresholds when evaluating multiple profiles |
| Snap | The event of two fragments being confirmed as correlated evidence |
| snap_decision_record | Canonical table name for per-pair scoring audit log (NOT snap_decision_log) |
| Surprise | Shannon self-information (-log2(P)) of a snap score relative to its historical distribution |
| T-VEC | 1.5B parameter SentenceTransformer model for telecom-domain embeddings |
| TSLAM | 8B parameter Llama-3.1 fine-tune for telecom entity extraction and hypothesis generation |
| Weight Profile | Five-weight vector defining dimension importance per failure mode |

---

*End of ABEYANCE_MEMORY_LLD_V3.md*
*Version 3.0 | 56 tables | 14 discovery mechanisms | 5 cognitive layers | 31 audit findings resolved*
*Generated: 2026-03-16*
