# Causal Direction Testing -- Discovery Mechanism #10

**Task**: D3.1 -- Causal Direction Testing
**Version**: 1.0
**Date**: 2026-03-16
**Status**: Specification
**Tier**: 3 (Pure statistical algorithm -- no LLM dependency, no embeddings)
**Depends on**: Tier 2 -- `entity_sequence_log` (D2.1 / temporal_sequence.md)
**Does NOT include**: Counterfactual simulation (T5.5), sequence model (T4.3)

---

## 1. Problem Statement

The temporal sequence infrastructure (D2.1) records per-entity, time-ordered state observations in `entity_sequence_log`. The transition matrix tells us P(state_j | state_i) for the same entity -- intra-entity sequential probability.

What the transition matrix does NOT tell us: **whether events on entity A drive events on entity B**. That is a cross-entity question. In telecom networks, this pattern is pervasive: a transport link flap on Router-7 may consistently precede cell outages on the eNBs that hang off it. The causal arrow runs from transport to RAN, not the reverse. Without directional testing, the system treats the two alarms as correlated but unordered.

This specification defines a Granger-style temporal precedence algorithm: if fragments referencing entity A consistently precede fragments referencing entity B by a stable inter-event lag, the pair is flagged as a **directional causal candidate**. The algorithm operates entirely on timestamps and entity references already present in `entity_sequence_log`. It requires no LLM, no embeddings, and no new source data.

**Epistemological bound (explicit)**: Temporal precedence is a necessary but not sufficient condition for causation. A consistently precedes B does not prove A causes B. Common causes, reverse causation, and coincidental co-occurrence all produce the same statistical pattern. All outputs of this mechanism are labelled **causal candidates**, not causal facts. Downstream hypothesis generation (T4.x) and operator review are the appropriate resolution steps.

---

## 2. Definitions

### 2.1 Co-occurrence Event

A **co-occurrence event** for entity pair (A, B) is a pair of sequence log entries `(entry_a, entry_b)` where:

1. Both entries belong to the same `tenant_id`.
2. `entry_a.entity_id` = A's UUID, `entry_b.entity_id` = B's UUID.
3. Both entries fall within a common **co-occurrence window** `W` seconds of each other:
   ```
   |entry_a.event_timestamp - entry_b.event_timestamp| <= W
   ```
4. Both entries have `severity_bucket` in `{CRITICAL, MAJOR, MINOR, WARNING}` -- i.e., non-nominal severity. Nominal-state observations are excluded from co-occurrence detection because they represent steady state, not events.

The **signed lag** for a co-occurrence event is:

```
lag_seconds = entry_b.event_timestamp - entry_a.event_timestamp
```

A positive lag means A precedes B. A negative lag means B precedes A.

### 2.2 Consistent Temporal Ordering

Entity pair (A, B) exhibits **consistent temporal ordering** (A -> B direction) when, across all co-occurrence events for that pair, the signed lags are predominantly positive and cluster around a stable mean. Formally: the fraction of co-occurrence events where `lag_seconds > 0` exceeds the **directional threshold** `delta` (default 0.80).

### 2.3 Causal Candidate

A pair (A, B) is a **causal candidate** when all of the following hold:

1. The co-occurrence event count `n >= N_min` (minimum sample size).
2. The directional fraction `df >= delta` (0.80 default).
3. The lag distribution has low relative spread: coefficient of variation `CV = std_lag / mean_lag <= CV_max` (default 0.50). High CV indicates that the lag is erratic -- temporally preceding but not stably so -- which weakens the directional claim.
4. `mean_lag > 0` (A precedes B on average; the pair is not symmetric).

### 2.4 State-Scoped vs. Entity-Scoped Pairs

The algorithm operates at two levels of granularity:

- **Entity-level pair**: All co-occurrence events between A and B regardless of which states they are in.
- **State-scoped pair**: Co-occurrence events restricted to specific state combinations `(state_key_a, state_key_b)`. E.g., `(DARK_ATTRIBUTE:TELEMETRY_EVENT:WARNING on Router-7, DARK_NODE:ALARM:MAJOR on ENB-4412)`.

The primary candidate record is entity-level. State-scoped breakdown is stored as provenance evidence (Section 6) to give operators actionable context.

---

## 3. Algorithm

### 3.1 High-Level Pseudocode

```
FOR EACH tenant:
  FOR EACH candidate_pair (A, B) in entity_pair_candidates(tenant):
    events = collect_co_occurrence_events(tenant, A, B, window=W)
    IF len(events) < N_min: SKIP  # Insufficient data
    lags = [e.lag_seconds for e in events]
    n = len(lags)
    n_positive = count(l > 0 for l in lags)
    df = n_positive / n
    mean_lag = mean(lags)
    std_lag = std(lags)
    cv = std_lag / abs(mean_lag) if mean_lag != 0 else INF
    confidence = compute_confidence(n, df, cv)
    IF df >= delta AND cv <= CV_max AND mean_lag > 0:
      write causal_candidate_record(A, B, mean_lag, std_lag, n, df, confidence)
      write evidence_fragment_pairs (sample of supporting (entry_a, entry_b))
```

### 3.2 Entity Pair Candidate Generation

Exhaustive enumeration of all entity pairs is quadratic and impractical for tenants with thousands of entities. Candidate pairs are generated using two filters applied before lag computation:

**Filter 1 -- Topological proximity**: Restrict to entity pairs where the entities appear together in the `topological_neighbourhood` JSONB of at least one fragment. This exploits the existing topology snapshot. Entities with no topological relationship are unlikely causal candidates.

```sql
SELECT DISTINCT
    fer1.entity_id AS entity_a,
    fer2.entity_id AS entity_b
FROM fragment_entity_ref fer1
JOIN fragment_entity_ref fer2
    ON fer1.fragment_id = fer2.fragment_id
    AND fer1.tenant_id = fer2.tenant_id
    AND fer1.entity_id < fer2.entity_id  -- Avoid duplicate (A,B)/(B,A)
WHERE fer1.tenant_id = :tenant_id
```

This generates all entity pairs that co-appear in at least one fragment's entity ref list. These are the candidate pairs fed into lag estimation.

**Filter 2 -- Minimum non-nominal observations**: Both A and B must each have at least `N_min` non-nominal observations in `entity_sequence_log` within the analysis window. Entities that are always in NOMINAL state cannot produce meaningful directional signal.

```sql
SELECT entity_id
FROM entity_sequence_log
WHERE tenant_id = :tenant_id
  AND event_timestamp >= :window_start
  AND severity_bucket NOT IN ('CLEAR', 'INFO', 'UNKNOWN')
GROUP BY entity_id
HAVING COUNT(*) >= :n_min
```

### 3.3 Co-occurrence Event Collection

```python
async def collect_co_occurrence_events(
    session: AsyncSession,
    tenant_id: str,
    entity_a: UUID,
    entity_b: UUID,
    window_seconds: int,
    analysis_start: datetime,
    analysis_end: datetime,
) -> list[CoOccurrenceEvent]:
    """
    Find all (entry_a, entry_b) pairs where:
    - entry_a references entity_a (non-nominal severity)
    - entry_b references entity_b (non-nominal severity)
    - |entry_a.event_timestamp - entry_b.event_timestamp| <= window_seconds
    - Both timestamps fall within [analysis_start, analysis_end]

    Returns signed lag for each pair (entry_b.ts - entry_a.ts).
    """
    # Fetch non-nominal observations for both entities in the analysis window
    obs_a = await _get_non_nominal_observations(
        session, tenant_id, entity_a, analysis_start, analysis_end
    )
    obs_b = await _get_non_nominal_observations(
        session, tenant_id, entity_b, analysis_start, analysis_end
    )

    events: list[CoOccurrenceEvent] = []

    # O(|obs_a| * |obs_b|) -- bounded by max_obs_per_entity^2
    # For typical entity observation counts (hundreds per window), this is fast.
    for a in obs_a:
        for b in obs_b:
            lag = (b.event_timestamp - a.event_timestamp).total_seconds()
            if abs(lag) <= window_seconds:
                events.append(CoOccurrenceEvent(
                    entry_a_id=a.id,
                    entry_b_id=b.id,
                    fragment_a_id=a.fragment_id,
                    fragment_b_id=b.fragment_id,
                    ts_a=a.event_timestamp,
                    ts_b=b.event_timestamp,
                    state_key_a=a.state_key,
                    state_key_b=b.state_key,
                    lag_seconds=lag,
                ))

    return events
```

**Bounding observation counts**: To prevent quadratic blowup on high-frequency entities, cap `obs_a` and `obs_b` at `max_obs_per_entity = 5000` observations per analysis window. If an entity exceeds this cap, sample uniformly from its non-nominal observations. This is controlled by the configuration parameter `max_obs_per_entity`.

### 3.4 Lag Distribution Statistics

```python
def compute_lag_statistics(events: list[CoOccurrenceEvent]) -> LagStats:
    lags = [e.lag_seconds for e in events]
    n = len(lags)
    if n == 0:
        return LagStats(n=0, mean=0, std=0, cv=float('inf'), df=0.0)

    n_positive = sum(1 for l in lags if l > 0)
    df = n_positive / n                      # Directional fraction: P(A before B)
    mean_lag = statistics.mean(lags)
    std_lag = statistics.stdev(lags) if n > 1 else 0.0
    cv = (std_lag / abs(mean_lag)) if abs(mean_lag) > 1e-9 else float('inf')

    return LagStats(n=n, mean=mean_lag, std=std_lag, cv=cv, df=df)
```

### 3.5 Confidence Metric

Confidence is a composite score in [0.0, 1.0] combining three factors:

```
confidence = w_sample * sample_factor(n)
           + w_direction * direction_factor(df)
           + w_stability * stability_factor(cv)
```

Where default weights are `w_sample = 0.30`, `w_direction = 0.50`, `w_stability = 0.20`.

**sample_factor(n)**: Saturating function of sample size.
```
sample_factor(n) = min(n, N_saturate) / N_saturate
```
Where `N_saturate = 100`. At n=30 this gives 0.30; at n=100 it saturates to 1.0.

**direction_factor(df)**: Linear scaling of the directional fraction above the minimum threshold.
```
direction_factor(df) = (df - delta) / (1.0 - delta)   for df >= delta
                     = 0.0                              for df < delta
```
With `delta = 0.80`: df=0.80 gives 0.0; df=1.00 gives 1.0.

**stability_factor(cv)**: Decreasing function of coefficient of variation.
```
stability_factor(cv) = max(0.0, 1.0 - cv / CV_max)
```
With `CV_max = 0.50`: cv=0.0 gives 1.0; cv=0.50 gives 0.0.

**Confidence interpretation**:

| Range | Label | Consumer Guidance |
|---|---|---|
| >= 0.75 | `HIGH` | Strong directional candidate. Surface to operator. |
| 0.50 -- 0.74 | `MEDIUM` | Plausible candidate. Include with caveat. |
| 0.25 -- 0.49 | `LOW` | Weak signal. Retain for accumulation; do not surface alone. |
| < 0.25 | `INSUFFICIENT` | Below threshold. Do not write causal candidate record. |

Candidate records with `INSUFFICIENT` confidence are discarded (not written to storage). The minimum confidence threshold for record persistence is 0.25.

---

## 4. Minimum Sample Size

### 4.1 Rationale

Lag estimation from small samples is unreliable. The sample mean and coefficient of variation are both high-variance estimators when n < 10. The directional fraction has binomial variance `p(1-p)/n`; at n=10 and df=0.80, the 95% confidence interval spans roughly 0.55 to 0.94 -- too wide to be useful.

### 4.2 Minimum Sample Threshold

`N_min = 15`

At n=15 and df=0.80, the 95% Wilson score interval for the true directional fraction is approximately [0.56, 0.93]. This is still wide, which is why the confidence metric (Section 3.5) down-weights small samples via `sample_factor`.

`N_min = 15` is the absolute floor below which no candidate record is created, regardless of how consistent the ordering appears. Below this threshold the algorithm emits no output.

### 4.3 Confidence-Adjusting Sample Regions

| n Range | Behaviour |
|---|---|
| < 15 | No record created (`INSUFFICIENT` by construction) |
| 15 -- 29 | Record created only if df >= 0.90 (raised threshold for small n). `sample_factor` caps at 0.29. |
| 30 -- 99 | Standard thresholds apply. Confidence grows with n. |
| >= 100 | `sample_factor` saturates at 1.0. Full confidence range available. |

The raised df threshold for small n (15-29) is implemented as a pre-filter before confidence computation:

```python
effective_delta = 0.90 if n < 30 else delta  # delta = 0.80 default
if df < effective_delta:
    return None  # Skip -- directional signal not strong enough for this sample size
```

---

## 5. Storage Schema

### 5.1 Table: `causal_candidate`

One row per entity pair per analysis run that meets the minimum thresholds.

| Column Name | Type | Nullable | Default | Constraints | Notes |
|---|---|---|---|---|---|
| id | UUID | NO | uuid4() | PRIMARY KEY | Candidate record ID |
| tenant_id | VARCHAR(100) | NO | - | NOT NULL | Tenant isolation (INV-7) |
| entity_a_id | UUID | NO | - | NOT NULL, FK -> shadow_entity.id | Presumed cause entity (precedes B) |
| entity_b_id | UUID | NO | - | NOT NULL, FK -> shadow_entity.id | Presumed effect entity (follows A) |
| entity_a_identifier | VARCHAR(500) | NO | - | NOT NULL | Denormalized from shadow_entity |
| entity_b_identifier | VARCHAR(500) | NO | - | NOT NULL | Denormalized from shadow_entity |
| entity_a_domain | VARCHAR(50) | YES | NULL | - | Domain of entity A (RAN, TRANSPORT, IP, etc.) |
| entity_b_domain | VARCHAR(50) | YES | NULL | - | Domain of entity B |
| mean_lag_seconds | FLOAT | NO | - | NOT NULL | Mean signed lag (entry_b.ts - entry_a.ts). Always > 0 for stored records. |
| std_lag_seconds | FLOAT | NO | - | NOT NULL | Standard deviation of lag distribution |
| sample_size | INTEGER | NO | - | NOT NULL | Number of co-occurrence events used for estimation |
| directional_fraction | FLOAT | NO | - | NOT NULL | Fraction of events where A preceded B (>= delta for stored records) |
| cv | FLOAT | NO | - | NOT NULL | Coefficient of variation (std / mean). Lower = more stable lag. |
| confidence | FLOAT | NO | - | NOT NULL | Composite confidence score [0.0, 1.0] |
| confidence_label | VARCHAR(20) | NO | - | NOT NULL | HIGH / MEDIUM / LOW |
| analysis_window_start | TIMESTAMP WITH TIME ZONE | NO | - | NOT NULL | Left edge of the analysis window |
| analysis_window_end | TIMESTAMP WITH TIME ZONE | NO | - | NOT NULL | Right edge of the analysis window |
| co_occurrence_window_seconds | INTEGER | NO | - | NOT NULL | W parameter used for this run |
| first_observed_co_occurrence | TIMESTAMP WITH TIME ZONE | NO | - | NOT NULL | Timestamp of earliest qualifying co-occurrence event |
| last_observed_co_occurrence | TIMESTAMP WITH TIME ZONE | NO | - | NOT NULL | Timestamp of most recent qualifying co-occurrence event |
| created_at | TIMESTAMP WITH TIME ZONE | NO | now() | NOT NULL, server_default | Record creation time |
| superseded_by | UUID | YES | NULL | FK -> causal_candidate.id | If a newer run for the same pair replaces this record |
| is_current | BOOLEAN | NO | TRUE | NOT NULL, DEFAULT | FALSE when superseded |

**Design decisions**:
- `entity_a` is always the presumed cause (positive mean_lag). The algorithm enforces this by construction: if mean_lag < 0, the pair is stored as (B, A) with negated lag.
- `superseded_by` / `is_current`: On each analysis run, existing records for the same pair are marked `is_current = FALSE` and a new record is inserted. This preserves history for trend analysis while keeping the current state queryable via `WHERE is_current = TRUE`.
- No `CHECK (mean_lag_seconds > 0)` at the DB level because the application enforces direction orientation before writing.

#### 5.1.1 Indexes

| Index Name | Columns | Type | Notes |
|---|---|---|---|
| ix_cc_tenant_current | (tenant_id, is_current, confidence) | BTREE | Primary consumer query: current candidates for a tenant, ordered by confidence |
| ix_cc_entity_a | (tenant_id, entity_a_id, is_current) | BTREE | "What does entity A appear to cause?" |
| ix_cc_entity_b | (tenant_id, entity_b_id, is_current) | BTREE | "What appears to cause entity B?" |
| uq_cc_pair_window | (tenant_id, entity_a_id, entity_b_id, analysis_window_end) | UNIQUE | Prevents duplicate runs for the same pair in the same window |
| ix_cc_domain_pair | (tenant_id, entity_a_domain, entity_b_domain, is_current) | BTREE | Cross-domain candidate queries (e.g., all TRANSPORT -> RAN candidates) |

#### 5.1.2 CHECK Constraints

```sql
ALTER TABLE causal_candidate
  ADD CONSTRAINT chk_cc_sample_positive
    CHECK (sample_size > 0);

ALTER TABLE causal_candidate
  ADD CONSTRAINT chk_cc_df_range
    CHECK (directional_fraction >= 0.0 AND directional_fraction <= 1.0);

ALTER TABLE causal_candidate
  ADD CONSTRAINT chk_cc_confidence_range
    CHECK (confidence >= 0.0 AND confidence <= 1.0);

ALTER TABLE causal_candidate
  ADD CONSTRAINT chk_cc_std_nonnegative
    CHECK (std_lag_seconds >= 0.0);

ALTER TABLE causal_candidate
  ADD CONSTRAINT chk_cc_cv_nonnegative
    CHECK (cv >= 0.0);

ALTER TABLE causal_candidate
  ADD CONSTRAINT chk_cc_entity_distinct
    CHECK (entity_a_id != entity_b_id);
```

---

### 5.2 Table: `causal_evidence_pair`

Provenance table: stores the specific fragment pairs that contributed evidence to each causal candidate. Not all co-occurrence events are stored -- a sample of up to `max_evidence_pairs` (default: 50) is retained per candidate per run.

| Column Name | Type | Nullable | Default | Constraints | Notes |
|---|---|---|---|---|---|
| id | UUID | NO | uuid4() | PRIMARY KEY | Evidence record ID |
| tenant_id | VARCHAR(100) | NO | - | NOT NULL | Tenant isolation (INV-7) |
| causal_candidate_id | UUID | NO | - | NOT NULL, FK -> causal_candidate.id ON DELETE CASCADE | Parent candidate |
| sequence_entry_a_id | BIGINT | NO | - | NOT NULL, FK -> entity_sequence_log.id | The A-side sequence log entry |
| sequence_entry_b_id | BIGINT | NO | - | NOT NULL, FK -> entity_sequence_log.id | The B-side sequence log entry |
| fragment_a_id | UUID | NO | - | NOT NULL, FK -> abeyance_fragment.id | Denormalized from sequence_entry_a for direct fragment lookup |
| fragment_b_id | UUID | NO | - | NOT NULL, FK -> abeyance_fragment.id | Denormalized from sequence_entry_b |
| ts_a | TIMESTAMP WITH TIME ZONE | NO | - | NOT NULL | event_timestamp of entry A |
| ts_b | TIMESTAMP WITH TIME ZONE | NO | - | NOT NULL | event_timestamp of entry B |
| lag_seconds | FLOAT | NO | - | NOT NULL | Signed lag for this specific pair (ts_b - ts_a) |
| state_key_a | VARCHAR(200) | NO | - | NOT NULL | State of entity A at this co-occurrence |
| state_key_b | VARCHAR(200) | NO | - | NOT NULL | State of entity B at this co-occurrence |
| is_sampled | BOOLEAN | NO | FALSE | NOT NULL, DEFAULT | TRUE if this row was selected as a representative sample (vs. total population stored) |
| created_at | TIMESTAMP WITH TIME ZONE | NO | now() | NOT NULL, server_default | Row creation time |

#### 5.2.1 Indexes

| Index Name | Columns | Type | Notes |
|---|---|---|---|
| ix_cep_candidate | (causal_candidate_id) | BTREE | "Get all evidence for this candidate" |
| ix_cep_fragment_a | (fragment_a_id) | BTREE | Reverse lookup: which candidates cite this fragment |
| ix_cep_fragment_b | (fragment_b_id) | BTREE | Reverse lookup: which candidates cite this fragment |

#### 5.2.2 Sampling Strategy

When `n_events > max_evidence_pairs` (50):
- Retain the 10 events with the **smallest absolute lag** (tightest temporal coupling -- most informative for lag estimation).
- Retain the 10 events with the **largest absolute lag** within the co-occurrence window (boundary cases).
- Randomly sample the remaining `max_evidence_pairs - 20` events from the middle of the lag distribution.

This ensures that the stored evidence represents the full range of the observed lag distribution rather than being biased toward any particular lag magnitude.

---

### 5.3 Table: `causal_analysis_run`

Provenance record for each execution of the causal direction analysis job.

| Column Name | Type | Nullable | Default | Constraints | Notes |
|---|---|---|---|---|---|
| id | UUID | NO | uuid4() | PRIMARY KEY | Run ID |
| tenant_id | VARCHAR(100) | NO | - | NOT NULL | Tenant isolation (INV-7) |
| started_at | TIMESTAMP WITH TIME ZONE | NO | - | NOT NULL | Job start time |
| completed_at | TIMESTAMP WITH TIME ZONE | YES | NULL | - | Job end time (NULL if running) |
| analysis_window_start | TIMESTAMP WITH TIME ZONE | NO | - | NOT NULL | Left edge of observation window |
| analysis_window_end | TIMESTAMP WITH TIME ZONE | NO | - | NOT NULL | Right edge of observation window |
| co_occurrence_window_seconds | INTEGER | NO | - | NOT NULL | W parameter used |
| n_min | INTEGER | NO | - | NOT NULL | Minimum sample size parameter |
| delta | FLOAT | NO | - | NOT NULL | Directional threshold parameter |
| cv_max | FLOAT | NO | - | NOT NULL | CV threshold parameter |
| pairs_evaluated | INTEGER | YES | NULL | - | Total entity pairs evaluated |
| pairs_skipped_insufficient | INTEGER | YES | NULL | - | Pairs dropped for n < N_min |
| candidates_created | INTEGER | YES | NULL | - | New causal_candidate rows written |
| candidates_superseded | INTEGER | YES | NULL | - | Existing candidate rows marked is_current=FALSE |
| status | VARCHAR(20) | NO | 'RUNNING' | NOT NULL, DEFAULT | RUNNING / COMPLETED / FAILED |
| error_message | TEXT | YES | NULL | - | If status=FAILED |

---

## 6. Provenance: Evidence Fragment Pairs

Every `causal_candidate` record is backed by a set of `causal_evidence_pair` rows identifying the exact sequence log entries that drove the statistical result. This means:

1. An operator investigating a candidate can navigate from `causal_candidate -> causal_evidence_pair -> entity_sequence_log -> abeyance_fragment` and read the actual raw_content of the source events.
2. If the underlying fragments are purged (retention expiry), the evidence pair rows are cascade-deleted (FK `ON DELETE CASCADE`). The candidate record itself is NOT deleted -- it represents an observed statistical pattern, even if the source events are gone. The `is_current` flag and the retention of `first_observed_co_occurrence` / `last_observed_co_occurrence` timestamps preserve the historical claim.
3. The analysis is reproducible: re-running the algorithm over the same `entity_sequence_log` window with the same parameters produces the same candidates.

---

## 7. Algorithm Configuration Parameters

| Parameter | Default | Description |
|---|---|---|
| `analysis_window_days` | 90 | How far back to look for co-occurrence events |
| `co_occurrence_window_seconds` (W) | 3600 | Max time separation for two events to be considered co-occurring |
| `n_min` | 15 | Minimum co-occurrence events for any candidate record |
| `n_saturate` | 100 | Sample size at which `sample_factor` saturates to 1.0 |
| `delta` | 0.80 | Minimum directional fraction for a record to be written |
| `cv_max` | 0.50 | Maximum coefficient of variation (lag stability) |
| `min_confidence` | 0.25 | Minimum composite confidence for record persistence |
| `max_evidence_pairs` | 50 | Max `causal_evidence_pair` rows stored per candidate |
| `max_obs_per_entity` | 5000 | Cap on non-nominal observations per entity per window (prevents O(n^2) blowup) |
| `w_sample` | 0.30 | Confidence weight for sample_factor |
| `w_direction` | 0.50 | Confidence weight for direction_factor |
| `w_stability` | 0.20 | Confidence weight for stability_factor |

Per-domain overrides follow the same pattern as the transition matrix (`sequence_window_days`). The `co_occurrence_window_seconds` parameter in particular should be domain-tuned: transport layer faults propagate within minutes; capacity-driven trends may have lag windows of hours.

---

## 8. Explicit Caveat: Temporal Precedence is Not Causation

This mechanism detects that A consistently precedes B. It does not prove that A causes B.

**Alternative explanations for observed directional precedence**:

1. **Common cause**: An upstream event C (e.g., a planned maintenance window, a power dip) triggers A and B independently, with A's instrumentation firing faster than B's. The lag reflects instrumentation latency, not physical causation.

2. **Reverse causation with instrumentation delay**: B physically causes A, but the alarm for B is raised with a delay (e.g., it requires threshold crossing over multiple polling cycles). A is reported first, B reported later.

3. **Spurious correlation**: A and B happen to co-occur during the same operational periods (e.g., both entities are in the same geographic region and affected by the same weather events or maintenance windows).

4. **Selection bias from the co-occurrence window**: A wide co-occurrence window (W = 3600s) admits many incidental pairs. Reducing W reduces false positive rate but also reduces sample size.

**Operator guidance encoded in the record label**: All candidate records carry `confidence_label` in `{HIGH, MEDIUM, LOW}`. The consuming layer (hypothesis generation or operator UI) MUST surface the caveat alongside the confidence label. The confidence metric is a measure of **statistical strength of the directional pattern**, not a probability of causation.

---

## 9. Telecom Example: Transport -> RAN Causal Candidate

### 9.1 Setup

Tenant `telco2`. Entity `ROUTER-22` (domain: TRANSPORT) provides backhaul to a cluster of eNodeBs. Entity `ENB-4412` (domain: RAN) is one of those eNodeBs.

### 9.2 Observation Window

Analysis window: 90 days. Co-occurrence window W = 3600 seconds (1 hour).

Over 90 days, non-nominal observations are collected for both entities from `entity_sequence_log`:

- ROUTER-22 non-nominal events: 48 (primarily `DARK_ATTRIBUTE:TELEMETRY_EVENT:WARNING` and `DARK_NODE:ALARM:MAJOR`)
- ENB-4412 non-nominal events: 62 (primarily `DARK_ATTRIBUTE:ALARM:MINOR` and `DARK_NODE:ALARM:MAJOR`)

### 9.3 Co-occurrence Events

After scanning all (ROUTER-22, ENB-4412) event pairs within the 1-hour window:

- Total co-occurrence events found: `n = 31`
- Events where ROUTER-22 preceded ENB-4412 (lag > 0): 27
- Events where ENB-4412 preceded ROUTER-22 (lag < 0): 4

Lag statistics:
```
n              = 31
n_positive     = 27
df             = 27/31 = 0.871
mean_lag       = +842 seconds (~14 minutes)
std_lag        = 310 seconds
cv             = 310 / 842 = 0.368
```

### 9.4 Qualification Check

```
n=31 >= N_min=15                  -> PASS
df=0.871 >= delta=0.80            -> PASS (using standard threshold; n >= 30)
cv=0.368 <= CV_max=0.50           -> PASS
mean_lag=842 > 0                  -> PASS (A precedes B)
```

### 9.5 Confidence Computation

```
sample_factor   = min(31, 100) / 100 = 0.31
direction_factor = (0.871 - 0.80) / (1.0 - 0.80) = 0.071 / 0.20 = 0.355
stability_factor = max(0.0, 1.0 - 0.368 / 0.50) = max(0.0, 0.264) = 0.264

confidence = 0.30 * 0.31 + 0.50 * 0.355 + 0.20 * 0.264
           = 0.093 + 0.1775 + 0.0528
           = 0.323
confidence_label = LOW
```

### 9.6 Resulting Causal Candidate Record

```
entity_a_identifier:  ROUTER-22
entity_b_identifier:  ENB-4412
entity_a_domain:      TRANSPORT
entity_b_domain:      RAN
mean_lag_seconds:     842.0
std_lag_seconds:      310.0
sample_size:          31
directional_fraction: 0.871
cv:                   0.368
confidence:           0.323
confidence_label:     LOW
analysis_window_start: 2025-12-16T00:00:00Z
analysis_window_end:   2026-03-16T00:00:00Z
co_occurrence_window_seconds: 3600
```

### 9.7 Evidence Fragment Pairs (stored sample)

Up to 50 `causal_evidence_pair` rows are stored linking the `entity_sequence_log` entries. Example of one representative pair:

```
ts_a:        2026-01-14T02:17:00Z  (ROUTER-22 enters DARK_NODE:ALARM:MAJOR)
ts_b:        2026-01-14T02:31:00Z  (ENB-4412 enters DARK_NODE:ALARM:MAJOR)
lag_seconds: +840.0
state_key_a: DARK_NODE:ALARM:MAJOR
state_key_b: DARK_NODE:ALARM:MAJOR
fragment_a:  Fragment UUID -> raw_content: "Interface GigE0/0/1 down: link failure"
fragment_b:  Fragment UUID -> raw_content: "Cell outage: S1 interface lost"
```

### 9.8 Interpretation

The candidate states: "ROUTER-22 non-nominal events precede ENB-4412 non-nominal events by a mean of 14 minutes, with a directional fraction of 87.1%, on 31 co-occurrence observations. Confidence: LOW."

The LOW confidence reflects moderate sample size (n=31, not yet saturated) and a directional fraction only modestly above the 0.80 threshold. The claim is plausible but requires either more observations (the confidence will rise naturally with continued data ingestion) or operator investigation.

The operator can drill into the evidence pairs to confirm: the ROUTER-22 alarms reference S1 transport interface failures, and the ENB-4412 alarms consistently cite S1 loss -- which is consistent with physical causation. This domain knowledge is outside the scope of the algorithm; the algorithm's role is to surface the pattern for the operator to evaluate.

**The algorithm does not assert that ROUTER-22 causes ENB-4412 outages. It asserts that ROUTER-22 non-nominal events have consistently preceded ENB-4412 non-nominal events by approximately 14 minutes in 87% of co-occurring cases over the past 90 days.**

---

## 10. Job Scheduling and Maintenance

### 10.1 Run Frequency

The causal direction analysis job runs on a configurable schedule, default: once per day per tenant. It is computationally heavier than the transition matrix incremental updates because it is cross-entity; it is not run inline with fragment ingestion.

```python
async def run_causal_analysis(session: AsyncSession, tenant_id: str) -> str:
    """
    Entry point for the scheduled causal direction analysis job.
    Returns the causal_analysis_run.id for this execution.
    """
```

### 10.2 Supersession

When a new analysis run completes for a tenant, existing `causal_candidate` records for the same entity pair are:
1. Marked `is_current = FALSE`.
2. Linked to the new record via `superseded_by`.

This creates an audit trail of how the causal candidate has evolved over time (confidence increasing as more data accumulates, or disappearing if the pattern breaks).

### 10.3 Staleness

If no analysis run has completed within the last 48 hours for a tenant, the consumer layer MUST treat all `causal_candidate` records for that tenant as stale and suppress them from display. Stale candidates are not deleted; they re-become current when the next run completes.

### 10.4 Candidate Expiry

`causal_candidate` records with `is_current = FALSE` older than 180 days are purged by the maintenance sweep. `causal_evidence_pair` rows are cascade-deleted. This prevents unbounded growth of the historical record while retaining recent trend data.

---

## 11. Invariants

| Invariant | Description |
|---|---|
| INV-7 | `tenant_id` present and indexed on all three tables. All queries scoped by tenant. |
| INV-20 | Every `causal_candidate` row has `mean_lag_seconds > 0` (direction orientation enforced at application layer). |
| INV-21 | Every `causal_candidate` row has `sample_size >= N_min` (application enforced; N_min=15). |
| INV-22 | Every `causal_evidence_pair` row references a valid `causal_candidate.id` (FK with CASCADE). |
| INV-23 | `entity_a_id != entity_b_id` (CHECK constraint). An entity cannot be its own causal candidate. |
| INV-24 | At most one `is_current = TRUE` record exists per `(tenant_id, entity_a_id, entity_b_id)` at any given time. Enforced by the supersession protocol in Section 10.2; a unique partial index may optionally enforce this at the DB level. |
| INV-25 | Temporal precedence findings are labelled as causal candidates, never as causal facts. The `confidence_label` field encodes statistical strength, not probability of causation. |

---

## 12. Storage Estimates

### 12.1 causal_candidate

Per row: ~400 bytes (UUIDs, floats, timestamps, identifiers).

For a tenant with 5,000 entity pairs qualifying for analysis:
- At 30% conversion rate (pairs that meet N_min and directional thresholds): ~1,500 candidate records.
- With supersession history retained for 180 days at 1 run/day: up to 270,000 rows per tenant.
- Storage: 270,000 * 400 bytes = ~108 MB per tenant (acceptable).

In practice, most tenants will have far fewer qualifying pairs. The quadratic candidate generation is bounded by topological proximity filtering, which substantially reduces the search space from all-pairs to topology-adjacent pairs.

### 12.2 causal_evidence_pair

Per row: ~200 bytes.

At 50 evidence pairs per candidate and 1,500 current candidates: 75,000 rows per run.
- Storage: 75,000 * 200 bytes = ~15 MB per run (negligible).

### 12.3 causal_analysis_run

Per row: ~300 bytes. One row per run per tenant per day: negligible.

---

## 13. Migration

### 13.1 Alembic Steps

```
1. CREATE TABLE causal_analysis_run (Section 5.3)
2. CREATE TABLE causal_candidate (Section 5.1)
3. CREATE INDEXES on causal_candidate (Section 5.1.1)
4. ADD CHECK CONSTRAINTS on causal_candidate (Section 5.1.2)
5. CREATE TABLE causal_evidence_pair (Section 5.2)
6. CREATE INDEXES on causal_evidence_pair (Section 5.2.1)
```

No backfill is required. The causal direction analysis job produces candidates by reading the already-populated `entity_sequence_log`. The first run after migration will populate the tables from scratch.

### 13.2 Prerequisites

- `entity_sequence_log` must exist and contain data (D2.1 must be deployed and have run its backfill).
- `shadow_entity` must exist (FK target for entity_a_id, entity_b_id).
- `abeyance_fragment` must exist (FK target for fragment_a_id, fragment_b_id in evidence pairs).

### 13.3 Rollback

All three tables are new. Rollback is DROP TABLE in reverse order (evidence pairs, candidates, run log). No existing tables are modified.

---

## 14. Downstream Consumers

| Consumer | What it reads | How it uses it |
|---|---|---|
| Hypothesis Generation (T4.x) | `causal_candidate WHERE is_current = TRUE AND confidence >= 0.50` | Incorporates HIGH/MEDIUM directional candidates as supporting evidence when generating causal hypotheses |
| Operator Investigation UI | `causal_candidate` + `causal_evidence_pair` | Displays directional candidates for an entity, with drilldown to fragment evidence |
| Counterfactual Simulation (T5.5) | Out of scope for this mechanism | T5.5 uses candidates as starting hypotheses for counterfactual reasoning |

---

Generated: 2026-03-16 | Task D3.1 | Abeyance Memory v3.0 | Discovery Mechanism #10 | Tier 3
