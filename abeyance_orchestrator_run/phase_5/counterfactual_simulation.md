# Counterfactual Simulation Framework -- Discovery Mechanism #12

**Task**: D4.1 -- Counterfactual Simulation Framework
**Version**: 3.0
**Date**: 2026-03-16
**Status**: Specification
**Tier**: 4 (Advanced -- requires Tiers 1-3 stable)
**Depends on**: T1.4 (Snap Engine v3.0), D2.1 (Temporal Sequence), Tier 3 mechanisms
**Enables**: Causal weight validation, hypothesis pruning, false-positive root cause analysis

---

## 1. Problem Statement

The snap engine (T1.4) scores fragment pairs and records its decisions in `snap_decision_log`. The temporal sequence model (D2.1) records the ordered observation history of each entity and maintains transition probability matrices. Both systems observe and classify. Neither system answers the question: **did a specific event actually cause a downstream snap?**

The current system cannot distinguish between:

1. **Genuine causal precedents**: Fragment A, once observed, reliably produces downstream snap decisions involving its neighbours. Removing A from history would have changed those outcomes.
2. **Spurious correlates**: Fragment A co-occurs with the causal event but removing it would not change any downstream snap score by a meaningful margin.

Without this distinction, Abeyance Memory cannot validate its own importance weights (Section 6.4 of T1.4), cannot prune false positive snaps by identifying that their triggering evidence was structurally removable, and cannot build a feedback signal for Tier 3 hypothesis generation.

Counterfactual Simulation answers this question by operationally removing a candidate event from a bounded historical window and replaying the snap scoring that originally ran against that window. The difference in downstream snap scores is the causal impact metric.

**This mechanism is a batch job only.** It runs during maintenance windows. It produces no real-time side effects.

---

## 2. Scope Boundaries

### 2.1 In Scope

- Operational definition of "remove and re-score" applied to `entity_sequence_log` and `snap_decision_log`
- Replay scope bounds: maximum fragments and maximum time window per simulation run
- Batch job scheduling: maintenance window only, not real-time
- Causal impact metric: difference in downstream snap scores
- Storage schema for simulation result records
- Computational complexity analysis: O(n) replays per candidate, total bound
- Concrete telecom example

### 2.2 Explicitly Out of Scope

- Snap engine internals (T1.4 is consumed as a read-only service)
- Sequence model internals (D2.1 is consumed as a read-only service)
- Real-time causal inference or online counterfactual computation
- Hypothesis generation from simulation results (Tier 3 consumes these records)
- Causal graph construction (Tier 4 task D4.3, separate specification)

---

## 3. Operational Definition: "Remove and Re-score"

### 3.1 The Three-Step Protocol

Given a **candidate fragment** `F_c` and a bounded **replay window** `[T_start, T_end]`:

**Step 1 — Baseline extraction**

Query `snap_decision_log` for all snap decisions that evaluated `F_c` as either `new_fragment_id` or `candidate_fragment_id` within the replay window. These are the **baseline decisions** — what the snap engine actually decided with `F_c` present.

```
baseline_decisions = SELECT * FROM snap_decision_log
    WHERE tenant_id = :tenant_id
      AND timestamp BETWEEN :T_start AND :T_end
      AND (new_fragment_id = :F_c OR candidate_fragment_id = :F_c)
```

Additionally, collect **downstream decisions**: snap decisions involving fragments that snapped to `F_c` (fragments that received `decision = 'SNAP'` with `F_c` as a party). These downstream fragments may have generated further snaps with other fragments — their scores depended indirectly on `F_c` being in the accumulation graph.

```
downstream_fragment_ids = {row.new_fragment_id for row in baseline_decisions
                           where row.decision = 'SNAP'} |
                          {row.candidate_fragment_id for row in baseline_decisions
                           where row.decision = 'SNAP'}
downstream_fragment_ids -= {F_c}  # exclude F_c itself

downstream_decisions = SELECT * FROM snap_decision_log
    WHERE tenant_id = :tenant_id
      AND timestamp BETWEEN :T_start AND :T_end
      AND (new_fragment_id = ANY(:downstream_fragment_ids)
           OR candidate_fragment_id = ANY(:downstream_fragment_ids))
```

The union of `baseline_decisions` and `downstream_decisions` constitutes the **affected decision set**.

**Step 2 — Counterfactual replay**

For each pair `(F_a, F_b)` in the affected decision set where neither `F_a` nor `F_b` is `F_c`, re-score the pair using the v3.0 snap engine with the **same weight profile** that was applied in the original decision (read from `snap_decision_log.failure_mode_profile`).

This re-scoring is pure computation: the fragment embeddings and masks are read from `abeyance_fragment` as they exist now (they are write-once after enrichment, so they are identical to what existed at original score time). The temporal modifier is recomputed using the original `event_timestamp` values, not the current time.

For pairs where `F_c` is one of the fragments (`F_a = F_c` or `F_b = F_c`), the counterfactual score is defined as **undefined** — the pair would not exist in a world without `F_c`. These pairs are excluded from the delta computation.

**Step 3 — Delta computation**

For each re-scored pair, compute the causal impact delta:

```
delta(F_a, F_b) = counterfactual_final_score(F_a, F_b) - baseline_final_score(F_a, F_b)
```

A negative delta means removing `F_c` would have lowered the snap score between `F_a` and `F_b`. A delta near zero means `F_c` had no meaningful causal role in the `F_a`—`F_b` affinity.

**Note on the re-scoring mechanism**: The counterfactual replay does NOT literally delete `F_c` from any production table. It identifies which downstream pairs were in scope, re-runs score computation using the v3.0 engine function (`score_pair_v3`) in read-only mode, and records the delta. The production `snap_decision_log` and `abeyance_fragment` tables are never modified.

### 3.2 Why This Constitutes a Valid Counterfactual

The snap engine (T1.4, Section 7.3) guarantees full determinism: given the same fragment pair and weight profile, it always produces the same output. The temporal modifier uses only `event_timestamp` values (stored immutably on fragments), not wall-clock time. This means:

- `baseline_final_score(F_a, F_b)` can be read directly from `snap_decision_log` — no recomputation needed.
- `counterfactual_final_score(F_a, F_b)` is recomputed by calling `score_pair_v3` with the stored embeddings and stored event timestamps.

The two scores are directly comparable because they use identical inputs and an identical scoring function. The only difference in the counterfactual world is that `F_c` is absent — no path-level or accumulation-graph effects are captured. This is an **interventional counterfactual at the scoring layer**, not a full causal-graph intervention. This scope limitation is intentional and is why Tier 4 also specifies a separate causal graph construction task (D4.3).

---

## 4. Replay Scope Bounds

### 4.1 Motivation for Bounding

The affected decision set for a highly-connected fragment in a large tenant can be unbounded. A fragment that snapped to 40 other fragments, each of which snapped to 20 more, produces a decision fan-out that is quadratic in the worst case. The simulation must be bounded to prevent maintenance jobs from running for hours.

### 4.2 Bound Parameters

| Parameter | Default | Maximum Allowed | Notes |
|---|---|---|---|
| `max_replay_fragments` | 500 | 2,000 | Maximum distinct fragment IDs in the affected decision set. If exceeded, the simulation is abandoned for this candidate with status `SCOPE_EXCEEDED`. |
| `max_replay_window_days` | 14 | 30 | Maximum calendar span of the replay window `[T_start, T_end]`. The window is always anchored to `F_c.event_timestamp`. |
| `max_pairs_per_candidate` | 5,000 | 20,000 | Maximum (F_a, F_b) pairs re-scored per candidate. If the affected decision set expands beyond this, pairs are truncated to those with the highest baseline final score (highest-impact pairs first). |
| `max_candidates_per_batch` | 200 | 500 | Maximum candidates processed in one batch job invocation. |

### 4.3 Window Anchoring

The replay window is anchored to the candidate fragment's `event_timestamp`:

```
T_start = F_c.event_timestamp
T_end   = F_c.event_timestamp + max_replay_window_days
```

Rationale: causal effects flow forward in time. Events that occurred before `F_c` cannot have been caused by `F_c`. Constraining the window to forward-looking time reduces the affected decision set and aligns with the causal direction the simulation is testing.

The window may not exceed `max_replay_window_days` regardless of when `F_c` occurred. For candidates older than `now() - max_replay_window_days`, the simulation still runs against the historical window — it is not restricted to recent data.

### 4.4 Scope Overflow Handling

When the affected decision set exceeds `max_pairs_per_candidate` before truncation:

1. Sort all candidate pairs by `baseline_final_score DESC`.
2. Retain the top `max_pairs_per_candidate` pairs.
3. Record `scope_truncated = TRUE` in the simulation result with the count of discarded pairs.
4. Proceed with the truncated set.

The truncation strategy (highest-score-first) is deliberate: the highest-affinity downstream pairs are the ones most likely to have been meaningfully affected by `F_c`. Low-affinity pairs that scored near 0.0 will produce near-zero deltas regardless and are not worth computing.

---

## 5. Causal Impact Metric

### 5.1 Per-Pair Delta

For each re-scored pair `(F_a, F_b)`:

```
delta(F_a, F_b) = counterfactual_score - baseline_score
```

Both scores are in `[0.0, 1.0]`. The delta is in `[-1.0, 1.0]`.

- `delta < -0.05`: removing `F_c` would have meaningfully lowered this pair's affinity. `F_c` was a positive causal contributor.
- `-0.05 <= delta <= 0.05`: `F_c` had negligible impact on this pair.
- `delta > 0.05`: removing `F_c` would have raised this pair's affinity. This indicates `F_c` was acting as an attenuating intermediary (rare; possible via temporal modifier effects when `F_c` occupied a time slot that would otherwise compute a different temporal proximity).

The `±0.05` threshold for "negligible" is a configurable parameter (`min_meaningful_delta`, default `0.05`).

### 5.2 Aggregate Causal Impact Score

For a candidate fragment `F_c`, the aggregate causal impact score summarizes the per-pair deltas:

```
causal_impact_score(F_c) = MEAN(|delta(F_a, F_b)| for all replayed pairs)
```

This is the mean absolute delta across all pairs in the affected decision set. It measures how much `F_c` moves snap scores on average, regardless of direction.

Additionally compute:

```
causal_impact_positive(F_c)  = MEAN(max(0, -delta) for all pairs)
   # Average score reduction if F_c were absent — how much F_c contributes positively
causal_impact_negative(F_c)  = MEAN(max(0, delta) for all pairs)
   # Average score increase if F_c were absent — how much F_c suppresses affinities
```

### 5.3 Decision Flip Count

A **decision flip** occurs when the baseline decision and the counterfactual decision disagree:

```
flip(F_a, F_b) = TRUE if:
    (baseline_decision == 'SNAP' AND counterfactual_score < threshold) OR
    (baseline_decision != 'SNAP' AND counterfactual_score >= threshold)
```

Where `threshold` is the Sidak-corrected threshold from the original scoring context (stored in `snap_decision_log.threshold_applied`).

```
decision_flip_count(F_c) = COUNT(pairs where flip(F_a, F_b) = TRUE)
decision_flip_rate(F_c)  = decision_flip_count / total_replayed_pairs
```

A high flip rate indicates that `F_c` was load-bearing: its presence or absence changes binary snap outcomes, not just score magnitudes.

### 5.4 Relationship to Snap Engine Weight Profiles

The simulation results expose per-profile breakdowns. Because each snap decision records the `failure_mode_profile` used (from `snap_decision_log`), the delta can be aggregated by profile:

```
mean_delta_by_profile(F_c, profile) = MEAN(|delta| for pairs scored under `profile`)
```

This feeds directly into the weight calibration methodology (T1.4, Section 6.4): if `F_c` is a confirmed true positive for failure mode `DARK_NODE` and its removal produces a high delta only for `DARK_NODE`-profile pairs but not for `DARK_EDGE`-profile pairs, this supports the `DARK_NODE` weight profile's entity overlap emphasis as genuinely discriminative.

---

## 6. Batch Job Scheduling

### 6.1 Maintenance Window Constraint

The counterfactual simulation job runs **exclusively during maintenance windows**. It is not triggered by fragment ingestion events, not triggered by snap decisions, and not accessible via the real-time API path.

**Rationale**: Each simulation candidate requires re-scoring up to `max_pairs_per_candidate` fragment pairs. At 5,000 pairs per candidate and 200 candidates per batch, a single job run invokes up to 1,000,000 `score_pair_v3` calls. Each call reads two fragment rows (for embeddings) and performs vector arithmetic. This is a read-heavy, CPU-bound workload that must be isolated from the live ingestion and snap scoring paths.

### 6.2 Schedule

| Parameter | Value |
|---|---|
| Trigger type | Cron (maintenance window) |
| Default schedule | `0 2 * * 0` — Sundays at 02:00 local time |
| Duration budget | 4 hours maximum; job aborts if wall clock exceeds budget |
| Concurrency | Single instance per tenant; multiple tenants may run in parallel |
| Retry policy | No automatic retry on failure; next scheduled run handles backlog |

The schedule is configurable per tenant. High-volume tenants may need to run on shorter intervals (e.g., nightly) with a reduced `max_candidates_per_batch`.

### 6.3 Candidate Selection

The batch job selects candidates from the `counterfactual_candidate_queue` table (Section 7.3). Selection criteria:

1. `status = 'PENDING'`
2. `tenant_id = :current_tenant`
3. Order by `priority DESC, queued_at ASC` (highest-priority, oldest first)
4. Limit to `max_candidates_per_batch`

Candidates are enqueued by Tier 3 mechanisms (hypothesis generators) and by the operator API. They are not auto-enqueued by every snap decision — that would create unbounded queue growth. Tier 3 selects candidates based on anomaly signals (expectation violations, high-surprise fragments, identity mutations with large blast radius).

### 6.4 Job Phases

```
Phase 1: Candidate selection  (~1% of budget)
    SELECT candidates from queue, lock rows with SELECT FOR UPDATE SKIP LOCKED

Phase 2: Scope computation    (~4% of budget)
    For each candidate: expand affected decision set, apply bounds

Phase 3: Replay scoring       (~90% of budget)
    For each candidate: re-score pairs using score_pair_v3 in read-only mode

Phase 4: Result persistence   (~4% of budget)
    Write simulation results to counterfactual_simulation_result

Phase 5: Queue maintenance    (~1% of budget)
    Mark processed candidates as COMPLETED or FAILED
    Clean up stale PENDING entries older than max_queue_age_days (default: 30)
```

### 6.5 Abort and Partial Commit

If the job exceeds its duration budget:

1. The current candidate in flight is abandoned (not written).
2. All completed candidates in the current run are committed.
3. The abandoned candidate's queue status is reset to `PENDING`.
4. A job run record is written with `status = 'ABORTED'` and the count of completed candidates.

The job does not use a single transaction for the entire run. Each candidate result is committed independently to avoid holding long-lived locks.

---

## 7. Storage Schema

### 7.1 Table: `counterfactual_simulation_result`

One row per simulated candidate per batch run.

| Column | Type | Nullable | Constraints | Notes |
|---|---|---|---|---|
| id | UUID | NO | PRIMARY KEY | Simulation result ID |
| tenant_id | VARCHAR(100) | NO | NOT NULL | Tenant isolation |
| candidate_fragment_id | UUID | NO | NOT NULL, FK -> abeyance_fragment.id | The fragment whose removal was simulated |
| job_run_id | UUID | NO | NOT NULL, FK -> counterfactual_job_run.id | Which batch run produced this result |
| replay_window_start | TIMESTAMPTZ | NO | NOT NULL | T_start = F_c.event_timestamp |
| replay_window_end | TIMESTAMPTZ | NO | NOT NULL | T_end = T_start + window_days |
| replayed_pair_count | INTEGER | NO | NOT NULL | Total (F_a, F_b) pairs re-scored |
| scope_truncated | BOOLEAN | NO | NOT NULL, DEFAULT FALSE | TRUE if max_pairs_per_candidate was hit |
| discarded_pair_count | INTEGER | NO | NOT NULL, DEFAULT 0 | Pairs excluded by truncation |
| causal_impact_score | FLOAT | NO | NOT NULL | Mean absolute delta across all pairs |
| causal_impact_positive | FLOAT | NO | NOT NULL | Mean score reduction if F_c absent |
| causal_impact_negative | FLOAT | NO | NOT NULL | Mean score increase if F_c absent |
| decision_flip_count | INTEGER | NO | NOT NULL | Pairs where snap decision would change |
| decision_flip_rate | FLOAT | NO | NOT NULL | flip_count / replayed_pair_count |
| mean_delta_by_profile | JSONB | NO | NOT NULL | {"DARK_NODE": 0.12, "DARK_EDGE": 0.03, ...} |
| top_impacted_pairs | JSONB | NO | NOT NULL | Array of top 20 pairs by |delta|, see 7.1.1 |
| simulation_status | VARCHAR(20) | NO | NOT NULL | 'COMPLETE', 'SCOPE_EXCEEDED', 'NO_DECISIONS' |
| computed_at | TIMESTAMPTZ | NO | NOT NULL, server_default | When this result was written |

#### 7.1.1 `top_impacted_pairs` JSONB Structure

```json
[
  {
    "fragment_a_id": "uuid",
    "fragment_b_id": "uuid",
    "baseline_score": 0.8234,
    "counterfactual_score": 0.6102,
    "delta": -0.2132,
    "baseline_decision": "SNAP",
    "counterfactual_decision": "NEAR_MISS",
    "decision_flipped": true,
    "failure_mode_profile": "DARK_NODE"
  }
]
```

The top 20 pairs by absolute delta are stored inline. All pairs are stored in `counterfactual_pair_delta` (Section 7.2) for full auditability.

#### 7.1.2 Indexes

| Index | Columns | Type | Notes |
|---|---|---|---|
| ix_csr_tenant_candidate | (tenant_id, candidate_fragment_id) | BTREE | "What simulations have been run for this fragment?" |
| ix_csr_tenant_impact | (tenant_id, causal_impact_score DESC) | BTREE | "Which fragments had the highest causal impact?" |
| ix_csr_flip_rate | (tenant_id, decision_flip_rate DESC) | BTREE | "Which fragments most changed binary outcomes?" |
| ix_csr_job_run | (job_run_id) | BTREE | "All results from a given batch run" |

### 7.2 Table: `counterfactual_pair_delta`

One row per (F_a, F_b) pair per simulation. Full delta record for auditability.

| Column | Type | Nullable | Constraints | Notes |
|---|---|---|---|---|
| id | BIGSERIAL | NO | PRIMARY KEY | Row ID |
| simulation_result_id | UUID | NO | NOT NULL, FK -> counterfactual_simulation_result.id | Parent result |
| tenant_id | VARCHAR(100) | NO | NOT NULL | Denormalized for partition queries |
| fragment_a_id | UUID | NO | NOT NULL | First fragment in pair |
| fragment_b_id | UUID | NO | NOT NULL | Second fragment in pair |
| failure_mode_profile | VARCHAR(50) | NO | NOT NULL | Profile used in original scoring |
| baseline_score | FLOAT | NO | NOT NULL | Original final_score from snap_decision_log |
| counterfactual_score | FLOAT | NO | NOT NULL | Re-scored final_score without F_c |
| delta | FLOAT | NO | NOT NULL | counterfactual_score - baseline_score |
| baseline_decision | VARCHAR(20) | NO | NOT NULL | SNAP / NEAR_MISS / AFFINITY / NONE |
| counterfactual_decision | VARCHAR(20) | NO | NOT NULL | Decision under counterfactual score |
| decision_flipped | BOOLEAN | NO | NOT NULL | TRUE if decisions differ |

**Retention**: `counterfactual_pair_delta` rows are pruned when the parent `counterfactual_simulation_result` is older than `simulation_retention_days` (default: 180). The parent result row is retained indefinitely (it is small). Pair-level data is high-volume and is the pruning target.

#### 7.2.1 Index

| Index | Columns | Notes |
|---|---|---|
| ix_cpd_sim_result | (simulation_result_id) | Bulk read of all pairs for a given simulation |
| ix_cpd_fragment_a | (tenant_id, fragment_a_id) | "Which simulations involved this fragment?" |
| ix_cpd_flipped | (simulation_result_id, decision_flipped) WHERE decision_flipped = TRUE | Fast flip-only queries |

### 7.3 Table: `counterfactual_candidate_queue`

Queue of fragments to simulate. Written by Tier 3 mechanisms and operator API.

| Column | Type | Nullable | Constraints | Notes |
|---|---|---|---|---|
| id | UUID | NO | PRIMARY KEY | Queue entry ID |
| tenant_id | VARCHAR(100) | NO | NOT NULL | Tenant isolation |
| candidate_fragment_id | UUID | NO | NOT NULL, FK -> abeyance_fragment.id | Fragment to simulate |
| priority | INTEGER | NO | NOT NULL, DEFAULT 50 | 0=lowest, 100=highest. Tier 3 sets higher priority for anomaly-flagged candidates. |
| queued_at | TIMESTAMPTZ | NO | NOT NULL, server_default | When enqueued |
| queued_by | VARCHAR(100) | NO | NOT NULL | 'TIER3_HYPOTHESIS' / 'OPERATOR_API' / 'EXPECTATION_VIOLATION' |
| status | VARCHAR(20) | NO | NOT NULL, DEFAULT 'PENDING' | PENDING / IN_PROGRESS / COMPLETED / FAILED / CANCELLED |
| picked_up_at | TIMESTAMPTZ | YES | - | When the job claimed this entry |
| completed_at | TIMESTAMPTZ | YES | - | When the result was written |
| failure_reason | TEXT | YES | - | Populated on FAILED status |
| simulation_result_id | UUID | YES | FK -> counterfactual_simulation_result.id | Populated on COMPLETED |

#### 7.3.1 Uniqueness and Deduplication

```sql
CREATE UNIQUE INDEX uq_ccq_pending_candidate
    ON counterfactual_candidate_queue (tenant_id, candidate_fragment_id)
    WHERE status = 'PENDING';
```

This prevents the same fragment from being queued twice while a simulation is pending. If a Tier 3 mechanism tries to enqueue a fragment that already has a pending entry, the insert is silently ignored (ON CONFLICT DO NOTHING).

### 7.4 Table: `counterfactual_job_run`

One row per batch job invocation.

| Column | Type | Nullable | Notes |
|---|---|---|---|
| id | UUID | NO | PRIMARY KEY |
| tenant_id | VARCHAR(100) | NO | Tenant scope |
| started_at | TIMESTAMPTZ | NO | Job start time |
| ended_at | TIMESTAMPTZ | YES | Job end time (NULL if in progress) |
| status | VARCHAR(20) | NO | IN_PROGRESS / COMPLETE / ABORTED / FAILED |
| candidates_processed | INTEGER | NO | Count of completed candidates |
| candidates_attempted | INTEGER | NO | Count including failed/aborted |
| total_pairs_replayed | INTEGER | NO | Sum of replayed_pair_count across all results |
| duration_seconds | FLOAT | YES | Wall clock duration |
| abort_reason | TEXT | YES | Populated if status = ABORTED |

---

## 8. Computational Complexity

### 8.1 Per-Candidate Complexity

For a single candidate fragment `F_c`:

**Scope expansion**: Query `snap_decision_log` for decisions involving `F_c` — O(k) where k is the number of snap decisions that included `F_c`. With the replay window bound of 14 days, k is bounded in practice. Then expand to downstream pairs — O(k * m) where m is the average fanout per fragment. After applying `max_pairs_per_candidate`, the effective set is always bounded to `P_max` pairs.

**Re-scoring**: Each pair requires one call to `score_pair_v3`. The function reads two fragment rows (embedding vectors) and performs fixed-cost arithmetic:
- 4 cosine similarity computations: O(d) each where d = embedding dimension (1536 for semantic/topological/operational, 256 for temporal)
- 1 Jaccard computation: O(e) where e = average entity set size
- Weight redistribution: O(5) — constant
- Total per pair: O(d + e) ≈ O(d) since d >> e in practice

With at most `P_max = 5,000` pairs per candidate:

```
Cost per candidate = O(P_max * d) = O(5,000 * 1,536) = O(7.68M float64 operations)
```

This is dominated by memory bandwidth (loading embedding vectors), not arithmetic. On the VM 1 hardware (ARM, 12 GB RAM), each pair re-score takes approximately 0.5–2ms empirically (embedding reads + arithmetic), giving a worst-case per-candidate cost of 2–10 seconds.

### 8.2 Total Batch Complexity

```
Total cost = O(C * P_max * d)
```

Where:
- C = candidates per batch (max 200)
- P_max = pairs per candidate (max 5,000)
- d = embedding dimension constant (~1,536)

```
O(200 * 5,000 * 1,536) = O(1.536 * 10^9) float64 operations per batch
```

Within the 4-hour maintenance window, with ~2ms per pair re-score:

```
Total elapsed = 200 candidates * 5,000 pairs * 2ms = 2,000,000ms = ~33 minutes
```

This fits well within the 4-hour budget even at maximum scale parameters, leaving headroom for I/O-heavy phases (scope expansion queries, result persistence).

### 8.3 Bound Enforcement Guarantee

The bounds in Section 4.2 ensure the complexity is not O(n^2) in the total fragment count n. Without bounds:

- A hub fragment snapped to k other fragments, each with m downstream snaps, could produce O(k * m) pairs — potentially O(n^2) for highly connected components.
- The `max_pairs_per_candidate = 5,000` cap hard-truncates this to O(P_max) per candidate regardless of n.

The truncation strategy (highest-score-first) ensures the O(P_max) budget is spent on the most informationally valuable pairs. Low-score pairs trimmed by truncation have `delta ≈ 0` with high probability (a near-zero-affinity pair is unlikely to flip its decision) and contribute minimally to the aggregate causal impact score.

### 8.4 Database I/O

Scope expansion queries use the existing `snap_decision_log` indexes. The primary query pattern is:

```sql
-- Covered by ix_sdl_new_fragment or ix_sdl_candidate_fragment (assumed on snap_decision_log)
SELECT * FROM snap_decision_log
WHERE tenant_id = :t AND new_fragment_id = :F_c AND timestamp BETWEEN :T_start AND :T_end
UNION ALL
SELECT * FROM snap_decision_log
WHERE tenant_id = :t AND candidate_fragment_id = :F_c AND timestamp BETWEEN :T_start AND :T_end
```

Fragment embedding reads are the dominant I/O cost. For 200 candidates, each with up to 5,000 distinct fragment pair reads, the total distinct fragment loads are bounded by 200 * 5,000 * 2 = 2,000,000 row accesses. With fragment embeddings cached in PostgreSQL shared_buffers (hot fragments for active tenants), many of these will be buffer hits.

---

## 9. Telecom Example: Dark Node Counterfactual

### 9.1 Scenario

Tenant `telco2`. The Tier 3 hypothesis generator has flagged fragment `F_c` as a candidate for counterfactual analysis. `F_c` is a `DARK_NODE:ALARM:MAJOR` fragment for entity `ENB-4412`, observed at `T_c = 2026-03-10T08:00:00Z`. The hypothesis generator flagged it because T5.2 (Expectation Violation Detection) reported that this fragment represented an anomalous state skip: ENB-4412 transitioned directly from `NOMINAL` to `DARK_NODE:ALARM:MAJOR`, bypassing the usual `DARK_ATTRIBUTE:TELEMETRY_EVENT:WARNING` degradation phase (P=0.001 per the transition matrix).

The question: did `F_c` (the anomalous MAJOR alarm) causally drive the snaps that followed, or were those snaps driven by prior DARK_ATTRIBUTE fragments that would have snapped regardless?

### 9.2 Affected Decision Set Construction

Replay window: `[2026-03-10T08:00Z, 2026-03-24T08:00Z]` (14 days).

From `snap_decision_log`, the snap engine evaluated `F_c` against 38 candidate fragments during the window. 12 of those evaluations resulted in `decision = 'SNAP'`. The 12 snapped fragments are:

- 8 fragments from the `ENB-4412` alarm cascade (co-site alarms from sectors 1, 2, 3)
- 3 fragments from neighbouring cells (`ENB-4380`, `ENB-4391`) showing correlated degradation
- 1 change record fragment for ENB-4412 (planned maintenance window 6 hours after the alarm)

The 12 snapped fragments then participated in further snap evaluations. Expanding to downstream decisions yields an additional 214 pairs involving those 12 fragments. Total affected decision set: 38 + 214 = 252 pairs. This is well within `max_pairs_per_candidate = 5,000`.

### 9.3 Replay Results

The simulation re-scores the 214 downstream pairs (excluding the 38 pairs that directly involved `F_c`, which are by definition undefined in the counterfactual world).

**Results summary:**

| Metric | Value |
|---|---|
| Replayed pairs | 214 |
| Causal impact score (mean |delta|) | 0.187 |
| Decision flip count | 7 |
| Decision flip rate | 3.3% |
| Mean delta for DARK_NODE profile | 0.231 |
| Mean delta for DARK_EDGE profile | 0.042 |

**Interpretation**: `F_c` had a moderate-to-high causal impact (`0.187`) on downstream snap scores, concentrated in the `DARK_NODE` profile (`0.231`) with minimal impact on `DARK_EDGE` pairs (`0.042`). 7 snap decisions would have resolved as `NEAR_MISS` rather than `SNAP` had `F_c` not been present.

### 9.4 Top Impacted Pairs (excerpt)

| Fragment A | Fragment B | Baseline Score | Counterfactual Score | Delta | Flipped |
|---|---|---|---|---|---|
| Sector-1 alarm (ENB-4412) | ENB-4380 degradation | 0.823 | 0.591 | -0.232 | YES (SNAP -> NEAR_MISS) |
| Sector-2 alarm (ENB-4412) | ENB-4391 degradation | 0.791 | 0.614 | -0.177 | NO (both SNAP) |
| Sector-3 alarm (ENB-4412) | Change record | 0.756 | 0.631 | -0.125 | NO (both SNAP) |
| ENB-4380 degradation | ENB-4391 degradation | 0.684 | 0.673 | -0.011 | NO (negligible) |

**Finding**: The ENB-4412 Major alarm was genuinely load-bearing for the cross-site snap between Sector-1 and ENB-4380. That snap would not have occurred without `F_c` as an intermediary. The ENB-4380/ENB-4391 pair, however, had near-zero delta — these two sites were snapping to each other independently, regardless of `F_c`.

### 9.5 Feedback to Weight Calibration

The simulation records `mean_delta_by_profile = {"DARK_NODE": 0.231, "DARK_EDGE": 0.042}`. This result is consumed by the T1.4 weight calibration mechanism (Section 6.4) as evidence that:

- Entity overlap (`w_ent = 0.35` for DARK_NODE profile) is correctly dominant for this failure mode: the cross-site snaps were driven by shared entity identifiers (sector identifiers shared between ENB-4412 and its neighbours), which `F_c` amplified.
- The DARK_EDGE profile weights (with `w_ent = 0.30, w_topo = 0.30`) were not the drivers here — the edge-level topology mattered less than the node-level entity overlap.

---

## 10. Integration Points

### 10.1 Snap Engine (T1.4) — Read-Only Consumer

The simulation calls `score_pair_v3(frag_a, frag_b, entities_a, entities_b, profile, temporal_modifier)` in read-only mode. It never writes to `snap_decision_log`. It reads:

- `abeyance_fragment` — for embeddings and masks
- `fragment_entity_ref` — for entity sets (Jaccard input)
- `snap_decision_log` — for baseline decisions and weight profiles used

The temporal modifier is recomputed using `F_a.event_timestamp` and `F_b.event_timestamp` (original event times, not current time), ensuring the counterfactual score is temporally consistent with the baseline.

### 10.2 Temporal Sequence Model (D2.1) — Indirect Input

The simulation does not query `entity_sequence_log` or `transition_matrix` directly. However:

- Tier 3 mechanisms use the transition matrix (D2.1) to identify which fragments are anomalous (expectation violations, rare transitions). These are the primary source of candidates enqueued in `counterfactual_candidate_queue`.
- The `state_key` from the sequence log is not an input to the simulation — the simulation operates at the snap scoring layer, not the sequence layer.

### 10.3 Tier 3 Hypothesis Generation — Downstream Consumer

Tier 3 reads `counterfactual_simulation_result` to:

- Prune hypotheses: if `causal_impact_score < 0.05` for a candidate, the candidate is not a meaningful causal driver and the hypothesis is deprioritized.
- Prioritize investigations: candidates with `decision_flip_rate > 0.10` are flagged for operator review (they are load-bearing evidence for multiple snap clusters).
- Feed weight calibration: `mean_delta_by_profile` is forwarded to the T1.4 calibration pipeline as labeled evidence.

---

## 11. Invariants

| ID | Statement | Enforcement |
|---|---|---|
| INV-CF-1 | No production table is modified during simulation. `abeyance_fragment`, `snap_decision_log`, `entity_sequence_log`, `transition_matrix` are read-only. | Simulation code path uses read-only database sessions; batch job connection has no UPDATE/DELETE grants on production tables |
| INV-CF-2 | Replay window is always forward from `F_c.event_timestamp`. `T_start = F_c.event_timestamp`, `T_end > T_start`. | Enforced at queue entry creation time |
| INV-CF-3 | `replayed_pair_count <= max_pairs_per_candidate`. | Hard truncation applied before Phase 3 |
| INV-CF-4 | Baseline score read from `snap_decision_log` equals what `score_pair_v3` would produce for the same inputs (determinism). | T1.4 INV determinism guarantee; scores stored at 6 decimal places in `snap_decision_log` |
| INV-CF-5 | `causal_impact_score`, `causal_impact_positive`, `causal_impact_negative` all in `[0.0, 1.0]`. | Each delta is the difference of two `[0.0, 1.0]` scores; mean of bounded values is bounded. |
| INV-CF-6 | Every `counterfactual_pair_delta` row traces to exactly one `counterfactual_simulation_result`. | FK constraint + cascade delete on result row |
| INV-CF-7 | Batch job processes candidates from `counterfactual_candidate_queue` atomically (SELECT FOR UPDATE SKIP LOCKED). No candidate is processed by two concurrent job instances. | PostgreSQL row-level locking |
| INV-CF-8 | Job duration is bounded to `4 hours`. Duration budget enforced by wall-clock check between candidates. | Implementation check in Phase 2 loop; no check within a single candidate's scoring (a single candidate is always << 4 hours) |

---

## 12. Configuration Reference

| Parameter | Default | Description |
|---|---|---|
| `max_replay_fragments` | 500 | Maximum distinct fragments in affected decision set before SCOPE_EXCEEDED |
| `max_replay_window_days` | 14 | Days forward from `F_c.event_timestamp` for replay window |
| `max_pairs_per_candidate` | 5,000 | Maximum pairs re-scored per candidate (truncation applied if exceeded) |
| `max_candidates_per_batch` | 200 | Maximum candidates per job invocation |
| `min_meaningful_delta` | 0.05 | Threshold for "non-negligible" delta in per-pair classification |
| `simulation_retention_days` | 180 | Days to retain `counterfactual_pair_delta` rows (parent results kept indefinitely) |
| `max_queue_age_days` | 30 | PENDING queue entries older than this are cancelled on queue maintenance |
| `job_duration_budget_hours` | 4 | Wall-clock budget before job aborts and commits partial results |
| `cron_schedule` | `0 2 * * 0` | Default maintenance window cron (Sundays 02:00 local time) |

---

Generated: 2026-03-16 | Task D4.1 | Abeyance Memory v3.0 | Discovery Mechanism #12 | Tier 4
