# Abeyance Memory v3.0 — Observability Metrics Specification

**Task:** T2.6 — Observability Metrics Design
**Generated:** 2026-03-16
**Addresses Findings:** F-7.1 (SEVERE: no operational metrics), F-7.2 (no snap rate alerting), F-7.3 (no maintenance job history)

---

## 1. Overview

This document specifies all Prometheus-compatible metrics, histograms, counters, gauges, and alerting rules for the Abeyance Memory subsystem. It is a specification only — no implementation is included. All metric names follow the `abeyance_` namespace prefix and Prometheus naming conventions (`snake_case`, `_total` suffix for counters).

### 1.1 Metric Categories

| Category | Prefix | Addresses Finding |
|---|---|---|
| Fragment lifecycle counters | `abeyance_fragment_` | F-7.1 |
| Snap scoring histograms | `abeyance_snap_` | F-7.1, F-7.2 |
| Active fragment gauges | `abeyance_active_fragments_` | F-7.1 |
| Enrichment chain latency | `abeyance_enrichment_` | F-7.1 |
| ML model error rates and latency | `abeyance_model_` | F-7.1 |
| Maintenance job history | `abeyance_maintenance_` | F-7.3 |
| Embedding mask distribution | `abeyance_embedding_mask_` | F-7.1 |
| Accumulation graph metrics | `abeyance_graph_` | F-7.1 |
| Back-pressure / queue metrics | `abeyance_queue_` | F-7.1 |

---

## 2. Fragment Lifecycle Counters

### 2.1 `abeyance_fragment_ingested_total`

| Property | Value |
|---|---|
| Type | Counter |
| Description | Total fragments ingested into the enrichment chain |
| Labels | `tenant_id`, `source_type` |
| Unit | fragments |

**Emission point:** `EnrichmentChain.enrich()` — emit immediately after the `AbeyanceFragmentORM` is persisted and the DB transaction commits. File: `backend/app/services/abeyance/enrichment_chain.py`.

---

### 2.2 `abeyance_fragment_decayed_total`

| Property | Value |
|---|---|
| Type | Counter |
| Description | Total fragments whose `current_decay_score` was updated during a decay pass (not expired — only score updated) |
| Labels | `tenant_id`, `source_type` |
| Unit | fragments |

**Emission point:** `DecayEngine.run_decay_pass()` — emit once per fragment written in the bulk update. File: `backend/app/services/abeyance/decay_engine.py`.

---

### 2.3 `abeyance_fragment_expired_total`

| Property | Value |
|---|---|
| Type | Counter |
| Description | Total fragments transitioned to EXPIRED status (either by decay threshold or idle timeout) |
| Labels | `tenant_id`, `source_type`, `expiry_reason` |
| Unit | fragments |

**`expiry_reason` values:** `decay_threshold`, `idle_timeout`, `hard_lifetime`

**Emission point:** `DecayEngine.run_decay_pass()` — emit for each fragment whose `snap_status` transitions to `EXPIRED`. File: `backend/app/services/abeyance/decay_engine.py`.

---

### 2.4 `abeyance_fragment_snapped_total`

| Property | Value |
|---|---|
| Type | Counter |
| Description | Total fragments transitioned to SNAPPED status via the snap engine |
| Labels | `tenant_id`, `failure_mode`, `snap_trigger` |
| Unit | fragments |

**`snap_trigger` values:** `pairwise` (direct snap), `cluster` (cluster-level snap from `AccumulationGraph`)

**Emission point (pairwise):** `SnapEngine._apply_snap()` — emit after DB commit. File: `backend/app/services/abeyance/snap_engine.py`.
**Emission point (cluster):** `AccumulationGraph.detect_and_evaluate_clusters()` — emit for each fragment in the snapped cluster. File: `backend/app/services/abeyance/accumulation_graph.py`.

---

### 2.5 `abeyance_fragment_archived_cold_total`

| Property | Value |
|---|---|
| Type | Counter |
| Description | Total fragments archived to cold storage (both PostgreSQL and Parquet paths) |
| Labels | `tenant_id`, `storage_backend` |
| Unit | fragments |

**`storage_backend` values:** `pgvector`, `parquet`

**Emission point:** `AbeyanceColdStorage.archive_to_db()` and `archive_batch_to_db()` — emit after successful commit. File: `backend/app/services/abeyance/cold_storage.py`.

---

### 2.6 `abeyance_fragment_dedup_rejected_total`

| Property | Value |
|---|---|
| Type | Counter |
| Description | Total fragments rejected at ingestion due to duplicate `dedup_key` |
| Labels | `tenant_id`, `source_type` |
| Unit | fragments |

**Emission point:** `EnrichmentChain.enrich()` — emit when the `uq_fragment_dedup` constraint triggers a no-op or early return. File: `backend/app/services/abeyance/enrichment_chain.py`.

---

### 2.7 `abeyance_fragment_near_miss_boosted_total`

| Property | Value |
|---|---|
| Type | Counter |
| Description | Total near-miss boost applications (`apply_near_miss_boost` calls) |
| Labels | `tenant_id` |
| Unit | applications |

**Emission point:** `DecayEngine.apply_near_miss_boost()` — emit after DB write. File: `backend/app/services/abeyance/decay_engine.py`.

---

## 3. Snap Score Histograms

These histograms expose the full statistical distribution of snap scoring output, enabling detection of threshold drift, embedding degradation, and profile-specific anomalies.

### 3.1 `abeyance_snap_score_histogram`

| Property | Value |
|---|---|
| Type | Histogram |
| Description | Distribution of `final_score` values produced by the snap engine across all evaluations |
| Labels | `tenant_id`, `failure_mode`, `decision` |
| Buckets | `[0.0, 0.1, 0.2, 0.3, 0.4, 0.45, 0.5, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95, 1.0]` |
| Unit | score (dimensionless) |

Bucket granularity is highest in the `[0.40, 0.75]` range because `AFFINITY_THRESHOLD = 0.40`, `NEAR_MISS_THRESHOLD = 0.55`, and `BASE_SNAP_THRESHOLD = 0.75` all fall in this interval. Fine-grained buckets here allow detection of threshold boundary crowding.

**`decision` values:** `SNAP`, `NEAR_MISS`, `AFFINITY`, `NONE`

**Emission point:** `SnapEngine._score_pair()` — emit one observation per `(new_fragment, candidate_fragment, failure_mode_profile)` triple evaluated. File: `backend/app/services/abeyance/snap_engine.py`.

---

### 3.2 `abeyance_snap_component_score_histogram`

| Property | Value |
|---|---|
| Type | Histogram |
| Description | Distribution of individual scoring components per failure mode profile |
| Labels | `tenant_id`, `failure_mode`, `component` |
| Buckets | `[0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]` |
| Unit | score (dimensionless) |

**`component` values:** `semantic_sim`, `topological_prox`, `entity_overlap`, `operational_sim`, `temporal_modifier`

This histogram is the primary diagnostic for detecting embedding dimension degradation per component. For example, if `topo` emits scores near zero across all fragments, it signals the F-3.2 failure mode (empty entity list passed to topology expansion).

**Emission point:** `SnapEngine._score_pair()` — emit one observation per component per evaluation. File: `backend/app/services/abeyance/snap_engine.py`.

---

### 3.3 `abeyance_snap_threshold_applied_histogram`

| Property | Value |
|---|---|
| Type | Histogram |
| Description | Distribution of Sidak-adjusted thresholds applied per evaluation (reflects k value in multiple comparisons correction) |
| Labels | `tenant_id`, `multiple_comparisons_k` |
| Buckets | `[0.70, 0.75, 0.80, 0.82, 0.84, 0.86, 0.88, 0.90, 0.92, 0.95]` |
| Unit | threshold (dimensionless) |

**Emission point:** `SnapEngine._score_pair()` — emit once per evaluation using the `threshold_applied` value. File: `backend/app/services/abeyance/snap_engine.py`.

---

### 3.4 `abeyance_cluster_score_histogram`

| Property | Value |
|---|---|
| Type | Histogram |
| Description | Distribution of LME cluster scores and correlation-discounted adjusted scores |
| Labels | `tenant_id`, `score_stage`, `decision` |
| Buckets | `[0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 1.0]` |
| Unit | score (dimensionless) |

**`score_stage` values:** `raw_lme` (before correlation discount), `adjusted` (after discount)

**Emission point:** `AccumulationGraph.detect_and_evaluate_clusters()` — emit two observations per cluster evaluation (one for each stage). File: `backend/app/services/abeyance/accumulation_graph.py`.

---

### 3.5 `abeyance_cluster_size_histogram`

| Property | Value |
|---|---|
| Type | Histogram |
| Description | Distribution of cluster member counts at evaluation time |
| Labels | `tenant_id`, `decision` |
| Buckets | `[1, 2, 3, 5, 8, 10, 15, 20, 30, 40, 50]` |
| Unit | fragments |

**Emission point:** `AccumulationGraph.detect_and_evaluate_clusters()` — emit once per cluster evaluated. File: `backend/app/services/abeyance/accumulation_graph.py`.

---

## 4. Active Fragment Gauges

### 4.1 `abeyance_active_fragments`

| Property | Value |
|---|---|
| Type | Gauge |
| Description | Current count of fragments in ACTIVE or NEAR_MISS state per tenant |
| Labels | `tenant_id`, `snap_status` |
| Unit | fragments |

This is the primary capacity gauge. The LLD resource constraint RES-3.1-2 sets the operational limit at 500K active fragments per tenant. Alert when this approaches the limit (see Section 10).

**`snap_status` values:** `ACTIVE`, `NEAR_MISS`

**Emission point:** Emitted by a periodic scrape job that queries `abeyance_fragment` with `snap_status IN ('ACTIVE', 'NEAR_MISS')` grouped by `tenant_id, snap_status`. This is a read-side query, not emitted inline with mutations. Recommended interval: 60 seconds. File: a dedicated metrics collector function in `backend/app/services/abeyance/metrics_collector.py` (new module).

**Alternative:** Maintain an in-process counter and emit as gauge from the `MaintenanceService` at the end of each `run_full_maintenance()` pass. Counters for ingested, expired, snapped, and archived are sufficient to keep this consistent without periodic DB queries.

---

### 4.2 `abeyance_fragments_by_status`

| Property | Value |
|---|---|
| Type | Gauge |
| Description | Current count of fragments per lifecycle state per tenant |
| Labels | `tenant_id`, `snap_status` |
| Unit | fragments |

**`snap_status` values:** `INGESTED`, `ACTIVE`, `NEAR_MISS`, `SNAPPED`, `STALE`, `EXPIRED`, `COLD`

**Emission point:** Same periodic scrape job as 4.1. Emitted once per `(tenant_id, snap_status)` pair.

---

### 4.3 `abeyance_accumulation_edges`

| Property | Value |
|---|---|
| Type | Gauge |
| Description | Current count of accumulation edges per tenant |
| Labels | `tenant_id` |
| Unit | edges |

**Emission point:** Periodic scrape or emitted by `MaintenanceService.prune_stale_edges()` after the prune pass (using the post-prune count).

---

### 4.4 `abeyance_cold_fragments`

| Property | Value |
|---|---|
| Type | Gauge |
| Description | Current count of rows in the `cold_fragment` table per tenant |
| Labels | `tenant_id`, `storage_backend` |
| Unit | fragments |

**Emission point:** Periodic scrape job. Recommended interval: 300 seconds (cold storage growth is slow).

---

## 5. Enrichment Chain Latency

Enrichment proceeds through a deterministic sequence of steps. Each step is timed separately so that individual model failures and latency regressions are isolatable without instrumenting the entire chain.

### 5.1 `abeyance_enrichment_duration_seconds`

| Property | Value |
|---|---|
| Type | Histogram |
| Description | End-to-end latency of `EnrichmentChain.enrich()` from entry to DB commit |
| Labels | `tenant_id`, `source_type`, `outcome` |
| Buckets | `[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0]` |
| Unit | seconds |

**`outcome` values:** `success`, `entity_extraction_failed`, `embedding_partial` (some mask bits false), `embedding_failed` (all mask bits false), `dedup_rejected`

**Emission point:** `EnrichmentChain.enrich()` — wrap the full method body with a timer; emit on exit (success or exception caught and re-raised). File: `backend/app/services/abeyance/enrichment_chain.py`.

---

### 5.2 `abeyance_enrichment_step_duration_seconds`

| Property | Value |
|---|---|
| Type | Histogram |
| Description | Per-step latency within the enrichment chain |
| Labels | `tenant_id`, `step`, `outcome` |
| Buckets | `[0.001, 0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0]` |
| Unit | seconds |

**`step` values and corresponding code locations:**

| `step` label | Method instrumented | File |
|---|---|---|
| `entity_extraction_llm` | `_llm_extract_entities()` | `enrichment_chain.py` |
| `entity_extraction_regex` | `_regex_extract_entities()` | `enrichment_chain.py` |
| `topology_neighbourhood` | `shadow_topology.get_neighbourhood()` called from `enrich()` | `shadow_topology.py` |
| `operational_fingerprint` | `_build_operational_fingerprint()` | `enrichment_chain.py` |
| `emb_semantic` | T-VEC 1.5B call for semantic embedding (within `_compute_embeddings()`) | `enrichment_chain.py` |
| `emb_topological` | T-VEC 1.5B call for topological text embedding (within `_compute_embeddings()`) | `enrichment_chain.py` |
| `emb_temporal` | Sinusoidal `_build_temporal_vector()` call (within `_compute_embeddings()`) | `enrichment_chain.py` |
| `emb_operational` | T-VEC 1.5B call for operational text embedding (within `_compute_embeddings()`) | `enrichment_chain.py` |
| `entity_extraction_tslam` | TSLAM-8B entity extraction call (within `_resolve_entities()` or `_llm_extract_entities()`) | `enrichment_chain.py` |
| `db_persist` | SQLAlchemy `session.commit()` at end of `enrich()` | `enrichment_chain.py` |

**`outcome` values per step:** `success`, `fallback` (e.g., regex used instead of TSLAM), `error`, `skipped` (step bypassed due to prior failure)

**Emission point:** Each step is wrapped in an individual timer block inside `_compute_embeddings()`, `_resolve_entities()`, `_build_operational_fingerprint()`, and the topology call in `enrich()`. Emit on step completion.

---

### 5.3 `abeyance_enrichment_entity_count_histogram`

| Property | Value |
|---|---|
| Type | Histogram |
| Description | Distribution of entity count extracted per fragment |
| Labels | `tenant_id`, `source_type`, `extraction_method` |
| Buckets | `[0, 1, 2, 3, 5, 8, 10, 15, 20, 30]` |
| Unit | entities |

**`extraction_method` values:** `tslam_llm`, `regex_fallback`, `explicit_refs`

**Emission point:** `EnrichmentChain._resolve_entities()` — emit once after entity resolution completes.

---

## 6. ML Model Error Rates and Latency Percentiles

### 6.1 `abeyance_model_request_total`

| Property | Value |
|---|---|
| Type | Counter |
| Description | Total inference requests issued to each ML model |
| Labels | `model`, `tenant_id`, `status` |
| Unit | requests |

**`model` values:** `tvec_semantic`, `tvec_topological`, `tvec_operational`, `tslam_entity`, `sinusoidal_temporal`

**`status` values:** `success`, `error`, `timeout`, `fallback_used`

**Emission point:** Each model call site within `EnrichmentChain._compute_embeddings()` and `_resolve_entities()`/`_llm_extract_entities()`. Emit one increment per call on exit.

---

### 6.2 `abeyance_model_latency_seconds`

| Property | Value |
|---|---|
| Type | Histogram |
| Description | Per-model inference latency |
| Labels | `model`, `tenant_id` |
| Buckets | `[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0]` |
| Unit | seconds |

**`model` values:** same as 6.1

The fine-grained low-end buckets (`0.001`, `0.005`, `0.01`) are relevant for `sinusoidal_temporal` which is CPU-only and should complete in under 1 ms. The high-end buckets (`10.0`, `30.0`) are relevant for T-VEC and TSLAM under GPU memory pressure.

**Emission point:** Each model call site, same as 6.1.

---

### 6.3 `abeyance_model_error_total`

| Property | Value |
|---|---|
| Type | Counter |
| Description | Total model inference errors that caused a fallback or mask bit to be set False |
| Labels | `model`, `tenant_id`, `error_type`, `affected_embedding_dim` |
| Unit | errors |

**`error_type` values:** `inference_error`, `timeout`, `empty_output`, `dimension_mismatch`

**`affected_embedding_dim` values:** `semantic`, `topological`, `temporal`, `operational`, `entity`

**Emission point:** `EnrichmentChain._compute_embeddings()` — emit when the try/except around any model call enters the except branch and sets `mask[i] = False`.

---

### 6.4 `abeyance_model_fallback_total`

| Property | Value |
|---|---|
| Type | Counter |
| Description | Total activations of the regex fallback path for entity extraction (TSLAM failure) |
| Labels | `tenant_id`, `reason` |
| Unit | fallbacks |

**`reason` values:** `tslam_error`, `tslam_timeout`, `tslam_empty_output`, `no_tslam_service`

This metric directly tracks the F-4.2 failure scenario (entity extraction is single point of failure). A non-zero value indicates TSLAM is unavailable or misbehaving.

**Emission point:** `EnrichmentChain._resolve_entities()` — emit when the code path branches to `_regex_extract_entities()` instead of `_llm_extract_entities()`.

---

## 7. Maintenance Job History Metrics

These metrics address F-7.3 directly. Each maintenance task emits summary counters and a duration histogram so historical pass data is visible in Prometheus without a dedicated maintenance history table. The values are also the specification for what `MaintenanceService.run_full_maintenance()` should record to a `maintenance_job_run` table (see Section 7.7).

### 7.1 `abeyance_maintenance_decay_pass_total`

| Property | Value |
|---|---|
| Type | Counter |
| Description | Total decay pass invocations |
| Labels | `tenant_id`, `outcome` |
| Unit | passes |

**`outcome` values:** `success`, `partial` (batch limit hit, more fragments remain), `error`

**Emission point:** `MaintenanceService.run_decay_pass()` — emit on return. File: `backend/app/services/abeyance/maintenance.py`.

---

### 7.2 `abeyance_maintenance_decay_fragments_updated_total`

| Property | Value |
|---|---|
| Type | Counter |
| Description | Cumulative fragments whose decay score was updated across all decay passes |
| Labels | `tenant_id` |
| Unit | fragments |

**Emission point:** `MaintenanceService.run_decay_pass()` — increment by the `updated` value from `DecayEngine.run_decay_pass()`.

---

### 7.3 `abeyance_maintenance_decay_fragments_expired_total`

| Property | Value |
|---|---|
| Type | Counter |
| Description | Cumulative fragments expired across all decay passes |
| Labels | `tenant_id` |
| Unit | fragments |

**Emission point:** `MaintenanceService.run_decay_pass()` — increment by the `expired` value from `DecayEngine.run_decay_pass()`.

---

### 7.4 `abeyance_maintenance_edges_pruned_total`

| Property | Value |
|---|---|
| Type | Counter |
| Description | Cumulative accumulation edges removed across all prune passes |
| Labels | `tenant_id` |
| Unit | edges |

**Emission point:** `MaintenanceService.prune_stale_edges()` — increment by return value.

---

### 7.5 `abeyance_maintenance_fragments_expired_total`

| Property | Value |
|---|---|
| Type | Counter |
| Description | Cumulative fragments transitioned to EXPIRED by `expire_stale_fragments()` |
| Labels | `tenant_id` |
| Unit | fragments |

Note: This counter covers expiry via the explicit STALE→EXPIRED batch, distinct from decay-driven expiry in 7.3.

**Emission point:** `MaintenanceService.expire_stale_fragments()` — increment by return value.

---

### 7.6 `abeyance_maintenance_orphans_cleaned_total`

| Property | Value |
|---|---|
| Type | Counter |
| Description | Cumulative orphaned `fragment_entity_ref` rows deleted |
| Labels | `tenant_id` |
| Unit | rows |

**Emission point:** `MaintenanceService.cleanup_orphaned_entity_refs()` — increment by return value.

---

### 7.7 `abeyance_maintenance_duration_seconds`

| Property | Value |
|---|---|
| Type | Histogram |
| Description | Wall-clock duration of each maintenance task |
| Labels | `tenant_id`, `task` |
| Buckets | `[0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0]` |
| Unit | seconds |

**`task` values:** `decay_pass`, `edge_prune`, `fragment_expire`, `orphan_cleanup`, `full_maintenance`

**Emission point:** `MaintenanceService` — wrap each task and `run_full_maintenance()` with a timer; emit on exit.

---

### 7.8 `abeyance_maintenance_last_run_timestamp`

| Property | Value |
|---|---|
| Type | Gauge |
| Description | Unix timestamp of the last successful completion of each maintenance task per tenant |
| Labels | `tenant_id`, `task` |
| Unit | seconds (Unix epoch) |

**`task` values:** same as 7.7

This gauge enables staleness alerting. If `full_maintenance` has not run in over 2 hours for any tenant, the alert in Section 10.4 fires.

**Emission point:** `MaintenanceService` — set to `time.time()` immediately after each task returns without error.

---

## 8. Embedding Mask Distribution

These metrics expose the fraction of fragments for which each embedding dimension is valid (mask bit = True). This is the primary operational signal for detecting LLM/model outage impact on the fragment population.

### 8.1 `abeyance_embedding_mask_valid_fraction`

| Property | Value |
|---|---|
| Type | Gauge |
| Description | Fraction of currently-active fragments for which each embedding dimension is valid (`mask[i] = True`) |
| Labels | `tenant_id`, `embedding_dim` |
| Unit | ratio [0.0, 1.0] |

**`embedding_dim` values:**

| `embedding_dim` label | Mask index | Model responsible | Embedding columns |
|---|---|---|---|
| `semantic` | 0 | T-VEC 1.5B (CPU) | `enriched_embedding[0:512]` |
| `topological` | 1 | T-VEC 1.5B (CPU) | `enriched_embedding[512:896]` |
| `temporal` | 2 | Sinusoidal (CPU) | `enriched_embedding[896:1152]` |
| `operational` | 3 | T-VEC 1.5B (CPU) | `enriched_embedding[1152:1536]` |

The `embedding_mask` column in `abeyance_fragment` stores `[semantic_valid, topo_valid, temporal_valid, operational_valid]` as a JSONB array (INV-11).

**Emission point:** Periodic scrape job — query `abeyance_fragment` for ACTIVE/NEAR_MISS fragments grouped by `tenant_id`, compute fraction with `embedding_mask[i] = true` per dimension. Recommended interval: 120 seconds.

```sql
-- Example query structure (one per tenant):
SELECT
  tenant_id,
  COUNT(*) FILTER (WHERE (embedding_mask->0)::boolean = true) * 1.0 / COUNT(*) AS semantic_valid_fraction,
  COUNT(*) FILTER (WHERE (embedding_mask->1)::boolean = true) * 1.0 / COUNT(*) AS topo_valid_fraction,
  COUNT(*) FILTER (WHERE (embedding_mask->2)::boolean = true) * 1.0 / COUNT(*) AS temporal_valid_fraction,
  COUNT(*) FILTER (WHERE (embedding_mask->3)::boolean = true) * 1.0 / COUNT(*) AS operational_valid_fraction
FROM abeyance_fragment
WHERE snap_status IN ('ACTIVE', 'NEAR_MISS')
GROUP BY tenant_id;
```

---

### 8.2 `abeyance_embedding_mask_all_invalid_total`

| Property | Value |
|---|---|
| Type | Counter |
| Description | Total fragments ingested with all four mask bits False (complete embedding failure) |
| Labels | `tenant_id`, `source_type` |
| Unit | fragments |

A non-zero value here means fragments entered the system with no usable embedding across any dimension. These fragments can never produce a meaningful snap score.

**Emission point:** `EnrichmentChain.enrich()` — after `_compute_embeddings()` returns, check if all four mask elements are False; if so, increment.

---

### 8.3 `abeyance_embedding_mask_partial_total`

| Property | Value |
|---|---|
| Type | Counter |
| Description | Total fragments ingested with one or more (but not all) mask bits False |
| Labels | `tenant_id`, `source_type`, `invalid_dims` |
| Unit | fragments |

**`invalid_dims` values:** A sorted comma-separated string of the invalid dimension names, e.g., `"topological"`, `"semantic,operational"`. Limit cardinality by only tracking single-dimension failures with specific labels; multi-dimension failures group under `"multiple"`.

**Emission point:** `EnrichmentChain.enrich()` — after `_compute_embeddings()` returns, for each fragment where some (not all) mask bits are False.

---

## 9. Accumulation Graph and Shadow Topology Metrics

### 9.1 `abeyance_graph_edge_added_total`

| Property | Value |
|---|---|
| Type | Counter |
| Description | Total accumulation edges created or updated |
| Labels | `tenant_id`, `failure_mode`, `operation` |
| Unit | edges |

**`operation` values:** `created`, `updated` (affinity score increased)

**Emission point:** `AccumulationGraph.add_or_update_edge()` — emit on successful DB commit. File: `backend/app/services/abeyance/accumulation_graph.py`.

---

### 9.2 `abeyance_graph_edge_evicted_total`

| Property | Value |
|---|---|
| Type | Counter |
| Description | Total edge evictions due to `MAX_EDGES_PER_FRAGMENT = 20` enforcement |
| Labels | `tenant_id` |
| Unit | edges |

**Emission point:** `AccumulationGraph._enforce_edge_limit()` — emit for each evicted edge.

---

### 9.3 `abeyance_graph_cluster_evaluated_total`

| Property | Value |
|---|---|
| Type | Counter |
| Description | Total cluster evaluations performed |
| Labels | `tenant_id`, `decision` |
| Unit | evaluations |

**Emission point:** `AccumulationGraph.detect_and_evaluate_clusters()` — emit once per cluster evaluated.

---

### 9.4 `abeyance_topology_neighbourhood_size_histogram`

| Property | Value |
|---|---|
| Type | Histogram |
| Description | Distribution of neighbourhood entity counts returned by BFS expansion |
| Labels | `tenant_id`, `max_hops` |
| Buckets | `[0, 1, 5, 10, 25, 50, 100, 200, 300, 500]` |
| Unit | entities |

**Emission point:** `ShadowTopologyService.get_neighbourhood()` — emit on return with the entity count in the result. File: `backend/app/services/abeyance/shadow_topology.py`.

---

### 9.5 `abeyance_topology_bfs_capped_total`

| Property | Value |
|---|---|
| Type | Counter |
| Description | Total BFS expansions that hit the `MAX_BFS_RESULT = 500` hard cap |
| Labels | `tenant_id` |
| Unit | expansions |

A non-zero rate on this metric indicates that the shadow topology is too dense relative to the query entity set, or that `max_hops` is set too high for the graph size.

**Emission point:** `ShadowTopologyService.get_neighbourhood()` — emit if the returned entity count equals `MAX_BFS_RESULT`.

---

## 10. Back-Pressure and Queue Metrics

### 10.1 `abeyance_queue_depth`

| Property | Value |
|---|---|
| Type | Gauge |
| Description | Current depth of the fragment ingestion queue |
| Labels | `tenant_id` |
| Unit | items |

**Emission point:** Event ingestion queue layer — emit after each enqueue and dequeue operation.

---

### 10.2 `abeyance_queue_high_water_mark_total`

| Property | Value |
|---|---|
| Type | Counter |
| Description | Total HTTP 429 responses issued due to queue depth exceeding `HIGH_WATER_MARK = 500` |
| Labels | `tenant_id` |
| Unit | responses |

**Emission point:** Event ingestion endpoint — emit when returning HTTP 429.

---

### 10.3 `abeyance_queue_circuit_breaker_open_total`

| Property | Value |
|---|---|
| Type | Counter |
| Description | Total circuit breaker open events (queue depth exceeded `CRITICAL_WATER_MARK = 2000`) |
| Labels | `tenant_id` |
| Unit | events |

**Emission point:** Event ingestion queue layer — emit when the circuit breaker transitions to OPEN state.

---

## 11. Alerting Rules

All rules are expressed in Prometheus alerting rule syntax. Thresholds are initial recommendations and should be tuned per tenant baseline during the first 30 days of operation.

### 11.1 Snap Rate Anomaly (F-7.2)

```yaml
- alert: AbeyanceSnapRateAnomaly
  expr: |
    rate(abeyance_fragment_snapped_total[5m])
    > 5 * avg_over_time(rate(abeyance_fragment_snapped_total[5m])[1h:5m])
  for: 2m
  labels:
    severity: warning
    subsystem: snap_engine
  annotations:
    summary: "Snap rate for tenant {{ $labels.tenant_id }} is 5x the hourly average"
    description: >
      Snap rate spike may indicate threshold miscalibration, embedding drift,
      or a flood of correlated fragments (false positive storm). Investigate
      snap_score_histogram for score distribution changes.
      Finding F-7.2.

- alert: AbeyanceSnapRateDrop
  expr: |
    rate(abeyance_fragment_snapped_total[15m]) == 0
    and rate(abeyance_fragment_ingested_total[15m]) > 0
  for: 30m
  labels:
    severity: warning
    subsystem: snap_engine
  annotations:
    summary: "Zero snap rate for tenant {{ $labels.tenant_id }} despite active ingestion"
    description: >
      Possible embedding failure (all mask bits false), threshold too high,
      or snap engine not being called. Check abeyance_embedding_mask_valid_fraction
      and abeyance_model_error_total.
      Finding F-7.2.
```

---

### 11.2 Active Fragment Capacity

```yaml
- alert: AbeyanceActiveFragmentApproachingLimit
  expr: |
    sum by (tenant_id) (abeyance_active_fragments) > 400000
  for: 5m
  labels:
    severity: warning
    subsystem: fragment_lifecycle
  annotations:
    summary: "Active fragment count for tenant {{ $labels.tenant_id }} is above 400K (limit 500K per RES-3.1-2)"
    description: >
      Fragment count approaching operational limit. Check maintenance schedule,
      decay pass frequency, and ingestion rate. Consider increasing maintenance
      frequency or reducing ingestion rate.

- alert: AbeyanceActiveFragmentAtLimit
  expr: |
    sum by (tenant_id) (abeyance_active_fragments) > 480000
  for: 2m
  labels:
    severity: critical
    subsystem: fragment_lifecycle
  annotations:
    summary: "Active fragment count for tenant {{ $labels.tenant_id }} is critical (>480K, limit 500K)"
```

---

### 11.3 Embedding Mask Degradation

```yaml
- alert: AbeyanceEmbeddingDimensionDegraded
  expr: |
    abeyance_embedding_mask_valid_fraction < 0.80
  for: 5m
  labels:
    severity: warning
    subsystem: enrichment_chain
  annotations:
    summary: "Embedding dimension {{ $labels.embedding_dim }} valid fraction below 80% for tenant {{ $labels.tenant_id }}"
    description: >
      Model producing invalid embeddings for more than 20% of fragments.
      Snap scores for affected fragments will use zero-filled sub-vectors.
      Check abeyance_model_error_total for the responsible model.
      Finding F-7.1, F-6.1, F-6.2.

- alert: AbeyanceEmbeddingCompleteLoss
  expr: |
    abeyance_embedding_mask_valid_fraction{embedding_dim="semantic"} < 0.10
    or abeyance_embedding_mask_valid_fraction{embedding_dim="operational"} < 0.10
  for: 2m
  labels:
    severity: critical
    subsystem: enrichment_chain
  annotations:
    summary: "Critical embedding dimension nearly fully invalid for tenant {{ $labels.tenant_id }}"
    description: >
      T-VEC 1.5B appears to be down or returning empty outputs.
      System is operating with severely degraded snap scoring.
      Per F-6.1: LLM/model outage degenerates system to near-random correlation.
```

---

### 11.4 Maintenance Staleness (F-7.3)

```yaml
- alert: AbeyanceMaintenanceStaleness
  expr: |
    (time() - abeyance_maintenance_last_run_timestamp{task="full_maintenance"}) > 7200
  for: 5m
  labels:
    severity: warning
    subsystem: maintenance
  annotations:
    summary: "Maintenance has not run for tenant {{ $labels.tenant_id }} in over 2 hours"
    description: >
      If maintenance is not running, stale fragments accumulate and the
      active fragment gauge drifts toward the 500K limit.
      Finding F-7.3.

- alert: AbeyanceMaintenanceNeverRun
  expr: |
    absent(abeyance_maintenance_last_run_timestamp{task="full_maintenance"})
  for: 10m
  labels:
    severity: critical
    subsystem: maintenance
  annotations:
    summary: "No maintenance job run metric found — maintenance may not be configured"
    description: >
      The abeyance_maintenance_last_run_timestamp gauge is absent.
      Maintenance service may not have been started.
      Finding F-7.3.
```

---

### 11.5 TSLAM Entity Extraction Failure Rate

```yaml
- alert: AbeyanceTSLAMFallbackElevated
  expr: |
    rate(abeyance_model_fallback_total[5m]) > 0.1 * rate(abeyance_fragment_ingested_total[5m])
  for: 5m
  labels:
    severity: warning
    subsystem: enrichment_chain
  annotations:
    summary: "TSLAM entity extraction fallback rate exceeds 10% of ingestion rate for tenant {{ $labels.tenant_id }}"
    description: >
      TSLAM-8B is failing for more than 10% of fragments.
      Fragments falling back to regex extraction will have lower quality
      entity coverage, degrading topological embedding quality.
      Finding F-4.2.

- alert: AbeyanceTSLAMFullOutage
  expr: |
    rate(abeyance_model_fallback_total{reason="no_tslam_service"}[5m]) > 0
  for: 1m
  labels:
    severity: critical
    subsystem: enrichment_chain
  annotations:
    summary: "TSLAM service is unreachable — all entity extraction is using regex fallback"
    description: >
      TSLAM-8B GPU inference service is not responding.
      All fragments are falling back to regex extraction.
      Finding F-4.2.
```

---

### 11.6 Model Latency SLO

```yaml
- alert: AbeyanceTVECLatencyHigh
  expr: |
    histogram_quantile(0.95, rate(abeyance_model_latency_seconds_bucket{model=~"tvec_.*"}[5m])) > 5.0
  for: 3m
  labels:
    severity: warning
    subsystem: enrichment_chain
  annotations:
    summary: "T-VEC p95 latency exceeds 5 seconds for model {{ $labels.model }}"
    description: >
      T-VEC 1.5B CPU inference is slow. This will cause enrichment chain
      end-to-end latency to exceed acceptable limits and may cascade into
      back-pressure queue saturation.

- alert: AbeyanceTSLAMLatencyHigh
  expr: |
    histogram_quantile(0.95, rate(abeyance_model_latency_seconds_bucket{model="tslam_entity"}[5m])) > 10.0
  for: 3m
  labels:
    severity: warning
    subsystem: enrichment_chain
  annotations:
    summary: "TSLAM-8B p95 latency exceeds 10 seconds"
    description: >
      TSLAM-8B GPU inference latency is high. Possible GPU memory pressure
      or batch queue saturation.
```

---

### 11.7 Circuit Breaker

```yaml
- alert: AbeyanceCircuitBreakerOpen
  expr: |
    rate(abeyance_queue_circuit_breaker_open_total[1m]) > 0
  for: 0m
  labels:
    severity: critical
    subsystem: ingestion
  annotations:
    summary: "Abeyance ingestion circuit breaker opened for tenant {{ $labels.tenant_id }}"
    description: >
      Queue depth exceeded CRITICAL_WATER_MARK (2000). Circuit breaker
      is open. Ingestion is rejected for 30 seconds per cycle.
      Fragment ingestion is being shed. Investigate upstream ingestion rate.
```

---

## 12. Complete Metric Reference Table

| Metric Name | Type | Labels | Emission Source |
|---|---|---|---|
| `abeyance_fragment_ingested_total` | Counter | `tenant_id`, `source_type` | `EnrichmentChain.enrich()` |
| `abeyance_fragment_decayed_total` | Counter | `tenant_id`, `source_type` | `DecayEngine.run_decay_pass()` |
| `abeyance_fragment_expired_total` | Counter | `tenant_id`, `source_type`, `expiry_reason` | `DecayEngine.run_decay_pass()` |
| `abeyance_fragment_snapped_total` | Counter | `tenant_id`, `failure_mode`, `snap_trigger` | `SnapEngine._apply_snap()`, `AccumulationGraph.detect_and_evaluate_clusters()` |
| `abeyance_fragment_archived_cold_total` | Counter | `tenant_id`, `storage_backend` | `AbeyanceColdStorage.archive_to_db()` / `archive_batch_to_db()` |
| `abeyance_fragment_dedup_rejected_total` | Counter | `tenant_id`, `source_type` | `EnrichmentChain.enrich()` |
| `abeyance_fragment_near_miss_boosted_total` | Counter | `tenant_id` | `DecayEngine.apply_near_miss_boost()` |
| `abeyance_snap_score_histogram` | Histogram | `tenant_id`, `failure_mode`, `decision` | `SnapEngine._score_pair()` |
| `abeyance_snap_component_score_histogram` | Histogram | `tenant_id`, `failure_mode`, `component` | `SnapEngine._score_pair()` |
| `abeyance_snap_threshold_applied_histogram` | Histogram | `tenant_id`, `multiple_comparisons_k` | `SnapEngine._score_pair()` |
| `abeyance_cluster_score_histogram` | Histogram | `tenant_id`, `score_stage`, `decision` | `AccumulationGraph.detect_and_evaluate_clusters()` |
| `abeyance_cluster_size_histogram` | Histogram | `tenant_id`, `decision` | `AccumulationGraph.detect_and_evaluate_clusters()` |
| `abeyance_active_fragments` | Gauge | `tenant_id`, `snap_status` | Periodic scrape job (60s) |
| `abeyance_fragments_by_status` | Gauge | `tenant_id`, `snap_status` | Periodic scrape job (60s) |
| `abeyance_accumulation_edges` | Gauge | `tenant_id` | Periodic scrape or `MaintenanceService.prune_stale_edges()` |
| `abeyance_cold_fragments` | Gauge | `tenant_id`, `storage_backend` | Periodic scrape job (300s) |
| `abeyance_enrichment_duration_seconds` | Histogram | `tenant_id`, `source_type`, `outcome` | `EnrichmentChain.enrich()` |
| `abeyance_enrichment_step_duration_seconds` | Histogram | `tenant_id`, `step`, `outcome` | Per-step timers in `EnrichmentChain` |
| `abeyance_enrichment_entity_count_histogram` | Histogram | `tenant_id`, `source_type`, `extraction_method` | `EnrichmentChain._resolve_entities()` |
| `abeyance_model_request_total` | Counter | `model`, `tenant_id`, `status` | Per-model call sites in `EnrichmentChain` |
| `abeyance_model_latency_seconds` | Histogram | `model`, `tenant_id` | Per-model call sites in `EnrichmentChain` |
| `abeyance_model_error_total` | Counter | `model`, `tenant_id`, `error_type`, `affected_embedding_dim` | `EnrichmentChain._compute_embeddings()` except branches |
| `abeyance_model_fallback_total` | Counter | `tenant_id`, `reason` | `EnrichmentChain._resolve_entities()` |
| `abeyance_maintenance_decay_pass_total` | Counter | `tenant_id`, `outcome` | `MaintenanceService.run_decay_pass()` |
| `abeyance_maintenance_decay_fragments_updated_total` | Counter | `tenant_id` | `MaintenanceService.run_decay_pass()` |
| `abeyance_maintenance_decay_fragments_expired_total` | Counter | `tenant_id` | `MaintenanceService.run_decay_pass()` |
| `abeyance_maintenance_edges_pruned_total` | Counter | `tenant_id` | `MaintenanceService.prune_stale_edges()` |
| `abeyance_maintenance_fragments_expired_total` | Counter | `tenant_id` | `MaintenanceService.expire_stale_fragments()` |
| `abeyance_maintenance_orphans_cleaned_total` | Counter | `tenant_id` | `MaintenanceService.cleanup_orphaned_entity_refs()` |
| `abeyance_maintenance_duration_seconds` | Histogram | `tenant_id`, `task` | `MaintenanceService` task wrappers |
| `abeyance_maintenance_last_run_timestamp` | Gauge | `tenant_id`, `task` | `MaintenanceService` task exits |
| `abeyance_embedding_mask_valid_fraction` | Gauge | `tenant_id`, `embedding_dim` | Periodic scrape job (120s) |
| `abeyance_embedding_mask_all_invalid_total` | Counter | `tenant_id`, `source_type` | `EnrichmentChain.enrich()` |
| `abeyance_embedding_mask_partial_total` | Counter | `tenant_id`, `source_type`, `invalid_dims` | `EnrichmentChain.enrich()` |
| `abeyance_graph_edge_added_total` | Counter | `tenant_id`, `failure_mode`, `operation` | `AccumulationGraph.add_or_update_edge()` |
| `abeyance_graph_edge_evicted_total` | Counter | `tenant_id` | `AccumulationGraph._enforce_edge_limit()` |
| `abeyance_graph_cluster_evaluated_total` | Counter | `tenant_id`, `decision` | `AccumulationGraph.detect_and_evaluate_clusters()` |
| `abeyance_topology_neighbourhood_size_histogram` | Histogram | `tenant_id`, `max_hops` | `ShadowTopologyService.get_neighbourhood()` |
| `abeyance_topology_bfs_capped_total` | Counter | `tenant_id` | `ShadowTopologyService.get_neighbourhood()` |
| `abeyance_queue_depth` | Gauge | `tenant_id` | Ingestion queue layer |
| `abeyance_queue_high_water_mark_total` | Counter | `tenant_id` | Ingestion endpoint (HTTP 429) |
| `abeyance_queue_circuit_breaker_open_total` | Counter | `tenant_id` | Ingestion queue layer |

**Total metrics: 42** (21 counters, 7 gauges, 14 histograms)

---

## 13. Implementation Notes

### 13.1 Prometheus Client Pattern

All metrics are registered as module-level singletons using `prometheus_client` (Python). A thin `AbeyanceMetrics` class wraps all metric objects and provides typed emit methods. Services receive this object via dependency injection (same pattern as `ProvenanceLogger`).

```python
# Recommended structure (specification only):
class AbeyanceMetrics:
    fragment_ingested_total: Counter  # labels: tenant_id, source_type
    snap_score_histogram: Histogram
    # ... all metrics above

    def observe_fragment_ingested(self, tenant_id: str, source_type: str) -> None: ...
    def observe_snap_score(self, tenant_id: str, failure_mode: str,
                           decision: str, score: float) -> None: ...
```

New file: `backend/app/services/abeyance/abeyance_metrics.py`

### 13.2 Scrape-Based Gauges

Gauges backed by DB queries (Sections 4 and 8) must not be emitted inline with mutations due to the cost of SELECT COUNT queries. They are maintained by a background job running on a configurable interval. This job is separate from `MaintenanceService` and does not hold DB transactions across scrape intervals.

### 13.3 Label Cardinality

`tenant_id` appears on every metric. At the expected scale of up to 100 tenants, this is acceptable. `source_type` has 6 known values. `failure_mode` has 5 values. `embedding_dim` has 4 values. No unbounded label values are used. The `invalid_dims` label in `abeyance_embedding_mask_partial_total` is capped to single-dimension names plus `"multiple"` to prevent combinatorial explosion.

### 13.4 Metric Exposure

Metrics are exposed at `GET /metrics` on the FastAPI application (standard Prometheus scrape endpoint) using `prometheus_client.make_asgi_app()` mounted at the `/metrics` path. The endpoint must not require authentication so Prometheus can scrape without credentials.

---

*End of T2.6 Observability Metrics Specification*
*Version: 1.0 | Task: T2.6 | Phase: 2*
