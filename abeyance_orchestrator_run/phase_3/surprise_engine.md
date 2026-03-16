# Surprise Metrics Engine -- Discovery Mechanism #1

**Task**: D1.1 -- Surprise Metrics Engine
**Version**: 3.0
**Date**: 2026-03-16
**Status**: Specification
**Tier**: 1 (Foundation -- no LLM dependency)
**Remediates**: F-7.2 (MODERATE) -- silent threshold miscalibration / embedding drift detection

---

## 1. Problem Statement

The snap engine produces `SnapDecisionRecord` entries containing per-dimension scores, composite scores, and snap decisions. Currently, nothing monitors whether these scores are *expected* or *surprising*. Finding F-7.2 identifies that threshold miscalibration or embedding drift produces bad results silently -- the system can flood false positives or zero out false negatives without operator notification.

The surprise metrics engine solves this by maintaining rolling distributional models of snap scores, detecting when an individual score is statistically unlikely given recent history, and escalating surprising events for discovery evaluation.

**What this is**: A statistical anomaly detector operating on the stream of snap decision records. It answers the question: "Given recent scoring history for this failure mode in this tenant, is this score surprising?"

**What this is NOT**: It does not generate hypotheses, invoke an LLM, or modify snap decisions. It is a pure observer that reads snap decision records and emits surprise events.

---

## 2. Conceptual Model

### 2.1 Information-Theoretic Foundation

Surprise is quantified as Shannon self-information:

```
surprise(x) = -log2(P(x))
```

Where `P(x)` is the probability density of observing composite score `x` under the current rolling distribution for a given `(tenant_id, failure_mode_profile)` partition.

Interpretation:
- `surprise = 0 bits`: the score was the single most probable value (P=1, degenerate distribution)
- `surprise = 1 bit`: the score had probability 0.5
- `surprise = 3.32 bits`: the score had probability 0.1
- `surprise = 6.64 bits`: the score had probability 0.01
- `surprise = 10 bits`: the score had probability ~0.001

High surprise means the snap engine produced a score that is rare for this tenant+failure_mode combination. This could indicate:
1. A genuinely novel pattern (discovery opportunity)
2. Embedding drift (operational alert)
3. Threshold miscalibration (calibration alert)
4. Data quality change in upstream telemetry

### 2.2 Partition Key

Distributions are maintained **per (tenant_id, failure_mode_profile)** pair. This is the fundamental unit of surprise estimation.

**Rationale**: Different tenants have different network topologies, alarm profiles, and base rates. Different failure modes produce structurally different score distributions (DARK_EDGE scores cluster differently from IDENTITY_MUTATION scores). Cross-tenant or cross-profile aggregation would conflate structurally different distributions.

---

## 3. Distribution Estimator

### 3.1 Method: Fixed-Width Histogram

The rolling distribution is estimated using a **fixed-width histogram** over the `[0.0, 1.0]` score range.

**Choice rationale -- why histogram over kernel density estimation (KDE)**:
- KDE requires storing all raw samples in the window (memory: O(N) per partition). With 5 failure modes x T tenants, this is 5T windows of raw scores.
- Histogram requires storing only B bin counts (memory: O(B) per partition, B=50 fixed).
- Histogram update is O(1) per sample. KDE query is O(N) per sample.
- The composite score is bounded to `[0.0, 1.0]` and continuous, making fixed-width binning natural.
- Histogram bins can be decremented for window expiry without recomputation.

**Why not exponential moving average**: EMA over a single statistic (mean) cannot estimate probability density at arbitrary score values. EMA over histogram bins is equivalent to a histogram with exponential weighting, which we adopt as the decay mechanism (Section 3.3).

### 3.2 Histogram Parameters

| Parameter | Value | Rationale |
|---|---|---|
| Number of bins (B) | 50 | Bin width = 0.02, sufficient to distinguish score differences of 0.02. Snap thresholds are specified to 2 decimal places, so 0.02 resolution matches threshold granularity. |
| Score range | `[0.0, 1.0]` | Composite score is clamped to this range (INV-3). |
| Bin width | 0.02 | `1.0 / 50 = 0.02` |
| Bin assignment | `bin_index = min(floor(score / 0.02), 49)` | Scores of exactly 1.0 fall into bin 49. |

### 3.3 Decay Mechanism: Exponential Count Decay

Rather than a hard sliding window (which requires tracking individual sample timestamps), the histogram uses **exponential count decay** applied at a fixed frequency.

```
At each decay tick:
    for each bin i in [0..49]:
        count[i] = count[i] * alpha
```

| Parameter | Value | Rationale |
|---|---|---|
| Decay factor (alpha) | 0.995 | Half-life = `ln(2) / ln(1/0.995)` = 138.3 ticks. At 1 tick per snap evaluation batch, this means the effective window is approximately the last 138 evaluations contributing >= 50% weight. |
| Decay tick trigger | Every snap evaluation batch for the partition | A "batch" is all snap evaluations triggered by a single incoming fragment against its candidates. |

**Effective window size**: After 500 ticks, a count has decayed to `0.995^500 = 0.082` -- roughly 8% of original. After 1000 ticks, `0.995^1000 = 0.0067` -- negligible. So the effective observation window is approximately the last 500-1000 snap evaluations per partition.

### 3.4 Probability Density Estimation

Given a score `x`:

```
bin_index = min(floor(x / 0.02), 49)
total_mass = sum(count[i] for i in 0..49)

if total_mass < MINIMUM_MASS:
    return INSUFFICIENT_DATA  # see Section 9

P(x) = count[bin_index] / (total_mass * bin_width)
     = count[bin_index] / (total_mass * 0.02)
```

This produces a probability density (not a probability). The density is used in the surprise computation.

**Normalization check**: `sum(count[i] / (total_mass * 0.02) * 0.02 for i in 0..49) = sum(count[i] / total_mass) = 1.0`. The density integrates to 1.0 over `[0.0, 1.0]`.

---

## 4. Surprise Computation

### 4.1 Core Formula

```
surprise(x) = -log2(P(x) * bin_width)
            = -log2(count[bin_index] / total_mass)
```

**Derivation**: `P(x) * bin_width` gives the probability mass in the bin containing `x`. This is the discrete probability of the bin, which is the appropriate quantity for surprise computation on a histogrammed distribution.

Equivalently: `surprise(x) = log2(total_mass) - log2(count[bin_index])`

### 4.2 Bounded Arithmetic

**Problem**: If `count[bin_index] = 0`, then `P(x) = 0` and `-log2(0)` is undefined (positive infinity).

**Solution**: Apply Laplace smoothing to the bin counts before density estimation:

```
smoothed_count[i] = count[i] + LAPLACE_PSEUDOCOUNT

P_smoothed(x) = smoothed_count[bin_index] / sum(smoothed_count[j] for j in 0..49)
```

| Parameter | Value | Rationale |
|---|---|---|
| `LAPLACE_PSEUDOCOUNT` | 0.01 | Small enough to not distort bins with substantial counts. Total pseudocount across 50 bins = 0.5, which is negligible compared to even a modest `total_mass` of 50+. |

With Laplace smoothing:
- `smoothed_count[i] >= 0.01` for all bins
- `total_smoothed_mass >= 0.5` (from pseudocounts alone)
- `P_smoothed(x) >= 0.01 / total_smoothed_mass > 0`
- `surprise(x)` is always finite

**Upper bound on surprise**: The maximum surprise occurs when `count[bin_index] = 0` (only pseudocount) and `total_smoothed_mass` is large.

```
surprise_max = -log2(0.01 / (total_smoothed_mass))
             = log2(total_smoothed_mass) - log2(0.01)
             = log2(total_smoothed_mass) + 6.64
```

For `total_smoothed_mass = 1000`: `surprise_max = 9.97 + 6.64 = 16.61 bits`.

**Implementation cap**: Surprise is capped at 20 bits as a defense-in-depth bound:

```
surprise = min(-log2(P_smoothed_bin), 20.0)
```

### 4.3 Per-Dimension Surprise (Secondary Signal)

In addition to composite score surprise, the engine computes surprise on each available per-dimension score. These use the same histogram mechanism with separate histograms keyed by `(tenant_id, failure_mode_profile, dimension)`.

Per-dimension surprise is stored but does NOT trigger escalation independently. It serves as diagnostic context when composite surprise triggers. For example: composite surprise is high because the semantic dimension produced an unusually high score while topological was unusually low -- this narrows the discovery investigation.

**Total histograms per partition**: 1 (composite) + 5 (per-dimension) = 6 histograms.
**Memory per histogram**: 50 bins x 8 bytes (float64) = 400 bytes.
**Memory per partition**: 6 x 400 = 2,400 bytes.
**Memory for 10 tenants x 5 profiles**: 10 x 5 x 2,400 = 120,000 bytes = 117 KB.

---

## 5. Surprise Threshold Derivation

### 5.1 Methodology: Empirical Percentile-Based

The surprise threshold is NOT an arbitrary constant. It is derived from the observed surprise distribution itself.

**Approach**: Maintain a second-order histogram -- a histogram of surprise values -- per partition. The threshold is set at a configurable percentile of this distribution.

```
threshold = percentile(surprise_distribution, 1 - alpha)
```

Where `alpha` is the desired escalation rate.

| Parameter | Value | Rationale |
|---|---|---|
| Default alpha | 0.02 (2%) | Target: escalate the most surprising 2% of snap evaluations. This is a practical rate for operator review. |
| Percentile | 98th | `1 - 0.02 = 0.98` |

### 5.2 Surprise Histogram Parameters

The surprise histogram tracks the distribution of computed surprise values:

| Parameter | Value |
|---|---|
| Range | `[0.0, 20.0]` bits (matches surprise cap) |
| Bins | 100 |
| Bin width | 0.2 bits |
| Decay | Same alpha=0.995 as score histograms |

### 5.3 Threshold Computation

```
FUNCTION compute_surprise_threshold(surprise_histogram, alpha=0.02):
    total_mass = sum(surprise_histogram.counts)
    if total_mass < MINIMUM_MASS:
        return DEFAULT_THRESHOLD  # see Section 9

    # Find the bin where cumulative mass exceeds (1 - alpha)
    target_mass = total_mass * (1 - alpha)
    cumulative = 0.0
    for i in 0..99:
        cumulative += surprise_histogram.counts[i]
        if cumulative >= target_mass:
            threshold = (i + 1) * 0.2  # upper edge of the bin
            return threshold

    return 20.0  # cap
```

**Rationale for percentile-based over fixed threshold**:
- Different tenant+profile partitions have structurally different surprise distributions. A fixed threshold of, say, 5 bits would over-trigger for partitions with normally high surprise (sparse data) and under-trigger for partitions with normally low surprise (dense, stable data).
- The percentile approach automatically adapts: it always escalates the top 2% regardless of the partition's base surprise level.
- The escalation rate `alpha` is the single tunable parameter, and it has a direct operational meaning: "what fraction of snap evaluations do I want flagged for review?"

### 5.4 Cold-Start Threshold

When insufficient data exists for percentile estimation (see Section 9), the engine uses a fixed fallback:

| Parameter | Value | Rationale |
|---|---|---|
| `DEFAULT_THRESHOLD` | 6.64 bits | Equivalent to `P(bin) < 0.01`, i.e., the score fell in a bin with less than 1% of total probability mass. Conservative enough to avoid noise, permissive enough to catch genuinely rare scores. |

---

## 6. Trigger and Escalation

### 6.1 Trigger Condition

A snap decision record triggers a surprise event when:

```
composite_surprise >= surprise_threshold(tenant_id, failure_mode_profile)
```

### 6.2 Surprise Event Record

When triggered, the engine emits a `SurpriseEvent`:

```python
@dataclass
class SurpriseEvent:
    # Identity
    event_id: UUID                        # unique event identifier
    tenant_id: str
    timestamp: datetime                   # UTC

    # Source snap decision
    snap_decision_id: UUID                # FK to snap_decision_log
    new_fragment_id: UUID
    candidate_fragment_id: UUID
    failure_mode_profile: str

    # Surprise scores
    composite_surprise: float             # bits, [0.0, 20.0]
    dimension_surprises: dict[str, float] # per-dimension surprise values
    # Example: {"semantic": 4.2, "topological": 8.1, "temporal": 1.3,
    #           "operational": 3.7, "entity_overlap": 2.1}

    # Context
    composite_score: float                # the snap score that was surprising
    dimension_scores: dict[str, Optional[float]]  # per-dimension scores from snap
    threshold_used: float                 # surprise threshold at time of evaluation
    threshold_percentile: float           # e.g. 0.98
    distribution_sample_count: float      # effective total_mass of composite histogram

    # Classification
    escalation_type: str                  # "DISCOVERY" | "DRIFT_ALERT" | "CALIBRATION_ALERT"
```

### 6.3 Escalation Type Classification

The surprise event is classified into one of three types based on heuristic rules applied to the per-dimension surprises:

| Type | Condition | Meaning |
|---|---|---|
| `DISCOVERY` | Composite surprise is high AND at most 2 dimensions have high per-dimension surprise | A specific pattern is unusual. Candidate for discovery evaluation. |
| `DRIFT_ALERT` | 3+ dimensions simultaneously have per-dimension surprise above their respective 95th percentiles | Broad shift across multiple dimensions suggests embedding model drift or upstream data quality change. Operational alert, not discovery. |
| `CALIBRATION_ALERT` | Surprise threshold has decreased monotonically for 5+ consecutive recomputations | The distribution is spreading -- more scores are becoming "surprising" -- which suggests the snap threshold is miscalibrated or the embedding space is degrading. |

"High per-dimension surprise" means the per-dimension surprise exceeds the 95th percentile of its own surprise histogram.

### 6.4 Downstream Consumer

`DISCOVERY` events are placed on a queue consumed by the discovery evaluation coordinator (Tier 2+). The surprise engine does not act on these events itself.

`DRIFT_ALERT` and `CALIBRATION_ALERT` events are emitted as operational metrics (Prometheus gauge/counter) and optionally forwarded to the alerting subsystem. These address F-7.2 directly.

---

## 7. Storage Schema

### 7.1 Surprise Event Table

```sql
CREATE TABLE surprise_event (
    event_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        TEXT NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Source reference
    snap_decision_id UUID NOT NULL,
        -- FK to snap_decision_log(id); not enforced as hard FK
        -- to avoid cross-table locking on high-throughput insert path
    new_fragment_id      UUID NOT NULL,
    candidate_fragment_id UUID NOT NULL,
    failure_mode_profile TEXT NOT NULL,

    -- Surprise values
    composite_surprise   REAL NOT NULL,    -- bits, [0.0, 20.0]
    dimension_surprises  JSONB NOT NULL,   -- per-dimension surprise map

    -- Context snapshot
    composite_score      REAL NOT NULL,    -- the snap score
    dimension_scores     JSONB NOT NULL,   -- per-dimension scores from snap
    threshold_used       REAL NOT NULL,    -- surprise threshold at eval time
    threshold_percentile REAL NOT NULL,    -- e.g. 0.98
    distribution_sample_count REAL NOT NULL,

    -- Classification
    escalation_type      TEXT NOT NULL
        CHECK (escalation_type IN ('DISCOVERY', 'DRIFT_ALERT', 'CALIBRATION_ALERT')),

    -- Discovery lifecycle
    reviewed             BOOLEAN NOT NULL DEFAULT FALSE,
    reviewed_at          TIMESTAMPTZ,
    review_verdict       TEXT
        CHECK (review_verdict IS NULL OR review_verdict IN
               ('TRUE_DISCOVERY', 'FALSE_ALARM', 'KNOWN_PATTERN', 'DEFERRED')),

    CONSTRAINT chk_surprise_range CHECK (composite_surprise >= 0.0 AND composite_surprise <= 20.0),
    CONSTRAINT chk_score_range CHECK (composite_score >= 0.0 AND composite_score <= 1.0)
);

-- Tenant isolation: all queries filter by tenant_id
CREATE INDEX idx_surprise_event_tenant_time
    ON surprise_event (tenant_id, created_at DESC);

-- Discovery queue: unreviewed events by type
CREATE INDEX idx_surprise_event_unreviewed
    ON surprise_event (tenant_id, escalation_type, created_at)
    WHERE reviewed = FALSE;

-- Lookup by source snap decision
CREATE INDEX idx_surprise_event_snap_decision
    ON surprise_event (snap_decision_id);
```

### 7.2 Distribution State Table

The histogram state is persisted to survive restarts. It is NOT queried in the hot path -- it is loaded into memory at startup and written back periodically.

```sql
CREATE TABLE surprise_distribution_state (
    tenant_id              TEXT NOT NULL,
    failure_mode_profile   TEXT NOT NULL,
    dimension              TEXT NOT NULL,
        -- 'composite', 'semantic', 'topological', 'temporal',
        -- 'operational', 'entity_overlap',
        -- 'surprise_composite' (the second-order surprise histogram)
    histogram_bins         REAL[] NOT NULL,     -- array of 50 or 100 float counts
    total_mass             REAL NOT NULL,
    last_updated           TIMESTAMPTZ NOT NULL DEFAULT now(),
    tick_count             BIGINT NOT NULL DEFAULT 0,

    PRIMARY KEY (tenant_id, failure_mode_profile, dimension)
);
```

**Persistence frequency**: Every 100 ticks or every 60 seconds, whichever comes first. Loss of in-memory state between persistence points is acceptable -- the histogram rebuilds from subsequent observations within a few hundred snap evaluations.

### 7.3 Tenant Isolation

All tables include `tenant_id` as a leading column in the primary key or first index column. Queries MUST include `tenant_id` in the WHERE clause. There is no cross-tenant aggregation.

Row-level security (RLS) policies should be applied if the database supports multi-tenant access patterns, but this is an operational concern outside the surprise engine specification.

---

## 8. Algorithm: End-to-End Flow

### 8.1 Per Snap Decision Record

```
FUNCTION evaluate_surprise(record: SnapDecisionRecord):

    partition = (record.tenant_id, record.failure_mode_profile)

    # --- 1. Get or create histograms for this partition ---
    histograms = get_histograms(partition)
    # Returns: {
    #   "composite": Histogram(50 bins, range [0,1]),
    #   "semantic": Histogram(50 bins, range [0,1]),
    #   "topological": Histogram(50 bins, range [0,1]),
    #   "temporal": Histogram(50 bins, range [0,1]),
    #   "operational": Histogram(50 bins, range [0,1]),
    #   "entity_overlap": Histogram(50 bins, range [0,1]),
    #   "surprise_composite": Histogram(100 bins, range [0,20]),
    # }

    # --- 2. Compute composite surprise ---
    composite_hist = histograms["composite"]
    if composite_hist.total_mass < MINIMUM_MASS:
        composite_surprise = None   # insufficient data
    else:
        bin_prob = composite_hist.smoothed_bin_probability(record.final_score)
        composite_surprise = min(-log2(bin_prob), 20.0)

    # --- 3. Compute per-dimension surprises ---
    dim_surprises = {}
    dim_scores = {
        "semantic": record.score_semantic,
        "topological": record.score_topological,
        "temporal": record.score_temporal,
        "operational": record.score_operational,
        "entity_overlap": record.score_entity_overlap,
    }
    for dim, score in dim_scores.items():
        if score is None:
            dim_surprises[dim] = None
            continue
        h = histograms[dim]
        if h.total_mass < MINIMUM_MASS:
            dim_surprises[dim] = None
        else:
            bin_prob = h.smoothed_bin_probability(score)
            dim_surprises[dim] = min(-log2(bin_prob), 20.0)

    # --- 4. Update histograms with current observation ---
    # Apply decay THEN add new observation
    composite_hist.decay(alpha=0.995)
    composite_hist.add(record.final_score)

    for dim, score in dim_scores.items():
        if score is not None:
            histograms[dim].decay(alpha=0.995)
            histograms[dim].add(score)

    if composite_surprise is not None:
        histograms["surprise_composite"].decay(alpha=0.995)
        histograms["surprise_composite"].add(composite_surprise)

    # --- 5. Threshold check and escalation ---
    if composite_surprise is None:
        return None  # insufficient data, no event

    threshold = compute_surprise_threshold(
        histograms["surprise_composite"], alpha=0.02
    )

    if composite_surprise >= threshold:
        escalation_type = classify_escalation(
            composite_surprise, dim_surprises, histograms
        )
        event = SurpriseEvent(
            tenant_id=record.tenant_id,
            snap_decision_id=record.snap_decision_id,
            new_fragment_id=record.new_fragment_id,
            candidate_fragment_id=record.candidate_fragment_id,
            failure_mode_profile=record.failure_mode_profile,
            composite_surprise=composite_surprise,
            dimension_surprises=dim_surprises,
            composite_score=record.final_score,
            dimension_scores=dim_scores,
            threshold_used=threshold,
            threshold_percentile=0.98,
            distribution_sample_count=composite_hist.total_mass,
            escalation_type=escalation_type,
        )
        persist_surprise_event(event)
        return event

    return None
```

### 8.2 Observation Order: Score-Before-Update

The algorithm computes surprise BEFORE updating the histogram with the current observation. This is critical:

- **Correct**: "How surprising is this score given what I have seen so far?"
- **Incorrect**: "How surprising is this score after I have already incorporated it into my model?"

The latter would dilute the surprise of any single observation, especially in partitions with low traffic.

### 8.3 Decay Order: Decay-Before-Add

Decay is applied before adding the new observation in each tick. This ensures the new observation is added at full weight while older observations are proportionally reduced.

---

## 9. Failure Mode: Insufficient Data

### 9.1 Minimum Mass Threshold

```
MINIMUM_MASS = 30.0
```

**Rationale**: With 50 bins and total_mass < 30, most bins have counts < 1. The histogram is too sparse for reliable density estimation. The threshold of 30 is the statistical convention for minimum sample size for distribution estimation, and here it applies to the effective (decay-weighted) count.

### 9.2 Behavior Under Insufficient Data

When `total_mass < MINIMUM_MASS` for a partition:

1. **Composite surprise**: Not computed. Returns `None`.
2. **No surprise events emitted**: Cannot trigger escalation.
3. **Histogram still updated**: New observations are added and decay continues. The partition will eventually accumulate enough mass.
4. **Operational metric emitted**: A gauge `surprise_engine_insufficient_data{tenant_id, failure_mode_profile}` is set to 1 when any partition is below threshold. This allows operators to see which partitions are not yet producing surprise metrics.

### 9.3 Cold-Start Duration

For a new tenant or failure mode profile, the partition starts with zero mass. At one snap evaluation per incoming fragment, and assuming ~10 snap evaluations per fragment (10 candidates scored per profile), the partition reaches `MINIMUM_MASS = 30` after approximately 3 fragments with snap evaluations in this profile.

In practice, cold-start is short (minutes) for high-traffic tenants and longer (hours to days) for low-traffic tenants or rare failure modes. The insufficient-data gauge provides visibility.

### 9.4 Degenerate Distribution

If all scores in the window fall in the same bin (degenerate distribution), the surprise for any score in that bin is approximately 0 bits, and the surprise for any score outside that bin is high. This is correct behavior: a sudden shift from a stable score to a different score IS surprising.

If the degenerate distribution persists (all scores identical), the surprise histogram also becomes degenerate, and the threshold computation may select an artificially low threshold. The defense is `DEFAULT_THRESHOLD = 6.64 bits`: even if the percentile computation returns a low threshold, the engine never uses a threshold below `DEFAULT_THRESHOLD`.

```
effective_threshold = max(compute_surprise_threshold(...), DEFAULT_THRESHOLD)
```

---

## 10. Concrete Telecom Example

### 10.1 Scenario: Unusual eNB Alarm Pattern Snap Score

**Setup**: Tenant `telco2` processes alarms from an LTE radio access network. The failure mode profile `DARK_EDGE` is used to detect unknown connections between network elements. Over the past week, DARK_EDGE snap scores for `telco2` have clustered around 0.35 +/- 0.08 (most eNB alarm pairs have moderate topological similarity because they share the same RNC parent but differ in semantic and operational content).

**Rolling distribution state**:
- Composite histogram bins around score 0.30-0.42 have high counts (most mass).
- Bins above 0.60 have near-zero counts (very few high-similarity DARK_EDGE snap scores).
- `total_mass = 847.3` (healthy, well past minimum).

**Incoming event**: A new alarm fragment arrives from eNB `eNB-4412` with alarm type `S1_SETUP_FAILURE`. The snap engine scores it against candidate fragment from eNB `eNB-7803` (alarm type `X2_HANDOVER_FAILURE`). These two eNBs are in different tracking areas -- they have never been correlated before.

**Per-dimension scores**:
```
score_semantic:      0.82  (both are RAN signaling failures -- high semantic similarity)
score_topological:   0.12  (different tracking areas, distant in topology)
score_temporal:      0.71  (both occurred during the same maintenance window)
score_operational:   0.78  (same vendor, same software version, same change record)
score_entity_overlap: 0.08 (different eNBs, few shared entities)
```

**Composite score** (DARK_EDGE profile: `w_sem=0.15, w_topo=0.30, w_temp=0.10, w_oper=0.15, w_ent=0.30`):
```
composite = 0.15*0.82 + 0.30*0.12 + 0.10*0.71 + 0.15*0.78 + 0.30*0.08
          = 0.123 + 0.036 + 0.071 + 0.117 + 0.024
          = 0.371
```

After temporal modifier (0.95): `final_score = 0.371 * 0.95 = 0.352`.

**This is NOT a surprising composite score** -- 0.352 falls in the peak of the distribution (bins 0.34-0.36).

**However**, consider the per-dimension surprises:
- `score_semantic = 0.82`: The semantic histogram for DARK_EDGE in this tenant shows most values between 0.20-0.45. Score 0.82 falls in a bin with count 0.3 out of total mass 847. Surprise = `-log2(0.3/847)` = 11.5 bits. **Very surprising.**
- `score_topological = 0.12`: Typical for this profile. Surprise = 1.2 bits. Normal.
- `score_operational = 0.78`: The operational histogram shows most values between 0.30-0.50. Score 0.78 is in a bin with count 1.1. Surprise = `-log2(1.1/847)` = 9.6 bits. **Surprising.**

### 10.2 What Happens

The composite surprise is low (score 0.352 is common), so the event does NOT trigger escalation. But the per-dimension surprises are recorded.

**Now the interesting case**: The next day, three more eNB pairs from different tracking areas produce similar patterns -- high semantic + high operational, low topological + low entity overlap. The composite scores start to rise because the snap engine is accumulating affinity through the accumulation graph. A pair finally produces `final_score = 0.68`.

**Surprise computation** for `final_score = 0.68`:
- Bin 34 (range 0.68-0.70) has count 0.15 (almost all mass is around 0.35).
- `surprise = -log2(0.15 / 847.3)` = 12.5 bits.
- Current threshold (98th percentile of surprise histogram) = 8.3 bits.
- `12.5 >= 8.3` -- **TRIGGERED**.

**Escalation type**: Per-dimension surprises show 2 dimensions (semantic and operational) are highly surprising. This is <= 2 dimensions. Classification: `DISCOVERY`.

**Meaning**: The system has detected that a cross-tracking-area correlation between S1_SETUP_FAILURE and X2_HANDOVER_FAILURE alarms is emerging, driven by a shared vendor software version and maintenance window. This is a genuine discovery -- a latent failure pattern spanning network segments that the topology alone would never connect.

---

## 11. Computational Complexity

### 11.1 Per Snap Decision Record

| Operation | Complexity | Notes |
|---|---|---|
| Histogram lookup (bin index) | O(1) | Floor division |
| Smoothed bin probability | O(B) | Sum over B=50 bins for total mass. Can be cached as running total -- O(1) amortized. |
| Surprise computation | O(1) | Single log2 and division |
| Histogram decay | O(B) | Multiply each bin by alpha. B=50 or B=100. |
| Histogram add | O(1) | Increment one bin |
| Threshold computation | O(B_s) | Linear scan of surprise histogram. B_s=100. |
| Escalation classification | O(D) | Check D=5 dimensions |

**Total per snap decision record**: O(B + B_s + D) = O(50 + 100 + 5) = **O(155)** = **O(1)** (constant-time).

All operations are fixed-size arithmetic on fixed-size arrays. No dynamic allocation, no iteration over data proportional to history length.

### 11.2 Memory

Per partition: 7 histograms x (50 or 100 bins) x 8 bytes = ~3,600 bytes.

For 10 tenants x 5 failure modes = 50 partitions: **180 KB** total.

This is negligible. The engine can operate entirely in-process memory with periodic persistence.

### 11.3 I/O

- **Read**: Zero additional database reads. The engine consumes `SnapDecisionRecord` objects that are already materialized by the snap engine.
- **Write (surprise event)**: One INSERT per triggered event. At 2% escalation rate, this is 1 write per ~50 snap evaluations.
- **Write (persistence)**: One UPSERT per histogram per persistence tick (every 100 evaluations or 60 seconds). At 50 partitions x 7 histograms = 350 UPSERTs per persistence tick. Batched as a single transaction.

---

## 12. Integration Points

### 12.1 Input: Snap Engine

The surprise engine registers as a synchronous post-hook on the snap scoring path:

```python
# In snap engine, after scoring and persisting the SnapDecisionRecord:
def _score_and_record(self, frag_a, frag_b, profile, ...):
    record = score_pair_v3(frag_a, frag_b, ...)
    persist_snap_decision(record)

    # Surprise evaluation -- synchronous, O(1)
    surprise_event = self.surprise_engine.evaluate_surprise(record)
    if surprise_event:
        self.discovery_queue.put(surprise_event)
```

**Why synchronous, not async**: The evaluation is O(1) constant time (~microseconds). Async would add complexity (queue management, backpressure) for no latency benefit. The snap engine already performs O(N_candidates x N_profiles) scoring per fragment; adding O(1) surprise evaluation per record is negligible.

### 12.2 Output: Discovery Queue

`DISCOVERY` events are placed on an in-process queue (or Kafka topic `abeyance.discovery.surprise` for distributed deployments). The consumer is the discovery evaluation coordinator, which is a Tier 2+ component.

The surprise engine does not block on queue consumption. If the queue is full, the event is persisted to the `surprise_event` table (which always happens) and the queue insertion is logged as dropped. The discovery coordinator can recover dropped events by querying unreviewed surprise events from the table.

### 12.3 Output: Operational Metrics

```
# Prometheus metrics emitted by the surprise engine

surprise_engine_events_total{tenant_id, failure_mode_profile, escalation_type}
    # Counter: total surprise events emitted, by type

surprise_engine_composite_surprise{tenant_id, failure_mode_profile}
    # Histogram: distribution of composite surprise values (for meta-monitoring)

surprise_engine_threshold{tenant_id, failure_mode_profile}
    # Gauge: current surprise threshold per partition

surprise_engine_insufficient_data{tenant_id, failure_mode_profile}
    # Gauge: 1 if partition below MINIMUM_MASS, 0 otherwise

surprise_engine_distribution_mass{tenant_id, failure_mode_profile}
    # Gauge: current total_mass of composite histogram per partition
```

### 12.4 Non-Interaction: Snap Decisions

The surprise engine is a pure observer. It does NOT:
- Modify snap scores
- Modify snap decisions (SNAP / NEAR_MISS / AFFINITY / NONE)
- Modify thresholds used by the snap engine
- Block or delay snap processing (beyond the O(1) evaluation overhead)

---

## 13. Provenance: What Is Logged When Surprise Triggers

Every surprise event persisted to `surprise_event` contains full provenance:

1. **Which snap decision**: `snap_decision_id` links to the exact row in `snap_decision_log`, which contains the full per-dimension scores, weights, mask state, and decision.
2. **Which fragments**: `new_fragment_id` and `candidate_fragment_id` identify the specific fragment pair.
3. **Which profile**: `failure_mode_profile` identifies the weight profile used.
4. **The surprise value**: `composite_surprise` and `dimension_surprises` provide the full surprise decomposition.
5. **The threshold**: `threshold_used` records what threshold was active, and `threshold_percentile` records the configuration.
6. **The distribution state**: `distribution_sample_count` records the effective sample size at evaluation time. The full histogram state can be recovered from `surprise_distribution_state` (nearest persistence snapshot).
7. **The classification**: `escalation_type` records why this event was flagged.
8. **Review lifecycle**: `reviewed`, `reviewed_at`, `review_verdict` track operator disposition.

This provenance chain enables:
- **Audit**: "Why was this event flagged?" -- because `composite_surprise = 12.5 bits >= threshold 8.3 bits`, meaning the composite score of 0.68 was in a bin with probability mass of 0.018% for DARK_EDGE scores in this tenant.
- **Feedback loop**: `review_verdict` feeds back into Tier 2 outcome calibration. If operators consistently mark DISCOVERY events as FALSE_ALARM, the escalation rate `alpha` can be decreased.
- **Drift diagnosis**: If DRIFT_ALERT events accumulate for a tenant, the per-dimension surprises in the logged events show which embedding dimension is drifting.

---

## 14. Configuration Parameters Summary

| Parameter | Value | Scope | Tunable |
|---|---|---|---|
| `HISTOGRAM_BINS_SCORE` | 50 | Global | No (architectural) |
| `HISTOGRAM_BINS_SURPRISE` | 100 | Global | No (architectural) |
| `SCORE_BIN_WIDTH` | 0.02 | Derived | No |
| `SURPRISE_BIN_WIDTH` | 0.2 | Derived | No |
| `DECAY_ALPHA` | 0.995 | Global | Yes (per-tenant override possible) |
| `LAPLACE_PSEUDOCOUNT` | 0.01 | Global | No |
| `MINIMUM_MASS` | 30.0 | Global | Yes |
| `SURPRISE_CAP` | 20.0 bits | Global | No |
| `DEFAULT_THRESHOLD` | 6.64 bits | Global | Yes |
| `ESCALATION_ALPHA` | 0.02 | Per-tenant | Yes |
| `PERSISTENCE_TICK_INTERVAL` | 100 | Global | Yes |
| `PERSISTENCE_TIME_INTERVAL` | 60 seconds | Global | Yes |
| `DRIFT_DIMENSION_THRESHOLD_PCTL` | 0.95 | Global | Yes |
| `DRIFT_MIN_DIMENSIONS` | 3 | Global | Yes |
| `CALIBRATION_MONOTONIC_WINDOW` | 5 | Global | Yes |

---

## 15. Invariants

| ID | Statement | Enforcement |
|---|---|---|
| INV-S1 | Surprise value in `[0.0, 20.0]` bits | `min(-log2(...), 20.0)` cap + Laplace smoothing prevents -log2(0) |
| INV-S2 | No surprise computation on insufficient data | `total_mass < MINIMUM_MASS` check returns None |
| INV-S3 | Histogram bin counts non-negative | Decay multiplies by positive alpha; add increments; Laplace adds positive pseudocount |
| INV-S4 | Score-before-update ordering | Surprise computed before histogram update in `evaluate_surprise()` |
| INV-S5 | Tenant isolation in all queries | `tenant_id` in PK of distribution state; leading column in all surprise_event indexes |
| INV-S6 | Effective threshold >= DEFAULT_THRESHOLD | `max(compute_surprise_threshold(...), DEFAULT_THRESHOLD)` |
| INV-S7 | All surprise events persisted | `persist_surprise_event()` called before queue insertion; event survives queue drop |
| INV-S8 | No mutation of snap decisions | Engine reads SnapDecisionRecord; no write path to snap_decision_log |
