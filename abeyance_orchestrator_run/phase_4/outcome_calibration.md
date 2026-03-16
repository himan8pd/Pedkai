# Outcome-Linked Scoring Calibration -- Discovery Mechanism #5

**Task**: D2.1 -- Outcome-Linked Scoring Calibration
**Version**: 3.0
**Date**: 2026-03-16
**Status**: Specification
**Tier**: 2 (Feedback Loop -- requires operator action data)
**Remediates**: F-2.4 (SEVERE) -- hand-tuned weight profiles with no empirical validation

---

## 1. Problem Statement

The five weight profiles (`DARK_EDGE`, `DARK_NODE`, `IDENTITY_MUTATION`, `PHANTOM_CI`, `DARK_ATTRIBUTE`) in the snap engine are hand-tuned constants. Finding F-2.4 identifies that these profiles have no empirical validation, no sensitivity analysis, and no documentation of derivation methodology. Section 6.4 of the snap scoring spec (T1.4) sketches a four-phase validation methodology but does not specify the data model, algorithm, storage schema, or operational constraints.

This specification fills that gap. It defines:

1. How operator actions on snap results are captured and classified.
2. How classified outcomes are stored with full provenance.
3. The calibration algorithm that learns optimal weights from outcome data.
4. How calibrated weights are fed back to the snap engine without disrupting live scoring.
5. Cold-start methodology for operating before calibration data exists.

**What this is**: A closed-loop feedback mechanism that connects operator resolution actions to snap engine weight profiles, replacing hand-tuned guesses with empirically validated weights.

**What this is NOT**: It does not modify the snap scoring algorithm (T1.4), the per-dimension similarity functions, or the mask-aware weight redistribution formula. It operates exclusively on the weight profile values that the snap engine consumes.

---

## 2. Architecture Overview

```
+------------------+     +-----------------------+     +--------------------+
| Snap Engine      |---->| snap_decision_record  |---->| Outcome Feedback   |
| (T1.4)           |     | (per-dimension scores |     | (operator actions) |
|                  |     |  weights, decision)   |     |                    |
+------------------+     +-----------------------+     +--------------------+
        ^                                                       |
        |                                                       v
+------------------+     +-----------------------+     +--------------------+
| Weight Profile   |<----| calibration_history   |<----| Calibration Engine |
| Registry         |     | (provenance log)      |     | (logistic regr.)   |
+------------------+     +-----------------------+     +--------------------+
```

Data flow:
1. Snap engine scores fragment pairs, writes `snap_decision_record` with per-dimension scores and base weights.
2. Operator reviews snap results in the NOC UI and takes action (acknowledge, dismiss, escalate, resolve).
3. Operator action is recorded in `snap_outcome_feedback` referencing the `snap_decision_record.id`.
4. Calibration engine periodically reads accumulated feedback, fits a logistic regression per failure mode profile, extracts optimized weights.
5. Optimized weights are written to `calibration_history` (provenance) and published to the weight profile registry.
6. Snap engine reads updated weight profiles on next scoring cycle.

---

## 3. Operator Feedback Model

### 3.1 Operator Actions

When the NOC UI surfaces a snap result (a fragment pair that crossed the snap threshold), the operator takes one of four actions:

| Action | Code | Meaning |
|---|---|---|
| Acknowledge | `ACK` | Operator confirms the snap is a real correlation. The two fragments are part of the same incident or pattern. |
| Dismiss | `DISMISS` | Operator determines the snap is noise. The fragments are unrelated. |
| Escalate | `ESCALATE` | Operator believes the snap is real but requires further investigation. Treated as provisional true positive. |
| Resolve | `RESOLVE` | Operator has resolved the underlying incident. Confirms the snap was correct AND the incident is closed. |

### 3.2 Outcome Classification

Operator actions map to outcome labels used by the calibration algorithm:

| Operator Action | Outcome Label | Calibration Signal |
|---|---|---|
| `ACK` | `TRUE_POSITIVE` | The snap correctly identified a real correlation. Per-dimension scores that produced this composite are "good" signals. |
| `DISMISS` | `FALSE_POSITIVE` | The snap incorrectly fired. Per-dimension scores that produced this composite led to a bad decision. |
| `ESCALATE` | `TRUE_POSITIVE` | Treated as TP for calibration. If later dismissed after escalation review, a correction record overrides this. |
| `RESOLVE` | `TRUE_POSITIVE` | Strongest confirmation signal. |

### 3.3 Missed Snaps (FALSE_NEGATIVE)

A missed snap occurs when the system fails to correlate fragments that an operator later discovers should have been correlated. This is captured differently:

- The operator manually creates a correlation in the NOC UI (linking two fragments the system did not snap).
- The system retrieves the `snap_decision_record` for that fragment pair (if one exists with decision=`NONE` or `AFFINITY`) and creates a feedback record with outcome `FALSE_NEGATIVE`.
- If no `snap_decision_record` exists (the pair was never evaluated), a synthetic record is generated by scoring the pair retroactively and tagging it as `RETROACTIVE_EVAL`.

FALSE_NEGATIVE records are critical for calibration because they represent the failure mode where weights are misconfigured to undervalue the dimensions that would have surfaced the correlation.

### 3.4 Outcome Corrections

An operator may change their mind. For example, an escalated snap may later be dismissed after investigation. The feedback model supports corrections:

- A new `snap_outcome_feedback` row is inserted with `supersedes_id` pointing to the original feedback record.
- The calibration engine uses only the latest non-superseded feedback for each `snap_decision_record_id`.
- Original records are never deleted (append-only, INV-10).

---

## 4. Storage Schema

### 4.1 Table: `snap_outcome_feedback`

| Column Name | Type | Nullable | Default | Constraints | Notes |
|---|---|---|---|---|---|
| id | UUID | NO | uuid4() | PRIMARY KEY | Feedback record ID |
| tenant_id | VARCHAR(100) | NO | - | NOT NULL | Tenant isolation (INV-7) |
| snap_decision_record_id | UUID | NO | - | NOT NULL, FK -> snap_decision_record.id | The snap decision being evaluated |
| operator_action | VARCHAR(20) | NO | - | NOT NULL, CHECK IN ('ACK','DISMISS','ESCALATE','RESOLVE','MANUAL_LINK') | Action taken |
| outcome_label | VARCHAR(20) | NO | - | NOT NULL, CHECK IN ('TRUE_POSITIVE','FALSE_POSITIVE','FALSE_NEGATIVE') | Derived outcome for calibration |
| operator_id | VARCHAR(255) | NO | - | NOT NULL | Operator who provided feedback |
| feedback_timestamp | TIMESTAMP WITH TIME ZONE | NO | now() | NOT NULL, DEFAULT, server_default | When feedback was recorded |
| supersedes_id | UUID | YES | NULL | FK -> snap_outcome_feedback.id | If non-NULL, this record corrects the referenced record |
| notes | TEXT | YES | NULL | - | Free-text operator notes |
| is_retroactive | BOOLEAN | NO | FALSE | NOT NULL, DEFAULT | TRUE if the snap_decision_record was generated retroactively for a missed snap |

**Indexes:**

| Index Name | Columns | Type | Notes |
|---|---|---|---|
| ix_sof_tenant_time | (tenant_id, feedback_timestamp) | BTREE | Partition queries by tenant and time |
| ix_sof_decision_record | (snap_decision_record_id) | BTREE | Lookup feedback for a specific decision |
| ix_sof_outcome | (tenant_id, outcome_label) | BTREE | Filter by outcome for calibration queries |
| uq_sof_no_dup_active | (snap_decision_record_id) WHERE supersedes_id IS NULL | UNIQUE PARTIAL | Ensures at most one active (non-superseded) feedback per decision record |

**CHECK constraints:**

```sql
ALTER TABLE snap_outcome_feedback
  ADD CONSTRAINT chk_sof_action_outcome_coherence
    CHECK (
      (operator_action IN ('ACK','ESCALATE','RESOLVE') AND outcome_label = 'TRUE_POSITIVE')
      OR (operator_action = 'DISMISS' AND outcome_label = 'FALSE_POSITIVE')
      OR (operator_action = 'MANUAL_LINK' AND outcome_label = 'FALSE_NEGATIVE')
    );

ALTER TABLE snap_outcome_feedback
  ADD CONSTRAINT chk_sof_retroactive_manual
    CHECK (
      (is_retroactive = TRUE AND operator_action = 'MANUAL_LINK')
      OR (is_retroactive = FALSE)
    );
```

### 4.2 Table: `calibration_history`

Stores the provenance of every calibration run. Append-only.

| Column Name | Type | Nullable | Default | Constraints | Notes |
|---|---|---|---|---|---|
| id | UUID | NO | uuid4() | PRIMARY KEY | Calibration run ID |
| tenant_id | VARCHAR(100) | NO | - | NOT NULL | Tenant isolation (INV-7) |
| failure_mode_profile | VARCHAR(50) | NO | - | NOT NULL | Which weight profile was calibrated |
| calibration_timestamp | TIMESTAMP WITH TIME ZONE | NO | now() | NOT NULL, DEFAULT, server_default | When calibration ran |
| sample_count_tp | INTEGER | NO | - | NOT NULL | Number of TRUE_POSITIVE samples used |
| sample_count_fp | INTEGER | NO | - | NOT NULL | Number of FALSE_POSITIVE samples used |
| sample_count_fn | INTEGER | NO | - | NOT NULL | Number of FALSE_NEGATIVE samples used |
| total_samples | INTEGER | NO | - | NOT NULL | Total labeled outcomes used |
| weights_before | JSONB | NO | - | NOT NULL | Weight profile before this calibration: {"w_sem": ..., "w_topo": ..., "w_temp": ..., "w_oper": ..., "w_ent": ...} |
| weights_after | JSONB | NO | - | NOT NULL | Optimized weights produced by this calibration |
| weights_delta | JSONB | NO | - | NOT NULL | Per-weight change: {"w_sem": +0.03, ...} |
| model_auc | FLOAT | NO | - | NOT NULL | AUC-ROC of the fitted logistic model on the training data |
| model_coefficients | JSONB | NO | - | NOT NULL | Raw logistic regression coefficients for auditability |
| convergence_status | VARCHAR(20) | NO | - | NOT NULL, CHECK IN ('CONVERGED','MAX_ITER','SINGULAR','SKIPPED') | Optimizer exit status |
| applied | BOOLEAN | NO | FALSE | NOT NULL, DEFAULT | Whether these weights were deployed to the live profile |
| applied_at | TIMESTAMP WITH TIME ZONE | YES | NULL | - | When weights were deployed (NULL if not applied) |
| applied_by | VARCHAR(255) | YES | NULL | - | Operator who approved deployment (NULL for auto-apply) |
| holdback_reason | TEXT | YES | NULL | - | If not applied, why (e.g., "AUC below threshold", "delta exceeds bounds") |

**Indexes:**

| Index Name | Columns | Type |
|---|---|---|
| ix_ch_tenant_profile_time | (tenant_id, failure_mode_profile, calibration_timestamp) | BTREE |
| ix_ch_applied | (tenant_id, failure_mode_profile) WHERE applied = TRUE | BTREE |

### 4.3 Table: `weight_profile_active`

The live weight profile registry. The snap engine reads from this table at scoring time.

| Column Name | Type | Nullable | Default | Constraints | Notes |
|---|---|---|---|---|---|
| id | UUID | NO | uuid4() | PRIMARY KEY | Row ID |
| tenant_id | VARCHAR(100) | NO | - | NOT NULL | Tenant isolation (INV-7) |
| failure_mode_profile | VARCHAR(50) | NO | - | NOT NULL | Profile name |
| w_sem | FLOAT | NO | - | NOT NULL, CHECK > 0.0 | Semantic weight |
| w_topo | FLOAT | NO | - | NOT NULL, CHECK > 0.0 | Topological weight |
| w_temp | FLOAT | NO | - | NOT NULL, CHECK > 0.0 | Temporal weight |
| w_oper | FLOAT | NO | - | NOT NULL, CHECK > 0.0 | Operational weight |
| w_ent | FLOAT | NO | - | NOT NULL, CHECK > 0.0 | Entity overlap weight |
| calibration_status | VARCHAR(30) | NO | 'INITIAL_ESTIMATE' | NOT NULL, DEFAULT | 'INITIAL_ESTIMATE' or 'EMPIRICALLY_VALIDATED' |
| calibration_run_id | UUID | YES | NULL | FK -> calibration_history.id | NULL for initial estimates; references the calibration run that produced these weights |
| effective_from | TIMESTAMP WITH TIME ZONE | NO | now() | NOT NULL, DEFAULT, server_default | When this profile became active |
| created_at | TIMESTAMP WITH TIME ZONE | NO | now() | NOT NULL, DEFAULT, server_default | Row creation time |

**Unique constraint:**

```sql
ALTER TABLE weight_profile_active
  ADD CONSTRAINT uq_wpa_tenant_profile
    UNIQUE (tenant_id, failure_mode_profile);
```

**CHECK constraints:**

```sql
ALTER TABLE weight_profile_active
  ADD CONSTRAINT chk_wpa_weights_positive
    CHECK (w_sem > 0.0 AND w_topo > 0.0 AND w_temp > 0.0 AND w_oper > 0.0 AND w_ent > 0.0);

ALTER TABLE weight_profile_active
  ADD CONSTRAINT chk_wpa_weights_sum_to_one
    CHECK (abs((w_sem + w_topo + w_temp + w_oper + w_ent) - 1.0) < 1e-6);

ALTER TABLE weight_profile_active
  ADD CONSTRAINT chk_wpa_weights_minimum
    CHECK (w_sem >= 0.05 AND w_topo >= 0.05 AND w_temp >= 0.05 AND w_oper >= 0.05 AND w_ent >= 0.05);
```

---

## 5. Calibration Algorithm

### 5.1 Objective

Given a labeled dataset of `(per-dimension scores, outcome_label)` pairs for a specific `(tenant_id, failure_mode_profile)`, find weight values that maximize the separation between TRUE_POSITIVE and FALSE_POSITIVE composite scores.

Formally: maximize the AUC-ROC of the composite score as a predictor of `outcome_label IN ('TRUE_POSITIVE')` vs `outcome_label = 'FALSE_POSITIVE'`.

### 5.2 Method: Constrained Logistic Regression

**Why logistic regression, not Bayesian optimization or grid search:**

1. Grid search over the 4-simplex (5 weights summing to 1.0) is computationally expensive: with 0.05 step size, there are C(23,4) = 8,855 grid points per calibration run. Feasible but wasteful.
2. Bayesian optimization is powerful but opaque -- the surrogate model makes it harder to interpret why specific weights were chosen.
3. Logistic regression directly models `P(TRUE_POSITIVE | dimension_scores)` and produces interpretable coefficients. The coefficients map directly to optimal weights.

**Algorithm:**

1. Collect all non-superseded feedback records for `(tenant_id, failure_mode_profile)` where the snap decision had all five dimensions available (no masked dimensions). This ensures the training data uses consistent dimensionality.

2. Build the feature matrix `X` where each row is a snap decision and the 5 columns are `[score_semantic, score_topological, score_temporal, score_operational, score_entity_overlap]`.

3. Build the label vector `y` where `y[i] = 1` if outcome is `TRUE_POSITIVE`, `y[i] = 0` if outcome is `FALSE_POSITIVE`.

4. FALSE_NEGATIVE records are included with `y[i] = 1` (they should have been snapped). Their per-dimension scores come from the retroactive evaluation.

5. Fit logistic regression with no intercept (forced through origin):

```
log(P(y=1) / P(y=0)) = beta_sem * S_sem + beta_topo * S_topo + beta_temp * S_temp
                      + beta_oper * S_oper + beta_ent * S_ent
```

No-intercept rationale: The intercept would capture the base rate of true positives, but we want the weights to reflect dimension importance relative to each other, not absolute probability. The snap threshold (separate from weights) controls the decision boundary.

6. Extract raw coefficients `[beta_sem, beta_topo, beta_temp, beta_oper, beta_ent]`.

7. Apply positivity constraint: `beta_d_positive = max(beta_d, 0.05)`. If a coefficient is negative, it means that dimension is anti-predictive of true positives for this profile. This should not happen for well-formed dimensions, but the floor prevents negative weights.

8. Normalize to sum to 1.0:

```
w_d_calibrated = beta_d_positive / SUM(beta_i_positive for all i)
```

9. Apply minimum weight bound:

```
w_d_final = max(w_d_calibrated, 0.05)
```

Re-normalize after applying minimum bounds so the final weights sum to 1.0.

### 5.3 Handling Masked Dimensions in Training Data

The algorithm in 5.2 uses only fully-available records (all 5 dimensions present). This discards records where one or more dimensions were masked.

**Why discard masked records**: Including records with masked dimensions would create a non-rectangular feature matrix (missing values). Imputation (filling missing scores) would inject artificial signal. The redistribution formula already handles masked dimensions at scoring time; the calibration should learn weights assuming all dimensions are available, and the redistribution formula handles degradation.

**Minimum coverage threshold**: If fewer than 70% of labeled outcomes have all 5 dimensions available, log a warning. This indicates systemic LLM availability issues that are degrading calibration quality.

### 5.4 Minimum Sample Size

| Parameter | Value | Rationale |
|---|---|---|
| Minimum total labeled outcomes | 200 | Below this, logistic regression coefficients are unstable. 200 provides roughly 40 samples per coefficient (5 coefficients). |
| Minimum TRUE_POSITIVE count | 50 | Need sufficient positive examples to learn which dimensions predict real correlations. |
| Minimum FALSE_POSITIVE count | 50 | Need sufficient negative examples to learn which dimensions produce noise. |
| Minimum per-profile count | 200 | Each failure mode profile is calibrated independently. A profile with 200 total but only 10 FP would not meet the per-class minimum. |

If any minimum is not met, calibration is skipped for that `(tenant_id, failure_mode_profile)` and `convergence_status = 'SKIPPED'` is recorded in `calibration_history` with `holdback_reason` explaining which threshold was not met.

### 5.5 Weight Update Bounds

To prevent calibration from producing wild swings in scoring behavior:

| Bound | Value | Rationale |
|---|---|---|
| Per-weight minimum | 0.05 | No dimension is structurally irrelevant. Zero weights break redistribution proportionality. |
| Per-weight maximum | 0.60 | No single dimension should dominate to the point of making the system single-signal. |
| Per-weight max delta per calibration | 0.10 | Prevents abrupt scoring changes. Large deltas are logged for human review. |
| Sum constraint | 1.0 (within 1e-6) | Enforced by normalization. |

**Delta enforcement algorithm:**

```python
def apply_delta_bounds(
    weights_before: dict[str, float],
    weights_proposed: dict[str, float],
    max_delta: float = 0.10,
) -> dict[str, float]:
    """Clamp proposed weights to be within max_delta of current weights."""
    clamped = {}
    for dim in weights_before:
        lo = max(0.05, weights_before[dim] - max_delta)
        hi = min(0.60, weights_before[dim] + max_delta)
        clamped[dim] = max(lo, min(hi, weights_proposed[dim]))

    # Re-normalize to sum to 1.0
    total = sum(clamped.values())
    return {dim: w / total for dim, w in clamped.items()}
```

If delta clamping alters the proposed weights, `calibration_history.holdback_reason` includes `"delta_clamped"` to flag that the optimizer wanted a larger change than was permitted.

### 5.6 AUC Quality Gate

After fitting the logistic model, compute AUC-ROC on the training data (leave-one-out cross-validation for small sample sizes, 5-fold cross-validation for N > 500).

| AUC Range | Action |
|---|---|
| AUC >= 0.70 | Apply calibrated weights automatically (auto-apply mode) or queue for operator review (manual-apply mode). |
| 0.55 <= AUC < 0.70 | Log calibration result but do NOT apply. The model has weak discriminative power; per-dimension scores are not strongly predictive of outcomes. This suggests the problem lies outside weight tuning (e.g., embedding quality, threshold selection). |
| AUC < 0.55 | Log and flag as anomalous. AUC near 0.50 means the model is no better than random. Investigate data quality. |

The `model_auc` field in `calibration_history` records the cross-validated AUC for every calibration run.

---

## 6. Calibration Frequency and Scheduling

### 6.1 Trigger Conditions

Calibration runs are triggered by either condition:

1. **Time-based**: Weekly (configurable). Default: Sunday 02:00 UTC tenant-local.
2. **Volume-based**: When the number of new feedback records since last calibration exceeds 100 for any `(tenant_id, failure_mode_profile)`.

Whichever trigger fires first initiates calibration. Both triggers are checked independently.

### 6.2 Execution Scope

Each calibration run processes one `(tenant_id, failure_mode_profile)` pair. A weekly trigger fires 5 calibration runs per tenant (one per failure mode profile). They execute sequentially within a tenant to avoid contention on the `weight_profile_active` table.

### 6.3 Weight Publication

After calibration:

1. New weights are written to `calibration_history` (always, regardless of whether they are applied).
2. If the AUC quality gate passes AND delta bounds are satisfied:
   a. In **auto-apply mode**: Update `weight_profile_active` row for `(tenant_id, failure_mode_profile)`. Set `calibration_status = 'EMPIRICALLY_VALIDATED'`, `calibration_run_id` to the new run, `effective_from` to `now()`.
   b. In **manual-apply mode**: Leave `weight_profile_active` unchanged. Set `calibration_history.applied = FALSE`, `holdback_reason = 'awaiting_operator_approval'`. Surface in NOC UI for operator review.
3. The snap engine reads from `weight_profile_active` on every scoring call. No cache invalidation protocol is needed because the read is a simple row lookup (one row per profile per tenant). The snap engine always reads the current row.

### 6.4 Deployment Mode Configuration

```python
# Per-tenant configuration in tenant_config table
CALIBRATION_MODE = "auto"   # "auto" or "manual"
CALIBRATION_SCHEDULE = "weekly"  # "weekly" or "volume" or "both"
CALIBRATION_VOLUME_THRESHOLD = 100  # new feedback records before triggering
```

Default: `auto` mode with `both` triggers. Conservative tenants can use `manual` mode where every calibration requires operator sign-off.

---

## 7. Cold Start Methodology

### 7.1 Initial State

Before any operator feedback exists, the system operates with the hand-tuned initial estimates from snap scoring spec Section 6.2:

| Profile | w_sem | w_topo | w_temp | w_oper | w_ent |
|---|---|---|---|---|---|
| DARK_EDGE | 0.15 | 0.30 | 0.10 | 0.15 | 0.30 |
| DARK_NODE | 0.25 | 0.10 | 0.10 | 0.20 | 0.35 |
| IDENTITY_MUTATION | 0.10 | 0.15 | 0.10 | 0.20 | 0.45 |
| PHANTOM_CI | 0.20 | 0.15 | 0.10 | 0.25 | 0.30 |
| DARK_ATTRIBUTE | 0.25 | 0.10 | 0.10 | 0.25 | 0.30 |

These are loaded into `weight_profile_active` at tenant provisioning time with `calibration_status = 'INITIAL_ESTIMATE'` and `calibration_run_id = NULL`.

### 7.2 Derivation Documentation for Initial Estimates

The initial estimates are derived from domain reasoning about telco CMDB/NMS failure modes. The rationale for each profile is documented in snap scoring spec Section 6.2. Summarized:

- **DARK_EDGE**: Topological and entity overlap dominate because the signal is structural (which nodes are connected).
- **DARK_NODE**: Entity overlap is strongest (same unknown entity in multiple contexts). Topology is weak because the node is not yet in the graph.
- **IDENTITY_MUTATION**: Entity overlap is dominant (old and new CI names co-occur in same operational context).
- **PHANTOM_CI**: Operational fingerprint is important (correlated maintenance windows).
- **DARK_ATTRIBUTE**: Semantic and operational are primary signals (description text and change-window correlation).

### 7.3 Cold Start Progression

| Phase | Condition | Behavior |
|---|---|---|
| 1. Blind | 0 feedback records | Use initial estimates. All decisions tagged `calibration_status: INITIAL_ESTIMATE`. |
| 2. Collecting | 1 to 199 feedback records per profile | Use initial estimates. Log sample counts. NOC UI shows progress bar toward calibration activation. |
| 3. First calibration | >= 200 feedback records per profile, with >= 50 TP and >= 50 FP | Run first calibration. If AUC >= 0.70, apply. Otherwise, continue with initial estimates. |
| 4. Steady state | Ongoing feedback | Weekly/volume-triggered calibration. Weights evolve incrementally within delta bounds. |

### 7.4 Cross-Tenant Seeding (Optional)

For new tenants that share similar network topology with an existing tenant, an operator may optionally seed the `weight_profile_active` table with calibrated weights from the source tenant. This is a manual operation:

1. Operator selects source tenant and target tenant in the admin UI.
2. System copies the `weight_profile_active` rows from source to target.
3. Copied weights are tagged `calibration_status: 'CROSS_TENANT_SEED'` and `calibration_run_id = NULL`.
4. The target tenant then collects its own feedback and calibrates independently.

This shortens the cold-start period but is never automatic -- tenant data isolation (INV-7) means calibration data itself is never shared, only the resulting weight values.

---

## 8. Feedback Loop Interface to Snap Engine

### 8.1 Contract

The calibration subsystem interacts with the snap engine through a single interface: the `weight_profile_active` table. The snap engine's `score_pair_v3()` function (T1.4 Section 9) reads the weight profile as:

```python
# Snap engine reads weight profile at scoring time
profile = db.query(WeightProfileActive).filter_by(
    tenant_id=tenant_id,
    failure_mode_profile=failure_mode,
).one()

weight_profile = WeightProfile(
    failure_mode=profile.failure_mode_profile,
    w_sem=profile.w_sem,
    w_topo=profile.w_topo,
    w_temp=profile.w_temp,
    w_oper=profile.w_oper,
    w_ent=profile.w_ent,
)
```

### 8.2 No Hot-Path Dependency

The calibration engine runs asynchronously (scheduled job). It never blocks or participates in the snap scoring hot path. The snap engine reads a single database row (cached in memory with a 60-second TTL to avoid per-pair DB lookups). Weight profile changes propagate to the snap engine within 60 seconds of publication.

### 8.3 Snap Decision Record Augmentation

The snap decision record (T1.4 Section 8) already contains all fields needed by the calibration engine:

- `score_semantic`, `score_topological`, `score_temporal`, `score_operational`, `score_entity_overlap` -- the per-dimension scores that form the calibration feature vector.
- `masks_active` -- which dimensions were available (used to filter training data per Section 5.3).
- `weights_used` -- the actual weights applied (used for provenance and delta computation).
- `failure_mode_profile` -- the partition key for per-profile calibration.
- `decision` -- the snap engine's decision (used to distinguish evaluated pairs from unevaluated ones).

No changes to the snap decision record schema are required.

### 8.4 Calibration Status Tag

The `calibration_status` field on `SnapDecisionRecord` is populated from `weight_profile_active.calibration_status`. This tags every snap decision with whether the weights used were initial estimates or empirically validated. This enables before/after analysis:

```sql
-- Compare snap accuracy before and after calibration
SELECT calibration_status,
       COUNT(*) FILTER (WHERE sof.outcome_label = 'TRUE_POSITIVE') AS tp,
       COUNT(*) FILTER (WHERE sof.outcome_label = 'FALSE_POSITIVE') AS fp,
       COUNT(*) AS total,
       ROUND(COUNT(*) FILTER (WHERE sof.outcome_label = 'TRUE_POSITIVE')::numeric / COUNT(*), 3) AS precision
FROM snap_decision_record sdr
JOIN snap_outcome_feedback sof ON sof.snap_decision_record_id = sdr.id
WHERE sdr.tenant_id = 'telco2'
  AND sdr.failure_mode_profile = 'DARK_EDGE'
  AND sof.supersedes_id IS NULL
GROUP BY calibration_status;
```

---

## 9. Telecom Example: DARK_EDGE Calibration for Telco2

### 9.1 Scenario

Tenant `telco2` operates a national mobile network. Over 8 weeks of operation, the snap engine surfaces DARK_EDGE snaps -- pairs of abeyance fragments that suggest missing connections between known network elements.

### 9.2 Feedback Collection

NOC operators at telco2 review 312 DARK_EDGE snap results over 8 weeks:

| Outcome | Count | Examples |
|---|---|---|
| TRUE_POSITIVE (ACK/RESOLVE) | 187 | Router `gNB-SYD-041` and core switch `CSW-SYD-003` have an undocumented fiber link. Fragments from both appeared in correlated alarm bursts. Operator confirmed the link exists but was missing from CMDB. |
| FALSE_POSITIVE (DISMISS) | 98 | Two fragments from different sites (`MEL-*` and `BNE-*`) snapped on high entity overlap because both mentioned the vendor `Nokia` and the alarm `linkDown`. Operator dismissed: different cities, no real connection. |
| FALSE_NEGATIVE (MANUAL_LINK) | 27 | Operator noticed two fragments about `PE-ADL-007` and `AGG-ADL-002` that should have snapped (same physical ring) but were scored below threshold. Retroactive evaluation confirmed high topological score (0.82) but low entity overlap (0.12) dragged the composite below threshold. |

### 9.3 Calibration Run

With 312 labeled outcomes (187 TP, 98 FP, 27 FN treated as TP), calibration fires.

**Feature matrix (first 3 rows):**

| S_sem | S_topo | S_temp | S_oper | S_ent | y |
|---|---|---|---|---|---|
| 0.71 | 0.89 | 0.45 | 0.62 | 0.78 | 1 (TP) |
| 0.65 | 0.31 | 0.52 | 0.58 | 0.82 | 0 (FP) |
| 0.48 | 0.82 | 0.61 | 0.55 | 0.12 | 1 (FN->TP) |

**Logistic regression coefficients (raw):**

```
beta_sem  = 0.42
beta_topo = 1.87
beta_temp = 0.18
beta_oper = 0.39
beta_ent  = 0.71
```

**Interpretation**: Topological similarity (`beta_topo = 1.87`) is far more predictive of true positives than any other dimension. Entity overlap (`beta_ent = 0.71`) is second. Temporal similarity (`beta_temp = 0.18`) contributes least. This makes domain sense: DARK_EDGE is about missing structural connections, so topological proximity is the strongest signal.

**Normalization to weights:**

```
total = 0.42 + 1.87 + 0.18 + 0.39 + 0.71 = 3.57

w_sem_proposed  = 0.42 / 3.57 = 0.118
w_topo_proposed = 1.87 / 3.57 = 0.524
w_temp_proposed = 0.18 / 3.57 = 0.050
w_oper_proposed = 0.39 / 3.57 = 0.109
w_ent_proposed  = 0.71 / 3.57 = 0.199
```

**Delta check against initial weights:**

| Dimension | Initial | Proposed | Delta | Within 0.10? |
|---|---|---|---|---|
| w_sem | 0.15 | 0.118 | -0.032 | Yes |
| w_topo | 0.30 | 0.524 | +0.224 | NO |
| w_temp | 0.10 | 0.050 | -0.050 | Yes |
| w_oper | 0.15 | 0.109 | -0.041 | Yes |
| w_ent | 0.30 | 0.199 | -0.101 | NO |

`w_topo` and `w_ent` exceed the 0.10 delta bound. Delta clamping activates:

```
w_topo_clamped = min(0.60, 0.30 + 0.10) = 0.40
w_ent_clamped  = max(0.05, 0.30 - 0.10) = 0.20
```

After clamping and re-normalization:

```
clamped = {sem: 0.118, topo: 0.40, temp: 0.050, oper: 0.109, ent: 0.20}
total = 0.877
w_sem_final  = 0.118 / 0.877 = 0.135
w_topo_final = 0.400 / 0.877 = 0.456
w_temp_final = 0.050 / 0.877 = 0.057
w_oper_final = 0.109 / 0.877 = 0.124
w_ent_final  = 0.200 / 0.877 = 0.228
                         Sum  = 1.000
```

**Cross-validated AUC: 0.78** (passes the 0.70 quality gate).

### 9.4 Effect on Scoring

With the calibrated DARK_EDGE profile, the missed-snap example from Section 9.2 (PE-ADL-007 / AGG-ADL-002) would now score:

```
Initial weights:  0.15*0.48 + 0.30*0.82 + 0.10*0.61 + 0.15*0.55 + 0.30*0.12 = 0.072 + 0.246 + 0.061 + 0.083 + 0.036 = 0.498
Calibrated weights: 0.135*0.48 + 0.456*0.82 + 0.057*0.61 + 0.124*0.55 + 0.228*0.12 = 0.065 + 0.374 + 0.035 + 0.068 + 0.027 = 0.569
```

The composite score rises from 0.498 to 0.569, a +14% increase. If the snap threshold is 0.55, this fragment pair now crosses the threshold and is correctly surfaced as a snap. The calibration directly resolved the false negative.

### 9.5 Calibration History Record

```json
{
  "id": "calib-run-0042",
  "tenant_id": "telco2",
  "failure_mode_profile": "DARK_EDGE",
  "calibration_timestamp": "2026-05-12T02:00:00Z",
  "sample_count_tp": 214,
  "sample_count_fp": 98,
  "sample_count_fn": 0,
  "total_samples": 312,
  "weights_before": {"w_sem": 0.15, "w_topo": 0.30, "w_temp": 0.10, "w_oper": 0.15, "w_ent": 0.30},
  "weights_after": {"w_sem": 0.135, "w_topo": 0.456, "w_temp": 0.057, "w_oper": 0.124, "w_ent": 0.228},
  "weights_delta": {"w_sem": -0.015, "w_topo": +0.156, "w_temp": -0.043, "w_oper": -0.026, "w_ent": -0.072},
  "model_auc": 0.78,
  "model_coefficients": {"beta_sem": 0.42, "beta_topo": 1.87, "beta_temp": 0.18, "beta_oper": 0.39, "beta_ent": 0.71},
  "convergence_status": "CONVERGED",
  "applied": true,
  "applied_at": "2026-05-12T02:00:15Z",
  "applied_by": null,
  "holdback_reason": "delta_clamped: w_topo +0.224->+0.156, w_ent -0.101->-0.072"
}
```

---

## 10. Sensitivity Analysis (Pre-Calibration Diagnostic)

Before the minimum sample threshold is reached, the system runs a lightweight sensitivity analysis on whatever feedback exists. This is not calibration -- it does not change weights. It produces diagnostic output for operators.

### 10.1 Method

For each dimension `d` in a given `(tenant_id, failure_mode_profile)`:

1. Compute the mean per-dimension score for TRUE_POSITIVE outcomes: `mean_TP_d`.
2. Compute the mean per-dimension score for FALSE_POSITIVE outcomes: `mean_FP_d`.
3. Compute the separation: `delta_d = mean_TP_d - mean_FP_d`.

### 10.2 Interpretation

| delta_d | Meaning |
|---|---|
| > 0.10 | Dimension `d` strongly differentiates TP from FP. Increasing `w_d` would likely improve precision. |
| [-0.05, 0.10] | Dimension `d` has weak discriminative power for this profile. Weight changes will have limited impact. |
| < -0.05 | Dimension `d` is anti-correlated with true positives. This is anomalous and warrants investigation (possible embedding quality issue). |

### 10.3 Output

Sensitivity analysis results are surfaced in the NOC UI as a per-profile dimension importance chart. This gives operators visibility into which dimensions are working before full calibration activates.

---

## 11. Drift Detection

### 11.1 Purpose

After calibration, the learned weights may become stale as the network evolves (new equipment, topology changes, operational pattern shifts). Drift detection monitors whether the calibrated model's predictive power is degrading.

### 11.2 Method

On each calibration run, compare the current AUC against the AUC from the previous calibration:

| AUC Change | Action |
|---|---|
| AUC dropped by < 0.05 | Normal variation. Log and continue. |
| AUC dropped by 0.05 to 0.10 | Warning alert to NOC. Suggest reviewing recent feedback for data quality issues. |
| AUC dropped by > 0.10 | Critical alert. The model has significantly degraded. Consider reverting to previous calibration's weights or to initial estimates. |

### 11.3 Revert Mechanism

If drift is severe, an operator can revert to any previous calibration's weights:

```sql
-- Revert DARK_EDGE profile for telco2 to calibration run from April
UPDATE weight_profile_active
SET w_sem = ch.weights_after->>'w_sem',
    w_topo = ch.weights_after->>'w_topo',
    w_temp = ch.weights_after->>'w_temp',
    w_oper = ch.weights_after->>'w_oper',
    w_ent = ch.weights_after->>'w_ent',
    calibration_run_id = ch.id,
    effective_from = now()
FROM calibration_history ch
WHERE ch.id = '<target-calibration-run-id>'
  AND weight_profile_active.tenant_id = 'telco2'
  AND weight_profile_active.failure_mode_profile = 'DARK_EDGE';
```

Or revert to initial estimates by setting all weights to the cold-start values and `calibration_status = 'INITIAL_ESTIMATE'`.

---

## 12. Invariants

| ID | Statement | Enforcement |
|---|---|---|
| INV-7 | Tenant isolation on all tables | `tenant_id` column on `snap_outcome_feedback`, `calibration_history`, `weight_profile_active` |
| INV-10 | Feedback and calibration history are append-only | No UPDATE or DELETE on `snap_outcome_feedback` or `calibration_history`. Corrections via `supersedes_id`. |
| INV-CAL-1 | All weights strictly positive and >= 0.05 | CHECK constraint on `weight_profile_active`; enforced in calibration algorithm before publication |
| INV-CAL-2 | Weights sum to 1.0 | CHECK constraint on `weight_profile_active`; normalization in calibration algorithm |
| INV-CAL-3 | Per-calibration weight delta <= 0.10 per dimension | `apply_delta_bounds()` in calibration engine; logged in `calibration_history.holdback_reason` when clamped |
| INV-CAL-4 | Calibration requires minimum 200 labeled outcomes with >= 50 TP and >= 50 FP | Sample size check before fitting; `convergence_status = 'SKIPPED'` when not met |
| INV-CAL-5 | AUC quality gate >= 0.70 for auto-apply | `model_auc` checked after fitting; weights not applied if below threshold |
| INV-CAL-6 | Every calibration run produces a `calibration_history` record | Written regardless of whether weights are applied |
| INV-CAL-7 | No single weight exceeds 0.60 | CHECK constraint on `weight_profile_active`; enforced in `apply_delta_bounds()` |

---

## 13. Implementation Pseudocode

```python
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import cross_val_score


@dataclass
class CalibrationResult:
    run_id: UUID
    tenant_id: str
    failure_mode_profile: str
    sample_count_tp: int
    sample_count_fp: int
    sample_count_fn: int
    total_samples: int
    weights_before: dict[str, float]
    weights_after: dict[str, float]
    weights_delta: dict[str, float]
    model_auc: float
    model_coefficients: dict[str, float]
    convergence_status: str
    applied: bool
    holdback_reason: str | None


DIMENSIONS = ["w_sem", "w_topo", "w_temp", "w_oper", "w_ent"]
SCORE_COLUMNS = [
    "score_semantic", "score_topological", "score_temporal",
    "score_operational", "score_entity_overlap",
]
MIN_TOTAL = 200
MIN_TP = 50
MIN_FP = 50
MIN_WEIGHT = 0.05
MAX_WEIGHT = 0.60
MAX_DELTA = 0.10
MIN_AUC = 0.70


def run_calibration(
    tenant_id: str,
    failure_mode_profile: str,
    db_session,
) -> CalibrationResult:
    """
    Run outcome-linked calibration for one (tenant, profile) pair.
    """

    # --- Step 1: Load current weights ---
    current_profile = db_session.query(WeightProfileActive).filter_by(
        tenant_id=tenant_id,
        failure_mode_profile=failure_mode_profile,
    ).one()

    weights_before = {
        "w_sem": current_profile.w_sem,
        "w_topo": current_profile.w_topo,
        "w_temp": current_profile.w_temp,
        "w_oper": current_profile.w_oper,
        "w_ent": current_profile.w_ent,
    }

    # --- Step 2: Load labeled outcomes ---
    # Only non-superseded feedback, only fully-available dimensions
    rows = db_session.execute("""
        SELECT sdr.score_semantic, sdr.score_topological, sdr.score_temporal,
               sdr.score_operational, sdr.score_entity_overlap,
               sof.outcome_label
        FROM snap_decision_record sdr
        JOIN snap_outcome_feedback sof
          ON sof.snap_decision_record_id = sdr.id
        WHERE sdr.tenant_id = :tenant_id
          AND sdr.failure_mode_profile = :profile
          AND sof.supersedes_id IS NULL
          AND sdr.score_semantic IS NOT NULL
          AND sdr.score_topological IS NOT NULL
          AND sdr.score_operational IS NOT NULL
    """, {"tenant_id": tenant_id, "profile": failure_mode_profile}).fetchall()

    # --- Step 3: Check sample size ---
    tp_count = sum(1 for r in rows if r.outcome_label in ('TRUE_POSITIVE',))
    fp_count = sum(1 for r in rows if r.outcome_label == 'FALSE_POSITIVE')
    fn_count = sum(1 for r in rows if r.outcome_label == 'FALSE_NEGATIVE')
    total = len(rows)

    if total < MIN_TOTAL or (tp_count + fn_count) < MIN_TP or fp_count < MIN_FP:
        return CalibrationResult(
            run_id=uuid4(),
            tenant_id=tenant_id,
            failure_mode_profile=failure_mode_profile,
            sample_count_tp=tp_count + fn_count,
            sample_count_fp=fp_count,
            sample_count_fn=fn_count,
            total_samples=total,
            weights_before=weights_before,
            weights_after=weights_before,  # unchanged
            weights_delta={d: 0.0 for d in DIMENSIONS},
            model_auc=0.0,
            model_coefficients={},
            convergence_status="SKIPPED",
            applied=False,
            holdback_reason=f"Insufficient samples: total={total}, tp={tp_count+fn_count}, fp={fp_count}",
        )

    # --- Step 4: Build feature matrix and labels ---
    X = np.array([
        [r.score_semantic, r.score_topological, r.score_temporal,
         r.score_operational, r.score_entity_overlap]
        for r in rows
    ], dtype=np.float64)

    # y=1 for TP and FN (both should have been snapped), y=0 for FP
    y = np.array([
        1 if r.outcome_label in ('TRUE_POSITIVE', 'FALSE_NEGATIVE') else 0
        for r in rows
    ], dtype=np.int32)

    # --- Step 5: Fit logistic regression (no intercept) ---
    model = LogisticRegression(
        fit_intercept=False,
        solver="lbfgs",
        max_iter=1000,
        C=1.0,  # mild regularization
    )
    model.fit(X, y)

    coefficients = model.coef_[0]  # shape (5,)
    coef_dict = {
        "beta_sem": float(coefficients[0]),
        "beta_topo": float(coefficients[1]),
        "beta_temp": float(coefficients[2]),
        "beta_oper": float(coefficients[3]),
        "beta_ent": float(coefficients[4]),
    }

    # --- Step 6: Cross-validated AUC ---
    cv_folds = 5 if total > 500 else min(total, 10)  # LOO-ish for small N
    auc_scores = cross_val_score(model, X, y, scoring="roc_auc", cv=cv_folds)
    model_auc = float(np.mean(auc_scores))

    # --- Step 7: Convert coefficients to weights ---
    betas_positive = np.maximum(coefficients, MIN_WEIGHT)
    beta_total = np.sum(betas_positive)
    weights_proposed = {
        dim: float(betas_positive[i] / beta_total)
        for i, dim in enumerate(DIMENSIONS)
    }

    # --- Step 8: Apply delta bounds ---
    weights_final = apply_delta_bounds(weights_before, weights_proposed, MAX_DELTA)

    # --- Step 9: Compute deltas ---
    weights_delta = {
        dim: round(weights_final[dim] - weights_before[dim], 6)
        for dim in DIMENSIONS
    }

    # --- Step 10: Determine if we should apply ---
    holdback_reasons = []
    if model_auc < MIN_AUC:
        holdback_reasons.append(f"AUC {model_auc:.3f} below threshold {MIN_AUC}")

    any_clamped = any(
        abs(weights_final[d] - weights_proposed[d]) > 1e-6
        for d in DIMENSIONS
    )
    if any_clamped:
        holdback_reasons.append("delta_clamped")

    should_apply = model_auc >= MIN_AUC
    holdback_reason = "; ".join(holdback_reasons) if holdback_reasons else None

    return CalibrationResult(
        run_id=uuid4(),
        tenant_id=tenant_id,
        failure_mode_profile=failure_mode_profile,
        sample_count_tp=tp_count + fn_count,
        sample_count_fp=fp_count,
        sample_count_fn=fn_count,
        total_samples=total,
        weights_before=weights_before,
        weights_after=weights_final,
        weights_delta=weights_delta,
        model_auc=model_auc,
        model_coefficients=coef_dict,
        convergence_status="CONVERGED" if model.n_iter_ < 1000 else "MAX_ITER",
        applied=should_apply,
        holdback_reason=holdback_reason,
    )


def apply_delta_bounds(
    weights_before: dict[str, float],
    weights_proposed: dict[str, float],
    max_delta: float = 0.10,
) -> dict[str, float]:
    """Clamp proposed weights within max_delta of current, enforce floor/ceiling."""
    clamped = {}
    for dim in weights_before:
        lo = max(MIN_WEIGHT, weights_before[dim] - max_delta)
        hi = min(MAX_WEIGHT, weights_before[dim] + max_delta)
        clamped[dim] = max(lo, min(hi, weights_proposed[dim]))

    # Re-normalize to sum to 1.0
    total = sum(clamped.values())
    return {dim: round(w / total, 6) for dim, w in clamped.items()}
```

---

## 14. Dependencies and Interactions

### 14.1 Upstream Dependencies

| Dependency | Source | What This Mechanism Reads |
|---|---|---|
| Snap decision records | T1.4 Snap Scoring | Per-dimension scores, masks_active, weights_used, failure_mode_profile, decision |
| Operator actions | NOC UI | Acknowledge, dismiss, escalate, resolve actions on surfaced snap results |

### 14.2 Downstream Consumers

| Consumer | What It Reads | Effect |
|---|---|---|
| Snap Engine (T1.4) | `weight_profile_active` table | Updated weight profiles change how composite scores are computed for all future snap evaluations |
| Surprise Engine (D1.1) | `calibration_history` table (optional) | Surprise engine may adjust baselines when weights change, to avoid false surprise spikes from calibration events |
| NOC UI | `calibration_history`, sensitivity analysis | Displays calibration status, AUC trends, and dimension importance charts |

### 14.3 Tier 2 Interactions

This mechanism (D2.1) is independent of the other Tier 2 mechanisms:
- **Pattern Conflict (D2.2)**: Operates on cluster structure, not weights. No interaction.
- **Temporal Sequence (D2.3)**: Operates on time-ordered fragment chains. No interaction.

However, Tier 3 mechanisms may consume calibrated weights as input signals for meta-analysis. This is specified in the Tier 3 design, not here.

---

## 15. Acceptance Criteria Traceability

| Criterion | Section |
|---|---|
| 1. Feedback table: snap_decision_record_id -> operator_action -> outcome classification | Section 3 (model), Section 4.1 (schema) |
| 2. Calibration algorithm: logistic regression on per-dimension scores predicting TP outcomes | Section 5 |
| 3. Minimum sample size before calibration activates | Section 5.4 |
| 4. Weight update frequency and bounds | Section 5.5 (bounds), Section 6 (frequency) |
| 5. Feedback loop: calibrated weights fed back to snap engine weight profiles | Section 8 |
| 6. Cold start: methodology for initial weights before calibration data exists | Section 7 |
| 7. Storage schema with tenant isolation | Section 4 (all tables have tenant_id, INV-7) |
| 8. Provenance: calibration history logged | Section 4.2 (calibration_history table) |
| 9. Concrete telecom example | Section 9 |

---

Generated: 2026-03-16 | Task D2.1 | Abeyance Memory v3.0
