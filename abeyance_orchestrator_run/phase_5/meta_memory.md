# Abeyance Memory v3.0 — Meta-Memory Specification

**Task:** T4.2 — Discovery Mechanism #13: Meta-Memory
**Discovery Tier:** TIER 4 — Advanced (requires outcome data from T4.1)
**Generated:** 2026-03-16
**Depends On:**
- T4.1 — Outcome Calibration (`snap_outcome_feedback`, `calibration_history`) — source of outcome data
- T3.1 — Ignorance Mapping (`ignorance_map_entry`, `exploration_directive`) — source of region taxonomy and topological structure
- T1.4 — Snap Scoring (`snap_decision_record`, `weight_profile_active`)

---

## 1. Purpose and Motivation

The snap engine evaluates fragment pairs across the full corpus indiscriminately: every candidate
pair is scored with equal initial effort regardless of whether that region of the corpus has
historically produced confirmed correlations or has consistently yielded noise. Calibration
(T4.1) optimizes *how* snap scoring weights dimensions. Meta-memory addresses a different
question:

> "Where in the fragment corpus should the search engine focus exploration effort — and where
> should it deprioritize, without abandoning entirely?"

Meta-memory is a historical productivity ledger for search areas. It tracks which combinations
of entity type, failure mode, time window, and topological region have yielded confirmed
correlations (TRUE_POSITIVE outcomes) versus noise (FALSE_POSITIVE outcomes) or systematic
misses (FALSE_NEGATIVE outcomes), and uses this history to bias future exploration effort.

**What this is**: A slow-moving prior that shifts snap pair generation and enrichment priority
toward historically productive regions, away from historically fruitless ones, while preserving
minimum exploration in all regions.

**What this is NOT**:
- It is not outcome tracking. Outcome data comes from T4.1 (`snap_outcome_feedback`). Meta-memory
  reads that table; it does not define it.
- It is not snap weight calibration. Calibration (T4.1) adjusts dimension weights within a
  failure mode profile. Meta-memory adjusts exploration *volume allocation* across regions.
- It is not ignorance mapping. Ignorance mapping (T3.1) measures where data is missing.
  Meta-memory measures where data is present but historically unproductive.
- It does not operate when insufficient outcome data exists. See Section 6 for the
  inactive-mode behavior.

---

## 2. Scope Boundaries

| In scope | Out of scope |
|---|---|
| Defining a productivity metric derived from outcome data | Defining outcome data (T4.1 owns this) |
| Tracking productivity across entity types, failure modes, time windows, topological regions | Modifying snap scoring weights (T4.1 owns this) |
| Bias algorithm that shifts exploration effort allocation | Modifying enrichment chain execution (T3.2 owns this) |
| Bias bounds enforcing minimum exploration floor | Snap threshold adjustment |
| Failure mode when outcome data is insufficient | Outcome feedback collection |
| Storage schema and provenance | Real-time alerting |

---

## 3. Productivity Metric

### 3.1 Definition

A search area is "productive" in proportion to the rate at which snap evaluations within it
yield confirmed true correlations, weighted by the confidence of those confirmations.

**Productivity score `P(A)` for search area A:**

```
Let N_TP(A) = count of TRUE_POSITIVE outcomes for snap pairs within area A
Let N_FP(A) = count of FALSE_POSITIVE outcomes for snap pairs within area A
Let N_FN(A) = count of FALSE_NEGATIVE outcomes (missed snaps retroactively confirmed) within A
Let N_total(A) = N_TP(A) + N_FP(A) + N_FN(A)

P(A) = [N_TP(A) + alpha * N_FN(A)] / N_total(A)
```

Where `alpha = 0.5`. Rationale: FALSE_NEGATIVE outcomes confirm that the area contains real
correlations the system failed to surface. They are half-weighted relative to TRUE_POSITIVE
because they represent confirmed misses rather than confirmed correct detections — the area was
productive but the system underperformed. Full weighting would double-count the same underlying
correlation evidence.

**Range:** `P(A)` is in [0.0, 1.0]. A value of 1.0 means every evaluated pair in the area was
either a true positive or a false negative (area is entirely productive). A value of 0.0 means
every pair was a false positive (area is entirely noise).

### 3.2 Why Outcome Data Is Required

`P(A)` requires operator feedback labels (`snap_outcome_feedback.outcome_label`). Without these
labels, the only available signal is snap evaluation volume — how many pairs were evaluated.
Volume is explicitly rejected as a productivity proxy because:

1. High-volume areas produce more snaps simply due to fragment density, not because correlations
   are more real.
2. A high-ignorance area (T3.1) produces few snaps due to masked embeddings, not because it
   lacks real correlations.
3. Volume as proxy would bias exploration toward already-well-covered areas, creating a
   reinforcement loop that ignores sparse-but-real-correlation regions.

See Section 6 for the behavior when outcome data is unavailable: meta-memory is fully inactive
and does not fall back to volume tracking.

### 3.3 Productivity Confidence

Raw `P(A)` is unreliable for small sample sizes. A Laplace-smoothed estimate is used:

```
P_smoothed(A) = [N_TP(A) + alpha * N_FN(A) + beta] / [N_total(A) + 2 * beta]
```

Where `beta = 5` (pseudo-count prior). This pulls estimates toward 0.5 when sample counts are
low, preventing small-sample areas from dominating the bias calculation.

**Minimum viable sample size:** An area with fewer than `MIN_OUTCOME_SAMPLES = 30` labeled
outcomes is classified as `INSUFFICIENT_DATA` and excluded from bias calculation (see Section
6.2). It receives the neutral exploration allocation, not the default minimum floor.

---

## 4. Tracked Dimensions

Meta-memory tracks productivity across four dimensions, forming a key space of search areas.
The dimensions are defined to align with the existing taxonomies in T3.1 and T4.1.

### 4.1 Entity Type

Entity types as defined in T3.1 Section 4.1:
`NETWORK_ELEMENT`, `INTERFACE`, `ALARM_CODE`, `IP_ADDRESS`, `CIRCUIT_ID`, `CUSTOMER_ID`,
`VENDOR_TAG`, `FAILURE_MODE`, plus a synthetic `ANY` aggregate bucket.

A snap pair is assigned to an entity type dimension based on the *union* of entity types
extracted from both fragments. If a pair involves a `NETWORK_ELEMENT` and an `ALARM_CODE`, it
contributes to both entity type buckets.

### 4.2 Failure Mode

The five failure mode profiles from the snap engine (T1.4):
`DARK_EDGE`, `DARK_NODE`, `IDENTITY_MUTATION`, `PHANTOM_CI`, `DARK_ATTRIBUTE`.

A snap pair's failure mode comes from `snap_decision_record.failure_mode_profile`.

### 4.3 Time Window

Productivity is tracked across rolling time windows to capture temporal patterns (e.g., alarm
storms that concentrate real correlations in short windows vs. chronic low-signal periods).

Three window granularities are maintained simultaneously:

| Window Granularity | Bucket Size | Rolling Depth | Purpose |
|---|---|---|---|
| Short | 6 hours | 28 buckets (7 days) | Detect intra-day patterns (shift changes, maintenance windows) |
| Medium | 24 hours | 90 buckets (90 days) | Detect day-of-week patterns, weekly maintenance cycles |
| Long | 7 days | 52 buckets (1 year) | Detect seasonal patterns, long-term structural changes |

A snap pair with `snap_decision_timestamp` in bucket `T` contributes to the productivity score
for that bucket at each granularity.

### 4.4 Topological Region

Topological regions are derived from the network topology graph (the same graph queried by T-VEC
topological embedding). A topological region is defined as a set of network elements within a
configured hop radius of a designated region anchor.

**Region definition:** Regions are pre-computed from the CMDB graph and stored in
`meta_memory_topological_region`. Each region is identified by a `region_id` and a `region_name`
(human-readable label such as `CORE-SYDNEY`, `RAN-MELBOURNE-NORTH`, `TRANSIT-BRISBANE`).

**Fragment-to-region assignment:** A fragment is assigned to a topological region based on the
network elements in its `extracted_entities`. A fragment that mentions elements in multiple
regions contributes to all matching region buckets.

**Fallback:** Fragments without topological entities (mask_topological = FALSE) are assigned to
the synthetic `UNLOCATED` region. The `UNLOCATED` region is always excluded from bias calculation
(it is not a coherent search area) but is tracked for diagnostic purposes.

### 4.5 Search Area Key

A search area is the cross-product of all four dimensions:

```
area_key = (tenant_id, entity_type, failure_mode, time_window_granularity, time_bucket, topological_region_id)
```

Full cross-product tracking would produce an enormous key space. Three levels of aggregation
are maintained:

| Level | Key Components | Purpose |
|---|---|---|
| Fine | entity_type + failure_mode + time_bucket(short) + region_id | Highest resolution; only populated for areas with >= 30 outcomes |
| Medium | entity_type + failure_mode + time_bucket(medium) | Primary operational level; drives day-to-day bias |
| Coarse | failure_mode + time_bucket(long) | Lowest resolution; always populated; backstop when fine/medium are sparse |

The bias algorithm (Section 5) operates on the highest-resolution level that has sufficient
data (`SUFFICIENT_DATA` status), falling back to coarser levels for sparse areas.

---

## 5. Bias Algorithm

### 5.1 Objective

Given historical productivity scores across search areas, compute an exploration allocation
`E(A)` for each area such that:

1. Areas with higher `P(A)` receive more exploration effort (more snap pair candidates generated,
   higher enrichment priority weight).
2. No area receives zero exploration (preservation of minimum floor; see Section 5.4).
3. The total allocation across all areas sums to 1.0 (relative allocation, not absolute volume).
4. The allocation updates slowly to prevent oscillation (see Section 5.3).

### 5.2 Base Allocation Formula

For areas at a given aggregation level with `SUFFICIENT_DATA` status:

```
Step 1 — Raw score: R(A) = P_smoothed(A)

Step 2 — Apply floor and ceiling (Section 5.4):
    R_bounded(A) = max(FLOOR, min(CEILING, R(A)))

Step 3 — Normalize within the set of all areas at this level:
    E_raw(A) = R_bounded(A) / SUM(R_bounded(A') for all A' at this level)

Step 4 — Apply minimum floor allocation (Section 5.4):
    E(A) = max(MIN_ALLOCATION_FLOOR, E_raw(A))

Step 5 — Re-normalize to ensure SUM(E(A)) = 1.0 across all areas:
    E_final(A) = E(A) / SUM(E(A') for all A')
```

### 5.3 Temporal Decay of Historical Evidence

Older outcomes should contribute less to the current productivity estimate than recent outcomes.
The system applies exponential decay to the outcome counts:

```
For each outcome record with timestamp t_outcome, observed at time t_now:
    age_days = (t_now - t_outcome).days
    decay_weight(outcome) = exp(-DECAY_LAMBDA * age_days)

Effective counts:
    N_TP_effective(A) = SUM(decay_weight(o) for o in outcomes where outcome_label = TRUE_POSITIVE)
    N_FP_effective(A) = SUM(decay_weight(o) for o in outcomes where outcome_label = FALSE_POSITIVE)
    N_FN_effective(A) = SUM(decay_weight(o) for o in outcomes where outcome_label = FALSE_NEGATIVE)
    N_total_effective(A) = N_TP_effective(A) + N_FP_effective(A) + N_FN_effective(A)

P_smoothed(A) = [N_TP_effective(A) + alpha * N_FN_effective(A) + beta] /
                [N_total_effective(A) + 2 * beta]
```

**Decay parameter:** `DECAY_LAMBDA = 0.02` per day. This gives a half-life of approximately
35 days (`ln(2) / 0.02 ≈ 34.7`). At 90 days, an outcome retains ~17% of its original weight.
At 180 days, ~3%.

**Rationale for 35-day half-life:** Telecom network topologies change slowly (major topology
changes are planned events), but operational patterns (alarm seasonality, maintenance windows)
can shift over weeks. A 35-day half-life allows the system to track multi-month trends while
remaining responsive to genuine shifts in productivity.

**Minimum effective sample threshold:** After applying decay, if `N_total_effective(A) < 5.0`
(equivalent to fewer than 5 recent outcomes at full weight), the area reverts to
`INSUFFICIENT_DATA` status regardless of historical raw count.

### 5.4 Bias Bounds: Exploration/Exploitation Balance

This is a non-negotiable design constraint. Meta-memory must not completely abandon any
search area. Abandonment would create blind spots where real correlations accumulate invisibly
until they manifest as operational incidents.

**Bounds definitions:**

| Parameter | Value | Meaning |
|---|---|---|
| `MIN_ALLOCATION_FLOOR` | 0.05 / N_areas | Each area receives at minimum 5% of the equal-split allocation. With 20 areas, floor = 0.25% each. |
| `MAX_ALLOCATION_CEILING` | 5.0 / N_areas | No area receives more than 5x the equal-split allocation. With 20 areas, ceiling = 25% each. |
| `MIN_RAW_PRODUCTIVITY_FLOOR` | 0.10 | Minimum productivity score accepted by the bias formula, regardless of how bad the actual P(A) is. |
| `MAX_RAW_PRODUCTIVITY_CEILING` | 0.90 | Maximum productivity score accepted, preventing a single area from monopolizing allocation. |

**Enforcement algorithm:**

```python
N_areas = number of distinct search areas at the operating aggregation level

# Step 1: Bound raw productivity scores before normalization
for area in areas:
    area.R_bounded = max(MIN_RAW_PRODUCTIVITY_FLOOR,
                         min(MAX_RAW_PRODUCTIVITY_CEILING, area.P_smoothed))

# Step 2: Normalize
total_R = sum(area.R_bounded for area in areas)
for area in areas:
    area.E_raw = area.R_bounded / total_R

# Step 3: Apply minimum allocation floor
equal_split = 1.0 / N_areas
min_floor = 0.05 * equal_split
for area in areas:
    area.E_floored = max(min_floor, area.E_raw)

# Step 4: Re-normalize after floor application
total_E = sum(area.E_floored for area in areas)
for area in areas:
    area.E_final = area.E_floored / total_E
```

**Invariant:** `E_final(A) >= min_floor` for every area, and `SUM(E_final(A)) = 1.0`.

The minimum floor ensures that even a chronically low-productivity area (e.g., a region that
has produced 95% false positives historically) still receives 5% of its equal-share allocation.
This is a deliberate design choice: the area may be recovering from a data quality issue, may
have recently had topology changes that make it newly productive, or may contain rare but
important correlation classes that are underrepresented in the historical feedback sample.

### 5.5 Allocation Application

The allocation `E_final(A)` is consumed by two downstream mechanisms:

**1. Snap Pair Generation:** The fragment candidate selection query is weighted by allocation.
When building the candidate pair set for a given new fragment `f`, the neighborhood expansion
draws proportionally from each search area according to `E_final`. Concretely: if area A has
`E_final = 0.30`, then 30% of the candidate pairs returned for `f` are drawn from area A's
fragment population.

**2. Enrichment Priority Weight:** The allocation score is written to the `meta_memory_bias`
table (Section 7.3) and read by Discovery Mechanism #3 (Enrichment Priority Routing) as a
multiplicative boost to enrichment priority. An area with `E_final = 0.30` and an ignorance
score of 0.60 (from T3.1) produces a combined priority score of `0.30 * 0.60 = 0.18`. The
ignorance score drives enrichment need; the allocation score amplifies enrichment effort for
productive areas.

The two consumers read `meta_memory_bias` independently. Neither blocks the other.

---

## 6. Failure Mode: Insufficient Outcome Data

### 6.1 Activation Threshold

Meta-memory requires a minimum corpus of outcome data before it activates. The threshold is
evaluated per tenant:

```
META_MEMORY_ACTIVATION_THRESHOLD:
    - Total labeled outcomes (non-superseded snap_outcome_feedback rows): >= 500
    - At least 3 distinct failure mode profiles with >= 50 labeled outcomes each
    - At least one outcome record less than 14 days old (data is not stale)
```

Until this threshold is met, meta-memory is in `INACTIVE` state.

### 6.2 INACTIVE State Behavior

When meta-memory is `INACTIVE`:

1. The `meta_memory_bias` table contains no rows for that tenant.
2. Snap pair generation proceeds with **uniform allocation**: each search area receives equal
   weight. This is equivalent to the pre-meta-memory behavior.
3. Enrichment priority routing uses only the ignorance score from T3.1 (no allocation boost).
4. The NOC UI displays "Meta-Memory: Inactive — insufficient outcome data
   (N outcomes / 500 required)".
5. **Critically:** the system does NOT substitute volume as a proxy for productivity. Volume
   tracking would silently bias toward dense areas and would not satisfy the activation criteria
   when the threshold is eventually met (it would pollute the historical record). Volume signals
   are never stored in meta-memory tables.

### 6.3 INSUFFICIENT_DATA Areas Within Active State

Once meta-memory is globally active, individual areas may still have `INSUFFICIENT_DATA` status
(fewer than 30 labeled outcomes, or effective N < 5.0 after decay). These areas:

- Are not included in the bias calculation.
- Receive the **neutral allocation**: `1.0 / N_total_areas_active`, where `N_total_areas_active`
  is the count of areas with `SUFFICIENT_DATA` status.
- This neutral allocation is greater than the minimum floor, ensuring that newly-emerging areas
  receive proportional exploration until they accumulate enough data to enter the bias calculation.

### 6.4 Transition from INACTIVE to ACTIVE

When the activation threshold is first crossed:

1. `MetaMemoryJob` runs a full historical backfill: it reads all non-superseded outcome records
   for the tenant and computes productivity scores with full temporal decay applied.
2. Initial bias allocations are written to `meta_memory_bias`.
3. Tenant status transitions from `INACTIVE` to `ACTIVE` in `meta_memory_tenant_state`.
4. A `PROVENANCE` event is written to the discovery ledger:
   `META_MEMORY_ACTIVATED` with the outcome counts and timestamp.

The backfill ensures that the first active allocation is informed by the full accumulated history,
not just the most recent outcomes.

---

## 7. Storage Schema

All tables are tenant-isolated. `tenant_id` is on every table and every index.

### 7.1 Table: `meta_memory_area`

Defines the known search area population. One row per `(tenant_id, area_key)`.

```sql
CREATE TABLE meta_memory_area (
    id                    UUID         NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    tenant_id             VARCHAR(100) NOT NULL,
    area_key              VARCHAR(600) NOT NULL,  -- "{entity_type}::{failure_mode}::{granularity}::{time_bucket_iso}::{region_id}"
    entity_type           VARCHAR(100) NOT NULL,  -- from T3.1 known_entity_types or 'ANY'
    failure_mode          VARCHAR(50)  NOT NULL,  -- from T1.4 weight profiles or 'ANY'
    time_granularity      VARCHAR(10)  NOT NULL,  -- 'SHORT' (6h), 'MEDIUM' (24h), 'LONG' (7d)
    time_bucket_start     TIMESTAMPTZ  NOT NULL,
    time_bucket_end       TIMESTAMPTZ  NOT NULL,
    topological_region_id VARCHAR(100) NOT NULL,  -- FK to meta_memory_topological_region.region_id, or 'UNLOCATED', or 'ALL'
    aggregation_level     VARCHAR(10)  NOT NULL,  -- 'FINE', 'MEDIUM', 'COARSE'
    created_at            TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uq_mma_tenant_key UNIQUE (tenant_id, area_key),
    CONSTRAINT chk_mma_granularity CHECK (time_granularity IN ('SHORT', 'MEDIUM', 'LONG')),
    CONSTRAINT chk_mma_agg_level CHECK (aggregation_level IN ('FINE', 'MEDIUM', 'COARSE'))
);

CREATE INDEX ix_mma_tenant_failure_mode
    ON meta_memory_area (tenant_id, failure_mode);

CREATE INDEX ix_mma_tenant_entity_type
    ON meta_memory_area (tenant_id, entity_type);

CREATE INDEX ix_mma_tenant_region
    ON meta_memory_area (tenant_id, topological_region_id);
```

### 7.2 Table: `meta_memory_productivity`

Productivity scores per area per computation run. Append-only (one row per area per job run).

```sql
CREATE TABLE meta_memory_productivity (
    id                     UUID         NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    tenant_id              VARCHAR(100) NOT NULL,
    area_id                UUID         NOT NULL,  -- FK to meta_memory_area.id
    job_run_id             UUID         NOT NULL,  -- FK to meta_memory_job_run.id
    computed_at            TIMESTAMPTZ  NOT NULL DEFAULT now(),

    -- Raw outcome counts (effective, after temporal decay)
    n_tp_effective         FLOAT        NOT NULL CHECK (n_tp_effective >= 0.0),
    n_fp_effective         FLOAT        NOT NULL CHECK (n_fp_effective >= 0.0),
    n_fn_effective         FLOAT        NOT NULL CHECK (n_fn_effective >= 0.0),
    n_total_effective      FLOAT        NOT NULL CHECK (n_total_effective >= 0.0),

    -- Raw outcome counts (unweighted, for diagnostics)
    n_tp_raw               INTEGER      NOT NULL CHECK (n_tp_raw >= 0),
    n_fp_raw               INTEGER      NOT NULL CHECK (n_fp_raw >= 0),
    n_fn_raw               INTEGER      NOT NULL CHECK (n_fn_raw >= 0),
    n_total_raw            INTEGER      NOT NULL CHECK (n_total_raw >= 0),

    -- Productivity scores
    p_raw                  FLOAT        NOT NULL CHECK (p_raw BETWEEN 0.0 AND 1.0),
    p_smoothed             FLOAT        NOT NULL CHECK (p_smoothed BETWEEN 0.0 AND 1.0),
    data_status            VARCHAR(20)  NOT NULL,  -- 'SUFFICIENT_DATA', 'INSUFFICIENT_DATA'

    -- Parameters used for this computation (for reproducibility)
    decay_lambda_used      FLOAT        NOT NULL,
    alpha_used             FLOAT        NOT NULL,
    beta_used              FLOAT        NOT NULL,

    CONSTRAINT chk_mmp_data_status CHECK (
        data_status IN ('SUFFICIENT_DATA', 'INSUFFICIENT_DATA')
    ),
    CONSTRAINT chk_mmp_n_total_coherence CHECK (
        ABS(n_tp_effective + n_fp_effective + n_fn_effective - n_total_effective) < 0.01
    )
);

CREATE INDEX ix_mmp_tenant_area_time
    ON meta_memory_productivity (tenant_id, area_id, computed_at DESC);

CREATE INDEX ix_mmp_tenant_job
    ON meta_memory_productivity (tenant_id, job_run_id);
```

### 7.3 Table: `meta_memory_bias`

The live bias allocation table. Consumed by snap pair generation and enrichment priority routing.
One row per `(tenant_id, area_id)` — the current allocation. Updated (not appended) on each
job run to maintain a single live view.

```sql
CREATE TABLE meta_memory_bias (
    id                    UUID         NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    tenant_id             VARCHAR(100) NOT NULL,
    area_id               UUID         NOT NULL,  -- FK to meta_memory_area.id
    last_job_run_id       UUID         NOT NULL,  -- FK to meta_memory_job_run.id
    updated_at            TIMESTAMPTZ  NOT NULL DEFAULT now(),

    -- Allocation result
    allocation_raw        FLOAT        NOT NULL CHECK (allocation_raw >= 0.0),
    allocation_floored    FLOAT        NOT NULL CHECK (allocation_floored >= 0.0),
    allocation_final      FLOAT        NOT NULL CHECK (allocation_final >= 0.0),
    p_smoothed_at_update  FLOAT        NOT NULL CHECK (p_smoothed_at_update BETWEEN 0.0 AND 1.0),

    -- Bounds applied
    r_bounded             FLOAT        NOT NULL,  -- p_smoothed after raw floor/ceiling
    n_areas_in_set        INTEGER      NOT NULL,  -- number of areas in the normalization set
    equal_split           FLOAT        NOT NULL,  -- 1.0 / n_areas_in_set
    min_floor_applied     BOOLEAN      NOT NULL DEFAULT FALSE,  -- TRUE if floor was binding

    CONSTRAINT uq_mmb_tenant_area UNIQUE (tenant_id, area_id)
);

CREATE INDEX ix_mmb_tenant_area
    ON meta_memory_bias (tenant_id, area_id);

-- Partial index for consumer queries: only active (non-INACTIVE tenant) rows
CREATE INDEX ix_mmb_tenant_allocation
    ON meta_memory_bias (tenant_id, allocation_final DESC);
```

### 7.4 Table: `meta_memory_topological_region`

Pre-computed topological regions. Populated from the CMDB graph during tenant provisioning and
updated when topology changes.

```sql
CREATE TABLE meta_memory_topological_region (
    region_id             VARCHAR(100) NOT NULL,
    tenant_id             VARCHAR(100) NOT NULL,
    region_name           VARCHAR(255) NOT NULL,  -- human-readable, e.g., 'CORE-SYDNEY'
    anchor_node_ids       TEXT[]       NOT NULL DEFAULT '{}',  -- network element IDs at region center
    hop_radius            INTEGER      NOT NULL DEFAULT 2,      -- hop distance for region membership
    member_node_ids       TEXT[]       NOT NULL DEFAULT '{}',  -- all nodes within hop_radius of anchors
    computed_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
    is_synthetic          BOOLEAN      NOT NULL DEFAULT FALSE,  -- TRUE for 'UNLOCATED' and 'ALL' pseudo-regions
    PRIMARY KEY (tenant_id, region_id)
);

CREATE INDEX ix_mmtr_tenant_region
    ON meta_memory_topological_region (tenant_id, region_id);
```

### 7.5 Table: `meta_memory_tenant_state`

Per-tenant meta-memory activation state and configuration.

```sql
CREATE TABLE meta_memory_tenant_state (
    tenant_id                VARCHAR(100) NOT NULL PRIMARY KEY,
    activation_status        VARCHAR(20)  NOT NULL DEFAULT 'INACTIVE',
    activated_at             TIMESTAMPTZ,           -- NULL until first activation
    last_job_run_id          UUID,                  -- FK to meta_memory_job_run.id
    last_job_run_at          TIMESTAMPTZ,
    total_outcomes_observed  INTEGER      NOT NULL DEFAULT 0,
    activation_threshold     INTEGER      NOT NULL DEFAULT 500,
    decay_lambda             FLOAT        NOT NULL DEFAULT 0.02,
    alpha                    FLOAT        NOT NULL DEFAULT 0.5,
    beta                     FLOAT        NOT NULL DEFAULT 5.0,
    min_area_samples         INTEGER      NOT NULL DEFAULT 30,
    min_area_effective_n     FLOAT        NOT NULL DEFAULT 5.0,
    CONSTRAINT chk_mmts_status CHECK (
        activation_status IN ('INACTIVE', 'ACTIVE', 'BACKFILLING')
    )
);
```

### 7.6 Table: `meta_memory_job_run`

Job provenance. Append-only.

```sql
CREATE TABLE meta_memory_job_run (
    id                    UUID         NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    tenant_id             VARCHAR(100) NOT NULL,
    started_at            TIMESTAMPTZ  NOT NULL DEFAULT now(),
    completed_at          TIMESTAMPTZ,
    status                VARCHAR(20)  NOT NULL DEFAULT 'RUNNING',
    run_type              VARCHAR(20)  NOT NULL,  -- 'INCREMENTAL', 'BACKFILL'
    outcomes_processed    INTEGER      NOT NULL DEFAULT 0,
    areas_scored          INTEGER      NOT NULL DEFAULT 0,
    areas_updated         INTEGER      NOT NULL DEFAULT 0,
    bias_rows_written     INTEGER      NOT NULL DEFAULT 0,
    activation_transition VARCHAR(20),            -- NULL, 'INACTIVE->ACTIVE', 'ACTIVE->ACTIVE'
    error_message         TEXT,
    config_snapshot       JSONB        NOT NULL DEFAULT '{}',
    CONSTRAINT chk_mmjr_status CHECK (
        status IN ('RUNNING', 'COMPLETED', 'ERROR', 'PARTIAL')
    ),
    CONSTRAINT chk_mmjr_run_type CHECK (
        run_type IN ('INCREMENTAL', 'BACKFILL')
    )
);

CREATE INDEX ix_mmjr_tenant_time
    ON meta_memory_job_run (tenant_id, started_at DESC);
```

---

## 8. MetaMemoryJob: Algorithm

The job runs as a scheduled background task. It is not on the snap scoring hot path.

### 8.1 Trigger Conditions

| Trigger | Condition | Run Type |
|---|---|---|
| Time-based | Daily at 03:00 UTC tenant-local (configurable) | INCREMENTAL |
| Volume-based | When new outcome records since last run >= 200 for any tenant | INCREMENTAL |
| Activation | When `total_outcomes_observed` crosses `activation_threshold` for first time | BACKFILL |

### 8.2 INCREMENTAL Run Algorithm

```
For each tenant with activation_status = 'ACTIVE':

    Step 1 — Load outcome data:
        Read all non-superseded snap_outcome_feedback rows for tenant.
        For each row, compute decay_weight = exp(-lambda * age_days).
        Join to snap_decision_record to get failure_mode_profile, timestamp, and
        the entity types from fragment_entity_ref for both fragments in the pair.
        Join to fragment topology assignment to get topological_region_id.

    Step 2 — Assign outcomes to areas:
        For each outcome record O:
            For each (entity_type, failure_mode, granularity, time_bucket, region_id)
            in cross_product_of(O.entity_types, O.failure_mode, granularities,
                                time_buckets(O.timestamp), O.region_ids):
                Accumulate decay_weight into area bucket (tp/fp/fn as appropriate)

    Step 3 — Compute productivity scores:
        For each area A with accumulated data:
            N_total_effective = sum of all accumulated weights
            if N_total_effective < min_area_effective_n:
                area.data_status = 'INSUFFICIENT_DATA'
                continue
            if area.n_total_raw < min_area_samples:
                area.data_status = 'INSUFFICIENT_DATA'
                continue
            p_raw = [N_TP_eff + alpha * N_FN_eff] / N_total_eff
            p_smoothed = [N_TP_eff + alpha * N_FN_eff + beta] / [N_total_eff + 2 * beta]
            area.data_status = 'SUFFICIENT_DATA'
        Write meta_memory_productivity rows for all areas.

    Step 4 — Compute bias allocation:
        Collect all SUFFICIENT_DATA areas.
        Apply bounds (Section 5.4).
        Normalize to sum to 1.0.
        Upsert meta_memory_bias rows (INSERT ON CONFLICT UPDATE).

    Step 5 — Update tenant state:
        Update meta_memory_tenant_state.last_job_run_at, last_job_run_id,
        total_outcomes_observed.

    Step 6 — Write job run record.
```

### 8.3 BACKFILL Run Algorithm

Identical to INCREMENTAL except:
- `run_type = 'BACKFILL'`
- Processes ALL historical outcome records (no cutoff date)
- Sets `activation_transition = 'INACTIVE->ACTIVE'` on the job run record
- Transitions tenant `activation_status = 'ACTIVE'` after successful completion

### 8.4 Complexity

**Step 1:** O(N_outcomes) with indexed joins on `snap_outcome_feedback`, `snap_decision_record`,
and `fragment_entity_ref`.

**Step 2:** O(N_outcomes * E * G * R) where E = entity types per pair (bounded at 8 * 2 = 16),
G = granularities (3), R = regions per pair (bounded at configurable max, default 4). Total
bounded constant factor: 192. For N_outcomes = 10,000 this is ~2M area bucket operations,
which is fast in-memory hash map accumulation.

**Step 4:** O(N_areas) with constant factor for bounds application and normalization.

Total job complexity: O(N_outcomes) with bounded constants. Suitable for daily runs on tenants
with tens of thousands of outcomes.

---

## 9. Concrete Telecom Example: Telco2

### 9.1 Context

Tenant `telco2` operates a national mobile network (same tenant as the T4.1 calibration
example). After 16 weeks of operation, meta-memory has been active for 10 weeks. The system
has accumulated 1,847 labeled outcomes across all failure modes.

### 9.2 Observed Productivity Pattern

The medium-granularity (24h bucket) productivity computation for the most recent job run shows:

| Entity Type | Failure Mode | Topological Region | P_smoothed | Data Status | E_final |
|---|---|---|---|---|---|
| NETWORK_ELEMENT | DARK_EDGE | CORE-SYDNEY | 0.81 | SUFFICIENT | 0.147 |
| NETWORK_ELEMENT | DARK_EDGE | RAN-MELBOURNE-NORTH | 0.74 | SUFFICIENT | 0.134 |
| ALARM_CODE | DARK_EDGE | CORE-SYDNEY | 0.62 | SUFFICIENT | 0.112 |
| NETWORK_ELEMENT | DARK_NODE | CORE-SYDNEY | 0.58 | SUFFICIENT | 0.105 |
| INTERFACE | PHANTOM_CI | TRANSIT-BRISBANE | 0.49 | SUFFICIENT | 0.089 |
| ALARM_CODE | PHANTOM_CI | TRANSIT-BRISBANE | 0.44 | SUFFICIENT | 0.080 |
| VENDOR_TAG | DARK_EDGE | RAN-MELBOURNE-NORTH | 0.21 | SUFFICIENT | 0.038 |
| VENDOR_TAG | DARK_ATTRIBUTE | UNLOCATED | — | INSUFFICIENT | 0.050 (neutral) |
| IP_ADDRESS | IDENTITY_MUTATION | CORE-SYDNEY | 0.17 | SUFFICIENT | 0.031 |
| (other 8 areas) | ... | ... | ... | SUFFICIENT | 0.214 total |

**Interpretation of notable rows:**

- `NETWORK_ELEMENT / DARK_EDGE / CORE-SYDNEY` at P=0.81: The Sydney core network is
  consistently surfacing real dark edges. 81% of snap evaluations in this area were confirmed
  true positives. This likely reflects that the CMDB has chronic underdocumentation of Sydney
  core fiber connections, which keeps producing real missing-link correlations.

- `VENDOR_TAG / DARK_EDGE / RAN-MELBOURNE-NORTH` at P=0.21: Melbourne RAN alarms tagged by
  vendor often co-occur by coincidence (vendor alarms are systemic, not topological). 79% of
  snap pairs here are false positives. The area still receives E_final=0.038, which is above
  the minimum floor of `0.05 / 20_areas = 0.0025`.

- `VENDOR_TAG / DARK_ATTRIBUTE / UNLOCATED` with INSUFFICIENT_DATA: This area has only 18
  labeled outcomes (below the 30 minimum). It receives the neutral allocation of `1/20 = 0.050`
  rather than being driven by the (unreliable) small-sample estimate.

- `IP_ADDRESS / IDENTITY_MUTATION / CORE-SYDNEY` at P=0.17: IP address mutations in the core
  are almost always transient BGP/OSPF churn, not real identity mutations. High FP rate.
  The 5% minimum floor is *not* binding here (E_raw = 0.031 > floor = 0.0025) — the floor
  only binds for areas that would otherwise receive near-zero allocation.

### 9.3 Effect on Snap Pair Generation

When a new abeyance fragment `f` arrives with:
- Entity types: `[NETWORK_ELEMENT, ALARM_CODE]`
- Topological assignment: `CORE-SYDNEY`

The candidate pair generation query draws 14.7% of candidates from the
`NETWORK_ELEMENT / DARK_EDGE / CORE-SYDNEY` area (the highest-allocation area that matches
this fragment's profile). Without meta-memory, this area would receive 5% allocation (uniform
across 20 areas). The result: the highest-productivity area receives ~3x more candidate
exposure, increasing the probability that the new fragment is correctly correlated with its
dark edge partner before it decays.

### 9.4 Activation Timeline

| Week | Total Outcomes | Meta-Memory State | Notes |
|---|---|---|---|
| 0–5 | 0–280 | INACTIVE | Uniform allocation. Outcome data accumulating. |
| 6 | 312 | INACTIVE | 312 outcomes, but only DARK_EDGE profile >= 50. Need 3 profiles. |
| 10 | 514 | BACKFILL → ACTIVE | 514 outcomes, DARK_EDGE (312), DARK_NODE (89), PHANTOM_CI (113). Threshold met. Backfill runs. |
| 11–26 | 514–1847 | ACTIVE | Weekly incremental runs. Allocation evolves as more outcomes accumulate. |

---

## 10. Invariants

| ID | Statement | Enforcement |
|---|---|---|
| INV-7 | Tenant isolation on all tables | `tenant_id` column on all meta_memory_* tables |
| INV-10 | meta_memory_productivity is append-only | No UPDATE or DELETE |
| INV-MM-1 | Allocation sums to 1.0 across all areas for an active tenant | Re-normalization step in bias algorithm (Section 5.4 Step 5) |
| INV-MM-2 | No area allocation below minimum floor | `max(min_floor, allocation_raw)` in bias algorithm; partial index on `meta_memory_bias` for diagnostics |
| INV-MM-3 | Meta-memory is fully inactive when outcome threshold not met | `activation_status = 'INACTIVE'` in `meta_memory_tenant_state`; no rows in `meta_memory_bias` for INACTIVE tenants |
| INV-MM-4 | Volume is never used as a productivity proxy | `meta_memory_productivity` has no column for evaluation count without outcome label; job algorithm only reads from `snap_outcome_feedback` (labeled) not from `snap_decision_record` alone |
| INV-MM-5 | P_smoothed is in [0.0, 1.0] | CHECK constraint on `meta_memory_productivity.p_smoothed` |
| INV-MM-6 | All allocation values are non-negative and sum to 1.0 | CHECK constraints on `meta_memory_bias.allocation_final`; normalization enforced in algorithm |
| INV-MM-7 | UNLOCATED region excluded from bias calculation | Applied in Step 4 of Section 8.2: UNLOCATED areas are scored but excluded from normalization set |

---

## 11. Dependencies and Interactions

### 11.1 Upstream Dependencies

| Dependency | Source | What Meta-Memory Reads |
|---|---|---|
| Labeled snap outcomes | T4.1 `snap_outcome_feedback` | outcome_label, timestamps, snap_decision_record_id |
| Per-dimension snap scores | T1.4 `snap_decision_record` | failure_mode_profile, snap_decision_timestamp |
| Fragment entity types | T1.2 `fragment_entity_ref` | entity types for both fragments in each pair |
| Topological region assignment | CMDB graph + T3.1 region taxonomy | region membership for fragment network elements |
| Ignorance scores (for combined priority) | T3.1 `ignorance_map_entry` | region_ignorance_score per area |

### 11.2 Downstream Consumers

| Consumer | What It Reads | Effect |
|---|---|---|
| Snap pair generation | `meta_memory_bias.allocation_final` | Candidate pair volume allocation per area |
| Enrichment Priority Routing (T3.2) | `meta_memory_bias.allocation_final` combined with T3.1 ignorance score | Multiplicative boost to enrichment priority for productive areas |
| NOC UI | `meta_memory_tenant_state`, `meta_memory_bias` | "Meta-Memory" panel: activation status, top productive areas, allocation visualization |

### 11.3 Non-Interactions

Meta-memory explicitly does NOT feed back into:
- `weight_profile_active` (owned by T4.1 calibration)
- `snap_threshold` values (separate tuning concern)
- `decay_rate` of fragments (T1.2 invariant)
- `ignorance_map_entry` classification (T3.1 is read-only from meta-memory's perspective)
