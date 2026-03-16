# Discovery Loop Specification -- End-to-End Signal-to-Discovery Flow

**Task**: Phase 6 -- Discovery Loop Architecture
**Version**: 3.0
**Date**: 2026-03-16
**Status**: SPECIFICATION COMPLETE
**Depends On**: T1.3 (Enrichment Chain), T1.4 (Snap Scoring), D1.1 (Surprise Engine), D3.8 (Hypothesis Engine)

---

## 1. Purpose

This document defines the deterministic, bounded, end-to-end flow that converts a raw signal (alarm, ticket, telemetry event) into a confirmed or refuted discovery. Every stage has explicit entry conditions, processing subsystems, outputs, exit conditions, failure paths, and provenance requirements. The flow is deterministic: the same inputs always traverse the same stages and produce the same outputs.

---

## 2. Flow Overview

```
Signal Ingestion
      |
      v
[Stage 1] ENRICHMENT
      |
      v
[Stage 2] CORRELATION (Snap Scoring)
      |
      v
[Stage 3] SURPRISE EVALUATION
      |
      +---> [Stage 3a] DRIFT/CALIBRATION ALERT (operational path, exits flow)
      |
      v
[Stage 4] HYPOTHESIS GENERATION
      |
      v
[Stage 5] EVIDENCE TESTING
      |
      +---> [Stage 6a] CONFIRMATION ---> DISCOVERY
      |
      +---> [Stage 6b] REFUTATION ---> ARCHIVED NEGATIVE
      |
      +---> [Stage 6c] RETIREMENT (timeout) ---> INCONCLUSIVE
```

**Determinism guarantee**: Every branching point is governed by a boolean predicate over immutable data (stored embeddings, masks, scores, timestamps). No random number generation, no non-deterministic operations, no external state outside the database.

**Boundedness guarantee**: Every loop and iteration in this flow has a declared maximum. There are no infinite cycles. See Section 10 for the complete bound table.

---

## 3. Stage 1: Enrichment

### 3.1 Entry Conditions

| Condition | Enforcement |
|---|---|
| `raw_content` is non-empty string, truncated to `MAX_RAW_CONTENT_BYTES` | Input validation (enrichment_chain.md Section 3.0) |
| `tenant_id` is non-empty string | Input validation |
| `source_type` is one of: `TICKET_TEXT`, `ALARM`, `TELEMETRY_EVENT`, `CLI_OUTPUT`, `CHANGE_RECORD`, `CMDB_DELTA` | Input validation against `SOURCE_TYPE_DEFAULTS` keys |
| `event_timestamp` is a valid UTC datetime or defaults to `now()` | Input validation |

**Entry gate**: If any precondition fails, the signal is rejected with a logged validation error. No fragment is created. The signal is dead-lettered for operator review.

### 3.2 Processing Subsystems

| Subsystem | Reference | Processing |
|---|---|---|
| TSLAM-8B Entity Extraction | enrichment_chain.md Step (a) | Extract entity identifiers + domains + failure-mode hypotheses from raw text. Fallback: regex extraction + rule-based classification. |
| T-VEC Semantic Embedding | enrichment_chain.md Step (b) | Embed `[source_type] raw_content + entity context` into 1536-dim vector. Failure: NULL + mask FALSE. |
| Shadow Topology + T-VEC Topological Embedding | enrichment_chain.md Step (c) | Resolve entity UUIDs, BFS neighbourhood expansion (max_hops=2), embed neighbourhood description into 1536-dim vector. Failure: NULL + mask FALSE. |
| Sinusoidal Temporal Encoding | enrichment_chain.md Step (d) | Deterministic 256-dim vector from time-of-day, day-of-week, day-of-year, operational context. Cannot fail. |
| T-VEC Operational Embedding | enrichment_chain.md Step (e) | Embed failure-mode hypotheses + operational fingerprint into 1536-dim vector. Failure: NULL + mask FALSE. |

### 3.3 Output

A persisted `AbeyanceFragmentORM` row containing:

| Field | Guarantee |
|---|---|
| `fragment_id` (UUID) | Always assigned |
| `emb_temporal` (vector 256) | Always non-NULL (pure math) |
| `emb_semantic` (vector 1536 or NULL) | NULL only on T-VEC failure; mask tracks validity |
| `emb_topological` (vector 1536 or NULL) | NULL only on T-VEC/topology failure; mask tracks validity |
| `emb_operational` (vector 1536 or NULL) | NULL only on T-VEC failure; mask tracks validity |
| `mask_semantic`, `mask_topological`, `mask_operational` | TRUE if corresponding embedding is valid |
| `extracted_entities` | At least regex-extracted entities (may be empty for unstructured text) |
| `failure_mode_tags` | From TSLAM or rule-based fallback |
| `operational_fingerprint` | Always populated |

### 3.4 Exit Conditions

| Condition | Next Stage |
|---|---|
| Fragment persisted with at least `emb_temporal` valid | Proceed to Stage 2 (Correlation) |

A fragment always exits Stage 1 successfully because temporal encoding cannot fail. Even if all T-VEC calls and TSLAM fail, the fragment is persisted with temporal-only embeddings and regex-extracted entities.

### 3.5 Failure Path

| Failure | Handling | Recovery |
|---|---|---|
| TSLAM-8B unavailable | Regex entity extraction + rule-based failure classification | Automatic; fragment proceeds with lower-quality entities |
| T-VEC unavailable (all 3 calls) | All embedding columns NULL except temporal; all masks FALSE | Fragment proceeds; snap scoring uses temporal + entity overlap only |
| Shadow Topology unavailable | Topological embedding NULL; mask FALSE | Fragment proceeds; snap scoring excludes topological dimension |
| Database write failure | Fragment is not persisted; signal dead-lettered | Retry via dead-letter consumer (external to this flow) |

### 3.6 Provenance

- `ProvenanceLogger` records: fragment_id, tenant_id, timestamp, enrichment duration, which models succeeded/failed, mask state.
- Stored in `AbeyanceFragmentORM` row alongside embeddings.

---

## 4. Stage 2: Correlation (Snap Scoring)

### 4.1 Entry Conditions

| Condition | Enforcement |
|---|---|
| A newly persisted `AbeyanceFragmentORM` (the "new fragment") exists with valid `fragment_id` | Output of Stage 1 |
| At least `emb_temporal` is non-NULL | Guaranteed by Stage 1 exit condition |

### 4.2 Processing Subsystems

| Subsystem | Reference | Processing |
|---|---|---|
| Candidate Retrieval | snap_scoring.md Section 11.3 | Entity-overlap-based retrieval produces candidate fragments from the same tenant. Bounded by `MAX_CANDIDATES_PER_FRAGMENT` (default: 50). |
| Per-Profile Scoring | snap_scoring.md Section 7 | For each candidate, for each failure-mode weight profile (5 profiles: DARK_EDGE, DARK_NODE, IDENTITY_MUTATION, PHANTOM_CI, DARK_ATTRIBUTE), compute the mask-aware per-dimension composite score. |
| Weight Redistribution | snap_scoring.md Section 5 | For each (new_fragment, candidate, profile) triple, determine available dimensions, redistribute weights proportionally, compute weighted composite. |
| Temporal Modifier | snap_scoring.md Section 7.2 | Apply recency/freshness modifier `[0.5, 1.0]` to composite score. |
| Sidak Correction | snap_scoring.md Section 11.2 | Adjust snap threshold for multiple-comparisons when multiple profiles are evaluated for the same candidate pair. |
| Decision Classification | snap_scoring.md Section 8 | Classify each scored pair as `SNAP`, `NEAR_MISS`, `AFFINITY`, or `NONE`. |

**Iteration bound**: `MAX_CANDIDATES_PER_FRAGMENT (50) x NUM_FAILURE_PROFILES (5) = 250` scoring operations per incoming fragment. This is the maximum; actual count may be lower if fewer candidates are retrieved.

### 4.3 Output

For each (new_fragment, candidate, profile) triple: a `SnapDecisionRecord` persisted to `snap_decision_log`, containing:

| Field | Range |
|---|---|
| Per-dimension scores (semantic, topological, temporal, operational, entity_overlap) | `[0.0, 1.0]` or NULL if unavailable |
| Dimension availability flags | Boolean per embedding dimension |
| Base weights and adjusted weights | Sum to 1.0 |
| Raw composite score | `[0.0, 1.0]` |
| Temporal modifier | `[0.5, 1.0]` |
| Final score | `[0.0, 1.0]` |
| Decision | One of: `SNAP`, `NEAR_MISS`, `AFFINITY`, `NONE` |
| Calibration status | `INITIAL_ESTIMATE` or `EMPIRICALLY_VALIDATED` |

Additionally, `SNAP` and `AFFINITY` decisions are forwarded to the accumulation graph as edges.

### 4.4 Exit Conditions

| Condition | Next Stage |
|---|---|
| All candidate pairs scored and all `SnapDecisionRecord`s persisted | Proceed to Stage 3 (Surprise Evaluation) for each record |
| Zero candidates retrieved | No scoring occurs; no `SnapDecisionRecord`s produced; flow terminates for this fragment at this stage (no surprise evaluation, no hypothesis generation) |

### 4.5 Failure Path

| Failure | Handling | Recovery |
|---|---|---|
| Candidate retrieval fails (DB error) | No candidates; flow terminates for this fragment | Retry via dead-letter or next enrichment cycle picks up the fragment as a candidate for future signals |
| Individual scoring computation fails (arithmetic error) | That specific (fragment, candidate, profile) triple is logged as failed and skipped; other triples proceed | Logged for investigation; no retry (deterministic inputs would produce same failure) |
| Database write failure for `SnapDecisionRecord` | Record lost; surprise evaluation cannot run for this record | Dead-letter retry or accepted data loss (the fragment and embeddings remain; the pair can be re-scored) |

### 4.6 Provenance

- Every `SnapDecisionRecord` contains full scoring provenance: per-dimension scores, mask state, base/adjusted weights, thresholds, and decision classification.
- `multiple_comparisons_k` records how many profiles were evaluated for the same candidate pair.

---

## 5. Stage 3: Surprise Evaluation

### 5.1 Entry Conditions

| Condition | Enforcement |
|---|---|
| A persisted `SnapDecisionRecord` exists | Output of Stage 2 |
| The record has a valid `final_score` in `[0.0, 1.0]` | INV-3 from snap scoring |
| The record has a valid `tenant_id` and `failure_mode_profile` | Schema constraints |

### 5.2 Processing Subsystems

| Subsystem | Reference | Processing |
|---|---|---|
| Histogram Lookup | surprise_engine.md Section 3 | Load or create rolling histogram for partition `(tenant_id, failure_mode_profile)`. 50 bins over `[0.0, 1.0]`, exponential decay alpha=0.995. |
| Composite Surprise Computation | surprise_engine.md Section 4 | Compute `surprise(x) = -log2(P_smoothed(bin))` with Laplace smoothing. Capped at 20 bits. |
| Per-Dimension Surprise (diagnostic) | surprise_engine.md Section 4.3 | Compute surprise per available dimension score using dimension-specific histograms. Stored but does not independently trigger escalation. |
| Histogram Update | surprise_engine.md Section 8.2 | Score-before-update ordering: surprise computed BEFORE current observation is added to histogram. Decay applied before add. |
| Threshold Computation | surprise_engine.md Section 5 | 98th percentile of surprise distribution histogram. Floor at `DEFAULT_THRESHOLD = 6.64 bits`. |
| Escalation Classification | surprise_engine.md Section 6.3 | Classify as `DISCOVERY`, `DRIFT_ALERT`, or `CALIBRATION_ALERT`. |

### 5.3 Output

**If composite surprise < threshold**: No surprise event. Histograms updated. Flow terminates for this `SnapDecisionRecord`. This is the common case (~98% of records).

**If composite surprise >= threshold**: A `SurpriseEvent` is persisted to `surprise_event` table and classified:

| Escalation Type | Downstream Path |
|---|---|
| `DISCOVERY` | Proceed to Stage 4 (Hypothesis Generation) |
| `DRIFT_ALERT` | Operational alert emitted (Prometheus metrics); flow exits discovery path |
| `CALIBRATION_ALERT` | Operational alert emitted; flow exits discovery path |

**If insufficient data** (`total_mass < MINIMUM_MASS = 30`): No surprise computed. Histogram updated. Operational gauge emitted. Flow terminates for this record.

### 5.4 Exit Conditions

| Condition | Next Stage |
|---|---|
| `SurpriseEvent` with `escalation_type = DISCOVERY` persisted | Proceed to Stage 4 |
| `SurpriseEvent` with `escalation_type = DRIFT_ALERT` or `CALIBRATION_ALERT` | Exit discovery flow; operational alert path |
| No surprise event (below threshold or insufficient data) | Exit discovery flow; normal operation |

### 5.5 Failure Path

| Failure | Handling | Recovery |
|---|---|---|
| Histogram state corrupted (NaN, negative counts) | Reset histogram for this partition to zero state; log warning | Histogram rebuilds from subsequent observations within ~100-500 snap evaluations |
| Database write failure for `SurpriseEvent` | Event persisted to in-memory discovery queue only; may be lost on process crash | Recovery: surprise engine re-evaluates unprocessed snap decisions on startup using persisted histogram state |
| Log2 arithmetic error (should not happen with Laplace smoothing) | Surprise capped at 20 bits; error logged | Defensive: Laplace smoothing guarantees positive bin probabilities |

### 5.6 Provenance

- `SurpriseEvent` contains: composite surprise value, per-dimension surprises, threshold used, threshold percentile, distribution sample count, escalation type classification.
- Links back to source `SnapDecisionRecord` via `snap_decision_id`.
- Distribution state snapshot recoverable from `surprise_distribution_state` table.

---

## 6. Stage 3a: Parallel Path -- Accumulation Graph Update

This stage runs in parallel with Stage 3, not sequentially after it. It is a separate consumer of Stage 2 output.

### 6.1 Entry Conditions

| Condition | Enforcement |
|---|---|
| A `SnapDecisionRecord` with `decision IN ('SNAP', 'AFFINITY')` exists | Stage 2 decision classification |

### 6.2 Processing

The accumulation graph receives `(fragment_a_id, fragment_b_id, affinity_score, failure_mode)` as a new edge. Clusters grow as edges accumulate. When a cluster exceeds thresholds, it becomes a trigger for hypothesis generation.

**Cluster growth trigger conditions** (from hypothesis_engine.md Section 3.1):
- `cluster_size >= MIN_CLUSTER_SIZE (5)`
- Cluster grew by `>= GROWTH_DELTA (2)` fragments in last `GROWTH_WINDOW (24h)`
- No active hypothesis already covers this cluster (50% fragment overlap check)

### 6.3 Output

If trigger conditions met: a `GenerationTrigger` with `trigger_type = 'recurring_snap_pattern'` is submitted to the hypothesis generation pipeline (Stage 4).

### 6.4 Exit Conditions

| Condition | Next Stage |
|---|---|
| Cluster trigger fired | Proceed to Stage 4 (Hypothesis Generation) |
| No cluster trigger (cluster below threshold, already covered) | Exit; accumulation graph updated, no further action |

---

## 7. Stage 4: Hypothesis Generation

### 7.1 Entry Conditions

Two entry paths converge here:

**Path A -- Surprise-triggered**:

| Condition | Enforcement |
|---|---|
| `SurpriseEvent` with `escalation_type = DISCOVERY` | Stage 3 exit condition |
| `composite_surprise >= HYPOTHESIS_SURPRISE_FLOOR (8.0 bits)` | hypothesis_engine.md Section 3.2 |
| No active hypothesis covers the same fragment pair + failure mode | Deduplication check against `hypothesis` table |

**Path B -- Accumulation-triggered**:

| Condition | Enforcement |
|---|---|
| Cluster trigger from Stage 3a | Stage 3a exit condition |
| `cluster_size >= MIN_CLUSTER_SIZE (5)` | hypothesis_engine.md Section 3.1 |
| `cluster_growth >= GROWTH_DELTA (2)` in last `GROWTH_WINDOW (24h)` | hypothesis_engine.md Section 3.1 |
| No active hypothesis covers >= 50% of cluster fragments | Deduplication check |

### 7.2 Processing Subsystems

| Subsystem | Reference | Processing |
|---|---|---|
| Context Assembly | hypothesis_engine.md Section 4.4 | Retrieve fragment summaries, snap scores, entity overlap, temporal context, dimensional surprises. Cap at `MAX_PROMPT_FRAGMENTS (8)` fragments, 3000 input tokens. |
| TSLAM-8B Hypothesis Generation | hypothesis_engine.md Section 4.1 | Send structured prompt to TSLAM-8B (or 4B fallback). Parse JSON response with schema validation. Timeout: 45 seconds. |
| Template Fallback | hypothesis_engine.md Section 4.3 | If TSLAM unavailable or output fails validation: deterministic template generates hypothesis with `generation_method = TEMPLATE_FALLBACK`. |
| Hypothesis Persistence | hypothesis_engine.md Section 8.1 | Persist `Hypothesis` row with status `proposed`, initial confidence `[0.1, 0.5]`, confirmation/refutation conditions, full generation provenance. |

### 7.3 Output

A persisted `Hypothesis` row with:

| Field | Value |
|---|---|
| `status` | `proposed` |
| `confidence` | `[0.1, 0.5]` (from TSLAM or 0.15 from template) |
| `confirmation_conditions` | 2-3 conditions (from TSLAM or template) |
| `refutation_conditions` | 2-3 conditions (from TSLAM or template) |
| `generation_trigger` | Full trigger context (fragment IDs, scores, surprise values) |
| `tslam_prompt_used` | Exact prompt text |
| `tslam_raw_response` | Exact TSLAM output |

### 7.4 Exit Conditions

| Condition | Next Stage |
|---|---|
| Hypothesis persisted with `status = proposed` | Proceed to Stage 5 (Evidence Testing) |

**Exit is guaranteed**: Template fallback ensures a hypothesis is always created, even without TSLAM. The only case where no hypothesis is created is if the deduplication check identifies an existing active hypothesis covering the same pattern -- in which case new evidence is routed to the existing hypothesis (Stage 5) instead.

### 7.5 Failure Path

| Failure | Handling | Recovery |
|---|---|---|
| TSLAM-8B unavailable | Retry queue (3 attempts, exponential backoff: 30s, 60s, 120s). After exhaustion: template fallback. | hypothesis_engine.md Section 7.2 |
| TSLAM output fails JSON validation | Raw output logged; template fallback generates hypothesis tagged `generation_quality = VALIDATION_FAILED` | Hypothesis functional; TSLAM output available for debugging |
| Generation queue full (100 capacity) | Request dropped; logged | Trigger data persisted in surprise_event/accumulation_graph tables; can be recovered by periodic sweep |
| Database write failure for hypothesis | Retry via `hypothesis_generation_queue` table | hypothesis_engine.md Section 8.3 |

### 7.6 Provenance

- `generation_trigger` JSONB: complete trigger context.
- `tslam_prompt_used`: exact prompt.
- `tslam_raw_response`: exact model output.
- `tslam_model_version` + `tslam_backend`: model identification.
- `generation_latency_ms`: wall-clock timing.
- `generation_method`: `tslam` or `TEMPLATE_FALLBACK`.

---

## 8. Stage 5: Evidence Testing

### 8.1 Entry Conditions

| Condition | Enforcement |
|---|---|
| A `Hypothesis` with `status IN ('proposed', 'testing')` exists | Output of Stage 4, or existing hypothesis receiving new evidence |
| New snap decisions or surprise events are arriving for the same tenant + failure mode | Continuous stream from Stages 2 and 3 |

### 8.2 Processing Subsystems

| Subsystem | Reference | Processing |
|---|---|---|
| Evidence Matching | hypothesis_engine.md Section 6.1 | Each new `SnapDecisionRecord` is checked against all active hypotheses (`status IN ('proposed', 'testing')`) for entity overlap with the hypothesis entity set AND same failure mode profile. |
| Evidence Relevance Scoring | hypothesis_engine.md Section 6.2 | Determine `supporting`, `contradicting`, or `neutral` relevance based on snap decision outcome and entity overlap. Compute confidence impact delta. Filter by `MIN_EVIDENCE_IMPACT (0.005)`. |
| Confidence Update | hypothesis_engine.md Section 6.3 | `new_confidence = clamp(confidence + impact, 0.0, 1.0)`. Logged in `confidence_history`. |
| Confirmation Condition Evaluation | hypothesis_engine.md Section 6.4 | Machine-evaluable conditions re-evaluated after each evidence attachment. Operator-evaluable conditions presented in review UI. |
| Refutation Condition Evaluation | hypothesis_engine.md Section 6.5 | Same dual-path evaluation. A single triggered refutation condition is sufficient for refutation. |
| Status Transition Evaluation | hypothesis_engine.md Section 5.3 | Check `proposed -> testing`, `testing -> confirmed`, `testing -> refuted` transition conditions after each evidence event. |
| Confidence Decay | hypothesis_engine.md Section 5.2 | `CONFIDENCE_DECAY_RATE = 0.01/day` applied by periodic sweep (`LIFECYCLE_SWEEP_INTERVAL = 1 hour`). |
| TTL Enforcement | hypothesis_engine.md Section 5.2 | `PROPOSED_TTL (72h)`, `TESTING_TTL (14d)` checked by periodic sweep. |

**First evidence transition**: When a `proposed` hypothesis receives its first evidence (supporting or contradicting), it transitions to `testing`.

### 8.3 Iteration Bounds

| Bound | Value | Rationale |
|---|---|---|
| Max active hypotheses per tenant | 50 (practical bound) | Evidence matching is O(H) per snap decision; 50 is extreme upper bound |
| Max evidence records per hypothesis | Unbounded in schema, but confidence saturates at 1.0 or drains to 0.0 | Bounded by TTL: hypotheses retire after `TESTING_TTL (14d)` without new evidence |
| Confidence decay iterations | Bounded by `TESTING_TTL / LIFECYCLE_SWEEP_INTERVAL = 336` ticks max | After 336 hours without evidence, confidence has decayed by 14 * 0.01 = 0.14. Combined with natural TTL expiry, this ensures retirement. |
| Evidence per snap decision | O(H) = O(50) hypothesis checks per snap decision | Each check is Jaccard on small entity sets, O(30) per check |

### 8.4 Output

Continuously updated `Hypothesis` rows. Status transitions when thresholds are reached:

| Transition | Condition |
|---|---|
| `proposed -> testing` | First evidence arrives |
| `testing -> confirmed` | `confidence >= 0.75` AND at least 1 confirmation condition satisfied |
| `testing -> refuted` | `confidence <= 0.10` OR any refutation condition triggered |
| `proposed -> retired` | No evidence within 72 hours |
| `testing -> retired` | No new evidence within 14 days |

### 8.5 Exit Conditions

| Condition | Next Stage |
|---|---|
| Hypothesis transitions to `confirmed` | Proceed to Stage 6a (Confirmation / Discovery) |
| Hypothesis transitions to `refuted` | Proceed to Stage 6b (Refutation) |
| Hypothesis transitions to `retired` (TTL expiry) | Proceed to Stage 6c (Retirement) |

### 8.6 Failure Path

| Failure | Handling | Recovery |
|---|---|---|
| Evidence matching fails (DB error on entity lookup) | Evidence not attached; hypothesis unchanged | Next snap decision retries the match |
| Confidence update arithmetic error | Clamped to `[0.0, 1.0]` by schema CHECK constraint | Defensive: `clamp()` on every update |
| Periodic sweep fails | TTL not enforced for this cycle; retried next cycle | Hypotheses remain in current status until next successful sweep |

### 8.7 Provenance

- `hypothesis_evidence` table: every evidence record with source_id, source_table, relevance, impact, fragment_ids.
- `confidence_history` JSONB: every confidence change with timestamp, old/new values, reason, evidence_id.
- `status_history` JSONB: every transition with timestamp, old/new status, reason, trigger type.

---

## 9. Stage 6: Terminal States

### 9.1 Stage 6a: Confirmation (Discovery)

**Entry**: Hypothesis `status = confirmed`.

**Processing**:
- `confirmed_at` timestamp recorded.
- Hypothesis surfaced in operator dashboard with claim text, supporting evidence links, and confirmation condition details.
- `CONFIRMED_TTL (90 days)`: after 90 days, hypothesis transitions to `retired` unless renewed by operator action.

**Output**: A **Discovery** -- a confirmed, falsifiable claim with full provenance chain from raw signal through enrichment, correlation, surprise, hypothesis, and evidence accumulation.

**Provenance**: Complete chain is reconstructable:
1. Raw signals (fragments) that entered Stage 1.
2. Enrichment results (embeddings, entities, failure modes).
3. Snap decisions that connected fragments (scores, weights, masks).
4. Surprise events that triggered hypothesis generation (surprise values, thresholds).
5. TSLAM hypothesis generation (prompt, response, claim).
6. Every piece of evidence that moved confidence (evidence records).
7. The threshold crossing that confirmed the hypothesis (confidence_history, status_history).

### 9.2 Stage 6b: Refutation (Archived Negative)

**Entry**: Hypothesis `status = refuted`.

**Processing**:
- `refuted_at` timestamp recorded.
- Hypothesis remains queryable for `REFUTED_RETENTION (30 days)`, then transitions to `retired`.
- If new contradicting evidence later emerges for a previously `confirmed` hypothesis, a NEW child hypothesis is generated referencing the parent via `parent_hypothesis_id`. The confirmed hypothesis is not modified.

**Output**: An archived negative result. The pattern was investigated and found to not hold.

**Provenance**: Same chain as confirmation, plus the specific evidence or condition that triggered refutation.

### 9.3 Stage 6c: Retirement (Inconclusive)

**Entry**: Hypothesis `status = retired` (from any prior status via TTL expiry).

**Processing**:
- `retired_at` timestamp recorded.
- Hypothesis no longer receives evidence.
- Hypothesis remains in database indefinitely for audit.

**Output**: An inconclusive result. The pattern was observed but insufficient evidence accumulated within the time bounds.

---

## 10. Boundedness Guarantees

Every iteration and loop in this flow has a declared maximum. There are no infinite cycles.

### 10.1 Per-Fragment Processing Bounds

| Stage | Operation | Maximum Iterations | Derivation |
|---|---|---|---|
| Stage 1 (Enrichment) | T-VEC embedding calls | 3 | Semantic + Topological + Operational |
| Stage 1 (Enrichment) | TSLAM calls | 1 | Single entity extraction + hypothesis call |
| Stage 1 (Enrichment) | Shadow topology entity resolutions | 30 | `entities[:30]` cap in `build_semantic_text` |
| Stage 2 (Correlation) | Candidate retrieval | MAX_CANDIDATES = 50 | Hard limit on retrieval query |
| Stage 2 (Correlation) | Scoring operations | 50 x 5 = 250 | Candidates x profiles |
| Stage 3 (Surprise) | Histogram updates per record | 7 | 1 composite + 5 per-dimension + 1 surprise histogram |
| Stage 3 (Surprise) | Surprise events per record | 1 | At most one event per snap decision record |
| Stage 4 (Hypothesis) | TSLAM calls per trigger | 1 + 3 retries = 4 | MAX_RETRY_ATTEMPTS = 3 |
| Stage 4 (Hypothesis) | Hypotheses generated per trigger | 1 | One hypothesis per trigger (or zero if deduplicated) |

### 10.2 Lifecycle Time Bounds

| Hypothesis Status | Maximum Duration | Enforcement |
|---|---|---|
| `proposed` | 72 hours | `PROPOSED_TTL`; periodic sweep retires stale proposed hypotheses |
| `testing` | 14 days | `TESTING_TTL`; periodic sweep retires stale testing hypotheses |
| `confirmed` | 90 days | `CONFIRMED_TTL`; periodic sweep retires aged confirmed hypotheses |
| `refuted` | 30 days | `REFUTED_RETENTION`; periodic sweep retires to archived state |

### 10.3 Evidence Accumulation Bounds

| Bound | Value | Effect |
|---|---|---|
| Confidence range | `[0.0, 1.0]` | `clamp()` prevents runaway accumulation |
| Confirmation threshold | 0.75 | Hypothesis confirmed once reached (with condition satisfied) |
| Refutation threshold | 0.10 | Hypothesis refuted once reached |
| Confidence decay | 0.01/day | Prevents indefinite high-confidence without fresh evidence |
| Max active hypotheses per tenant | ~50 (practical) | Evidence matching cost bounded at O(50) per snap decision |

### 10.4 No Feedback Loops

The flow is acyclic. There is no path where a later stage feeds back into an earlier stage within the same cycle:

- A confirmed discovery does NOT generate new fragments (Stage 1 input comes from external signals only).
- A refuted hypothesis does NOT modify snap scoring weights (weight profiles are static until empirical calibration, which is an offline process).
- A surprise event does NOT modify the enrichment pipeline.
- Evidence accumulation does NOT retroactively change snap scores (scores are write-once).

The only "loop" is the temporal one: new signals arrive over time and traverse the same pipeline. But each traversal is independent -- the pipeline processes each signal exactly once through Stages 1-3, and hypothesis lifecycle (Stages 4-6) runs asynchronously with bounded time limits.

---

## 11. Determinism Contract

### 11.1 Stage-Level Determinism

| Stage | Deterministic? | Condition |
|---|---|---|
| Stage 1 (Enrichment) | Yes* | *TSLAM-8B and T-VEC are deterministic at temperature=0. Sinusoidal encoding is pure math. Regex extraction is deterministic. |
| Stage 2 (Correlation) | Yes | Cosine similarity on float64 is deterministic per IEEE 754 on same platform. Weight redistribution is pure arithmetic. Clamp is pure function. |
| Stage 3 (Surprise) | Yes | Histogram operations are deterministic given same input sequence. Laplace smoothing and log2 are deterministic. |
| Stage 3a (Accumulation) | Yes | Graph edge insertion and cluster size computation are deterministic. |
| Stage 4 (Hypothesis) | Partial | TSLAM-8B at temperature=0 is deterministic for same input. Template fallback is deterministic. However, TSLAM availability may vary, causing different generation paths (TSLAM vs template). |
| Stage 5 (Evidence) | Yes | Evidence matching (Jaccard), confidence update (arithmetic), threshold comparison are all deterministic. |
| Stage 6 (Terminal) | Yes | Status transitions are boolean predicates on deterministic inputs. |

### 11.2 Flow-Level Determinism

Given identical:
- Input signal (raw_content, source_type, event_timestamp, tenant_id)
- Database state (existing fragments, snap decisions, hypotheses)
- Model availability (TSLAM, T-VEC)

The flow produces identical:
- Fragment embeddings and masks
- Snap decision records and scores
- Surprise events (or absence thereof)
- Hypothesis generation (or deduplication decision)
- Evidence matching and confidence updates
- Terminal state transitions

### 11.3 Cross-Platform Note

IEEE 754 float64 arithmetic may produce slightly different results across CPU architectures due to extended-precision intermediate results. The flow is deterministic within a single deployment but not guaranteed bit-identical across different hardware. This is acceptable: the system runs on a single deployment at a time.

---

## 12. End-to-End Latency Budget

| Stage | Expected Latency | Bottleneck |
|---|---|---|
| Stage 1 (Enrichment) | 50-500ms | TSLAM-8B (~300ms GPU) + 3x T-VEC (~50ms each, parallel) + Shadow Topology lookup (~20ms) |
| Stage 2 (Correlation) | 10-100ms | 50 candidates x 5 profiles = 250 cosine computations on float64 vectors |
| Stage 3 (Surprise) | <1ms | O(1) histogram operations, in-memory |
| Stage 3a (Accumulation) | 1-10ms | Graph edge insertion + cluster size check |
| Stage 4 (Hypothesis) | 3-45s (async) | TSLAM-8B generation (~3s vLLM, ~30-60s llama-cpp). Does NOT block signal processing. |
| Stage 5 (Evidence) | 1-5ms per snap decision | O(50) Jaccard computations per snap decision |
| Stage 6 (Terminal) | <1ms | Boolean predicate evaluation |

**Critical path** (synchronous, blocking per-fragment): Stages 1 + 2 + 3 = ~60-600ms.

**Async path** (non-blocking): Stages 4 + 5 + 6 run asynchronously. Hypothesis generation does not block signal ingestion.

---

## 13. Monitoring and Observability

### 13.1 Per-Stage Metrics

| Stage | Metrics |
|---|---|
| Stage 1 | `enrichment_duration_ms`, `enrichment_mask_state{dim}`, `enrichment_tslam_fallback_rate`, `enrichment_tvec_failure_rate` |
| Stage 2 | `snap_candidates_retrieved`, `snap_decisions_total{decision}`, `snap_scoring_duration_ms`, `snap_dimensions_available{count}` |
| Stage 3 | `surprise_events_total{escalation_type}`, `surprise_threshold{tenant,profile}`, `surprise_insufficient_data{tenant,profile}` |
| Stage 3a | `accumulation_cluster_size`, `accumulation_trigger_fired_total` |
| Stage 4 | `hypothesis_generated_total{method}`, `hypothesis_tslam_latency_ms`, `hypothesis_queue_depth`, `hypothesis_retry_total` |
| Stage 5 | `evidence_attached_total{relevance}`, `hypothesis_confidence_distribution`, `hypothesis_transitions_total{from,to}` |
| Stage 6 | `discovery_confirmed_total`, `hypothesis_refuted_total`, `hypothesis_retired_total{reason}` |

### 13.2 Flow-Level Health Indicators

| Indicator | Healthy Range | Alert Condition |
|---|---|---|
| Enrichment success rate | > 99% | < 95% for 5 minutes |
| Snap scoring throughput | Matches ingestion rate | Backlog > 1000 unscored fragments |
| Surprise escalation rate | ~2% of snap decisions | > 10% or < 0.1% sustained for 1 hour |
| Hypothesis generation success rate | > 90% (including template fallback) | < 50% |
| Active hypothesis count per tenant | 1-50 | > 100 (runaway generation) or 0 for > 24h (pipeline stall) |
| Mean time from signal to discovery | Hours to days | Dependent on pattern frequency; no fixed alert |

---

## 14. Complete Flow Trace (Concrete Example)

This traces a single signal through the entire pipeline, referencing the telecom example from the input specifications.

### 14.1 Signal Arrival (t=0)

```
raw_content: "S1 setup failure on eNB-4412, tracking area 17,
              cause: transport-resource-unavailable"
source_type: ALARM
tenant_id: telco2
event_timestamp: 2026-03-15T02:15:00Z
```

### 14.2 Stage 1: Enrichment (t=0 to t=350ms)

- TSLAM-8B extracts entities: `[eNB-4412, TA-17, RNC-3, vendor-ericsson, sw-v22.3.1]`
- TSLAM-8B classifies failure mode: `DARK_EDGE (confidence=0.4)`
- T-VEC semantic embedding: 1536-dim vector (mask_semantic=TRUE)
- Shadow Topology: resolves eNB-4412 UUID, gets 2-hop neighbourhood
- T-VEC topological embedding: 1536-dim vector (mask_topological=TRUE)
- Sinusoidal temporal: 256-dim vector (always valid)
- T-VEC operational embedding: 1536-dim vector (mask_operational=TRUE)
- Fragment `frag-4412-s1` persisted. All masks TRUE.

### 14.3 Stage 2: Correlation (t=350ms to t=450ms)

- Candidate retrieval returns 12 fragments with entity overlap.
- Among them: `frag-7803-x2` (X2_HANDOVER_FAILURE on eNB-7803).
- Scoring `(frag-4412-s1, frag-7803-x2, DARK_EDGE)`:
  - All 5 dimensions available. No weight redistribution needed.
  - Composite score: 0.371. Temporal modifier: 0.95. Final score: 0.352.
  - Decision: `AFFINITY` (below snap threshold, above affinity threshold).
- SnapDecisionRecord persisted. Edge added to accumulation graph.

### 14.4 Stage 3: Surprise Evaluation (t=450ms to t=451ms)

- Partition `(telco2, DARK_EDGE)` histogram has total_mass=847.3.
- Score 0.352 falls in peak bin (0.34-0.36). Bin probability high.
- Composite surprise: 1.8 bits. Threshold: 8.3 bits.
- 1.8 < 8.3: No surprise event. Histogram updated. Flow ends for this record.

### 14.5 Stage 3a: Accumulation Graph (t=450ms, parallel)

- Edge `(frag-4412-s1, frag-7803-x2, 0.352, DARK_EDGE)` added to graph.
- Cluster containing these fragments has size 3. Below MIN_CLUSTER_SIZE (5). No trigger.

### 14.6 Subsequent Days (t=24h to t=72h)

Three more eNB pairs produce similar patterns. Cluster grows to size 7. Accumulation trigger fires:
- `cluster_size (7) >= MIN_CLUSTER_SIZE (5)`: YES
- `growth (4) >= GROWTH_DELTA (2) in last 24h`: YES
- No existing hypothesis covers this cluster: YES

Meanwhile, a high-scoring pair (`final_score = 0.68`) triggers surprise:
- Composite surprise: 12.5 bits >= threshold 8.3 bits: TRIGGERED.
- Escalation type: DISCOVERY (2 dimensions with high surprise, <= 2).

### 14.7 Stage 4: Hypothesis Generation (t=72h)

Both triggers (accumulation cluster + surprise DISCOVERY) converge. Deduplication: since both reference overlapping fragments, a single hypothesis is generated.

TSLAM-8B generates:
```
Claim: "Software version 22.3.1 on Ericsson eNBs introduces a transport-layer
        defect that causes correlated S1 setup failures and X2 handover failures
        across topologically unrelated base stations during maintenance windows."
Status: proposed
Confidence: 0.25
```

### 14.8 Stage 5: Evidence Testing (t=72h to t=9d)

- First evidence attaches: hypothesis transitions `proposed -> testing`.
- 15 more supporting evidence records over 7 days.
- Confidence climbs: 0.25 -> 0.30 -> 0.38 -> ... -> 0.78.
- Machine-evaluable confirmation condition satisfied (3+ additional eNB pairs found).
- `confidence (0.78) >= CONFIRMATION_THRESHOLD (0.75)` AND condition satisfied.

### 14.9 Stage 6a: Confirmation (t=9d)

- Hypothesis transitions `testing -> confirmed`.
- `confirmed_at` timestamp recorded.
- Discovery surfaced in operator dashboard.

**Discovery**: A cross-tracking-area failure pattern in Ericsson sw-v22.3.1 eNBs, with full provenance from the original alarm signals through every scoring, surprise, and evidence step.

---

## 15. Invariants (Discovery Loop Level)

| ID | Statement | Enforcement |
|---|---|---|
| INV-DL1 | Every fragment passes through enrichment before correlation | Stage 2 entry requires persisted fragment from Stage 1 |
| INV-DL2 | Every snap decision is evaluated for surprise | Stage 3 is a synchronous post-hook on Stage 2 scoring |
| INV-DL3 | No hypothesis generated without meeting trigger thresholds | Entry conditions in Stage 4 enforce `HYPOTHESIS_SURPRISE_FLOOR` or `MIN_CLUSTER_SIZE` |
| INV-DL4 | No infinite hypothesis accumulation | TTLs bound every status: proposed (72h), testing (14d), confirmed (90d), refuted (30d) |
| INV-DL5 | No backward lifecycle transitions | Forward-only state machine in Stage 5; enforced by `evaluate_transitions()` |
| INV-DL6 | Flow is acyclic within a single signal processing cycle | No stage feeds back into a prior stage; accumulation and hypothesis lifecycle are async |
| INV-DL7 | All stages produce provenance records | Each stage specification requires provenance logging (Sections 3.6, 4.6, 5.6, 7.6, 8.7) |
| INV-DL8 | Maximum per-fragment processing is bounded | 250 scoring ops + 7 histogram updates + O(50) evidence matches per snap decision |
| INV-DL9 | Synchronous critical path completes in < 1 second | Stages 1-3 total: ~60-600ms; hypothesis generation is async |
| INV-DL10 | Template fallback guarantees hypothesis creation | TSLAM unavailability triggers deterministic template; no pipeline stall |
| INV-DL11 | Tenant isolation at every stage | All queries filtered by tenant_id; no cross-tenant operations |
| INV-DL12 | Discovery is fully reconstructable from provenance chain | fragment -> snap_decision -> surprise_event -> hypothesis -> evidence -> confirmation, all linked by foreign keys |
