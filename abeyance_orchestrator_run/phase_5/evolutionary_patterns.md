# Evolutionary Pattern Discovery -- Discovery Mechanism #14

**Task**: D14.1 -- Evolutionary Pattern Discovery
**Version**: 3.0
**Date**: 2026-03-16
**Status**: Specification
**Tier**: 4 (Advanced -- requires all preceding tiers stable)
**Dependencies**:
- Outcome-Linked Scoring Calibration (phase_4/outcome_calibration.md): provides `predictive_power` fitness component
- Surprise Metrics Engine (phase_3/surprise_engine.md): provides `novelty` fitness component
- Pattern Compression Discovery (phase_5/pattern_compression.md): provides `compression_gain` fitness component

---

## 1. Problem Statement

Pattern compression (Mechanism #11) produces compression rules from a single time window. Each rule is a static snapshot: "in the past N days, this population compressed to this grammar." But patterns in telecom networks are not static. A cross-tracking-area alarm correlation may strengthen, weaken, merge with a sibling pattern, or split into two distinct sub-patterns as network topology evolves, software versions change, and operator remediations accumulate.

No existing mechanism treats confirmed patterns as **entities with history and fitness**. A pattern detected in week 1 and the same pattern detected in week 4 are stored as independent records with no ancestry tracking, no fitness trajectory, and no mechanism to ask "is this pattern getting stronger?" or "have two weak patterns merged into one strong one?"

Evolutionary pattern discovery fills this gap. It maintains a **bounded population of confirmed patterns**, assigns each a **fitness score** derived from multiple evidence sources, and applies **selection, mutation, and recombination operators** on a generation schedule. Patterns with high and improving fitness survive; low-fitness patterns are culled; novel combinations are explored through recombination.

**What this is**: A meta-layer over confirmed patterns that tracks pattern evolution across time. It does not generate snap decisions, does not invoke the snap engine, and does not modify weight profiles. It is a population management system operating entirely on the output of Tiers 1-3.

**What this is NOT**: It does not replace pattern compression, surprise detection, or outcome calibration. It consumes their outputs.

---

## 2. Core Abstractions

### 2.1 Confirmed Pattern

A **confirmed pattern** `P` is a compression rule that has been validated by at least one `CompressionDiscoveryEvent` with `review_verdict = 'TRUE_DISCOVERY'` OR `discovery_class = 'DOMINANT'` and `is_novel = TRUE`, for a given `(tenant_id, failure_mode_profile)` partition.

The confirmed pattern record stores:
- The compression rule `ρ` (the 5-band condition vector from Mechanism #11)
- The partition `(tenant_id, failure_mode_profile)` it was discovered in
- The discovery event that first confirmed it
- Its full evolutionary history: fitness scores, ancestry, mutation/recombination events

### 2.2 Pattern Individual

A **pattern individual** `I` is the evolutionary unit. Each individual has:
- A unique identifier
- A genotype: the compression rule `ρ`
- A fitness score `f ∈ [0.0, 1.0]` (see Section 3)
- A generation counter: how many evolution cycles it has participated in
- Ancestry references: parent individual IDs (one parent = born from mutation; two parents = born from recombination; no parents = original discovery)
- A fitness trajectory: the sequence of fitness scores across all generations it has lived

One confirmed pattern maps to exactly one individual in the population. When a pattern is culled (fitness too low, population cap exceeded), its record is archived; it is not deleted.

### 2.3 Population

The **population** `Ω` for a partition `(tenant_id, failure_mode_profile)` is the set of all currently active (non-archived) individuals for that partition.

**Bounded population size**: `|Ω| ≤ POP_CAP` where `POP_CAP = 50` per partition. The rationale: with 3^5 = 243 possible distinct 5-band rules for a fixed failure mode, and in practice far fewer meaningful rules per tenant, a cap of 50 is generous while bounding storage and computation. The cap is enforced at the end of each generation cycle via selection pressure.

---

## 3. Fitness Function

### 3.1 Overview

The fitness of a pattern individual `I` at generation `g` is a weighted combination of four components, each sourced from a specific upstream mechanism:

```
f(I, g) = w_pp * PP(I, g)
         + w_st * ST(I, g)
         + w_nv * NV(I, g)
         + w_cg * CG(I, g)
```

Where:
- `PP(I, g)` = predictive power, sourced from outcome calibration (Mechanism #5)
- `ST(I, g)` = stability, computed from the individual's own fitness trajectory
- `NV(I, g)` = novelty, sourced from the surprise engine (Mechanism #1)
- `CG(I, g)` = compression gain, sourced from pattern compression (Mechanism #11)

**Default weights:**

| Component | Weight | Rationale |
|---|---|---|
| `w_pp` | 0.35 | Predictive power is the most operationally valuable property: does this pattern predict real incidents? |
| `w_st` | 0.25 | Stable patterns are more actionable than volatile ones. Stability rewards consistency over generations. |
| `w_nv` | 0.15 | Novelty is rewarded but not dominant. A very novel pattern that is not predictive should not outcompete proven ones. |
| `w_cg` | 0.25 | Compression gain measures structural regularity -- the pattern must explain a population efficiently to be meaningful. |

All four components are normalized to `[0.0, 1.0]` before weighting. All weights sum to 1.0. The final fitness `f(I, g) ∈ [0.0, 1.0]`.

### 3.2 Component: Predictive Power (PP)

**Source**: `calibration_history` and `snap_outcome_feedback`, both maintained by Outcome-Linked Scoring Calibration (phase_4/outcome_calibration.md).

**Definition**: The predictive power of a pattern individual `I` with rule `ρ` is the precision of `ρ` as a predictor of true positive snap outcomes, computed over the most recent `PP_WINDOW_DAYS = 30` days of snap decisions that match `ρ`.

**Algorithm**:

```
FUNCTION compute_predictive_power(I, tenant_id, failure_mode_profile, window_days=30):

    # Step 1: Retrieve snap decisions matching the pattern rule
    # A snap decision matches rule ρ if its discretized score signature
    # (per Mechanism #11, Section 2.1) satisfies all non-wildcard conditions of ρ
    matching_decisions = query_snap_decisions_matching_rule(
        tenant_id, failure_mode_profile,
        rule = I.genotype,
        window_days = window_days
    )

    if len(matching_decisions) < PP_MIN_DECISIONS:
        return PP_DEFAULT  # insufficient data; see Section 3.2.1

    # Step 2: Retrieve outcomes for those decisions
    # Uses snap_outcome_feedback.outcome_label for labeled decisions
    labeled = [d for d in matching_decisions if d has non-superseded feedback]

    if len(labeled) < PP_MIN_LABELED:
        return PP_DEFAULT  # insufficient labeled outcomes

    # Step 3: Compute precision
    true_positives = sum(1 for d in labeled
                         if d.outcome_label == 'TRUE_POSITIVE')
    precision = true_positives / len(labeled)

    return precision   # already in [0.0, 1.0]
```

**Parameters:**

| Parameter | Value | Rationale |
|---|---|---|
| `PP_WINDOW_DAYS` | 30 | Match the calibration feedback window. Long enough to accumulate stable signal. |
| `PP_MIN_DECISIONS` | 5 | Fewer than 5 matching decisions in 30 days means the pattern is rare; evidence is thin. |
| `PP_MIN_LABELED` | 3 | At least 3 labeled outcomes required. Below this, precision is noisy. |
| `PP_DEFAULT` | 0.40 | Neutral default for data-insufficient cases. Does not reward or penalize. |

**Cross-reference**: This query accesses `snap_decision_log` (Tier 1) and `snap_outcome_feedback` (phase_4/outcome_calibration.md Section 4.1). The `review_verdict` field in `calibration_history` is not used directly; raw feedback labels are used to compute precision independently of weight calibration.

### 3.3 Component: Stability (ST)

**Source**: The individual's own fitness trajectory within the evolutionary system.

**Definition**: Stability measures consistency of fitness across recent generations. A pattern that oscillates between high and low fitness is less stable than one with steady fitness.

**Algorithm**:

```
FUNCTION compute_stability(I, window_generations=5):

    # Get fitness scores from the last window_generations cycles
    recent_fitness = I.fitness_trajectory[-window_generations:]

    if len(recent_fitness) < 2:
        return ST_DEFAULT  # not enough history

    mean_f = mean(recent_fitness)
    std_f  = std(recent_fitness)

    # Stability = 1 - normalized standard deviation
    # If std_f = 0 (perfectly stable), stability = 1.0
    # If std_f = mean_f (CV = 1.0), stability = 0.0
    # Clamp to [0.0, 1.0]

    if mean_f < 1e-6:
        return 0.0   # zero-mean pattern is not stable (it is extinct)

    coefficient_of_variation = std_f / mean_f
    stability = max(0.0, 1.0 - coefficient_of_variation)

    return stability
```

**Parameters:**

| Parameter | Value | Rationale |
|---|---|---|
| `ST_WINDOW_GENERATIONS` | 5 | Five generations of history captures medium-term trends without requiring a long history. New individuals have less history and get `ST_DEFAULT`. |
| `ST_DEFAULT` | 0.50 | Neutral default for new individuals without sufficient history. |

**Note**: Stability is the one fitness component computed entirely within the evolutionary system itself. It does not query any external table beyond the individual's own trajectory, which is stored in `pattern_individual` (Section 9.1).

### 3.4 Component: Novelty (NV)

**Source**: `surprise_event` table, maintained by the Surprise Metrics Engine (phase_3/surprise_engine.md).

**Definition**: Novelty measures how frequently the pattern is associated with high-surprise snap decisions. A pattern that continues to surface surprising events is more novel than one whose population has become routine. This rewards patterns that are still "actively informative" rather than fully domesticated.

**Algorithm**:

```
FUNCTION compute_novelty(I, tenant_id, failure_mode_profile, window_days=30):

    # Step 1: Retrieve snap decisions matching the pattern rule (same query as PP)
    matching_decisions = query_snap_decisions_matching_rule(
        tenant_id, failure_mode_profile,
        rule = I.genotype,
        window_days = window_days
    )

    if len(matching_decisions) < NV_MIN_DECISIONS:
        return NV_DEFAULT

    # Step 2: Retrieve surprise events for those decisions
    # A surprise event is associated with a decision via snap_decision_id
    matching_snap_ids = {d.id for d in matching_decisions}

    surprise_events = query_surprise_events_for_decisions(
        matching_snap_ids,
        escalation_type = 'DISCOVERY'
    )

    # Step 3: Novelty = fraction of matching decisions with a DISCOVERY surprise event
    novelty_rate = len(surprise_events) / len(matching_decisions)

    # Step 4: Scale: novelty_rate=0.0 → NV=0.0, novelty_rate >= NV_SATURATION → NV=1.0
    # A pattern where every decision triggers a surprise is maximally novel.
    # A pattern where no decision triggers surprise is not novel.
    # NV_SATURATION prevents reward saturation at low novelty rates.
    novelty = min(1.0, novelty_rate / NV_SATURATION)

    return novelty
```

**Parameters:**

| Parameter | Value | Rationale |
|---|---|---|
| `NV_WINDOW_DAYS` | 30 | Same as PP window for consistency. |
| `NV_MIN_DECISIONS` | 5 | Below this, the novelty rate is too noisy. |
| `NV_DEFAULT` | 0.30 | Below-neutral default for data-insufficient cases. Low novelty is acceptable but not rewarded. |
| `NV_SATURATION` | 0.10 | 10% of matching decisions triggering DISCOVERY surprise is treated as maximal novelty. In typical deployment, 2% of ALL decisions trigger surprise (surprise engine `ESCALATION_ALPHA=0.02`); a pattern with a 10% rate is 5x the baseline and saturates the novelty component. |

**Cross-reference**: Queries `surprise_event.snap_decision_id` (phase_3/surprise_engine.md Section 7.1) with filter `escalation_type = 'DISCOVERY'`. Does not use `DRIFT_ALERT` or `CALIBRATION_ALERT` events, which indicate data quality issues rather than genuine pattern novelty.

### 3.5 Component: Compression Gain (CG)

**Source**: `compression_discovery_event` table, maintained by Pattern Compression Discovery (phase_5/pattern_compression.md).

**Definition**: Compression gain measures how efficiently the pattern explains a population. It is taken directly from the most recent `CompressionDiscoveryEvent` in which the rule `ρ` appears as the dominant rule or as any rule in `D`.

**Algorithm**:

```
FUNCTION compute_compression_gain(I, tenant_id, failure_mode_profile, window_days=30):

    # Retrieve the most recent compression discovery event for this partition
    # that includes I.genotype in its rules array
    recent_events = query_compression_events_containing_rule(
        tenant_id, failure_mode_profile,
        rule = I.genotype,
        window_days = window_days
    )

    if not recent_events:
        return CG_DEFAULT

    # Use the most recent event
    latest_event = max(recent_events, key=lambda e: e.created_at)

    # If the rule is the dominant rule in the event, use the event's
    # compression_gain directly (the dominant rule drives the metric).
    if latest_event.dominant_rule == I.genotype:
        return latest_event.compression_gain

    # If the rule is a non-dominant rule in the event, scale its contribution
    # by its individual coverage fraction (its share of the explained population).
    for rule_obj in latest_event.rules:
        if rule_obj.conditions == I.genotype:
            # Scale event-level compression_gain by this rule's coverage fraction
            # vs the dominant rule's coverage fraction
            scale = rule_obj.coverage_fraction / latest_event.dominant_coverage_fraction
            return min(1.0, latest_event.compression_gain * scale)

    return CG_DEFAULT
```

**Parameters:**

| Parameter | Value | Rationale |
|---|---|---|
| `CG_WINDOW_DAYS` | 30 | Same window as other components. |
| `CG_DEFAULT` | 0.20 | Below-neutral default. A pattern that is not appearing in recent compression events is weakening. |

**Cross-reference**: Queries `compression_discovery_event` (phase_5/pattern_compression.md Section 8.1). The `rules` JSONB array is parsed to locate the individual's genotype among the event's rules.

### 3.6 Fitness Formula Summary

```
f(I, g) = 0.35 * PP(I, g)
         + 0.25 * ST(I, g)
         + 0.15 * NV(I, g)
         + 0.25 * CG(I, g)
```

**Range**: `f(I, g) ∈ [0.0, 1.0]` by construction (each component in [0.0, 1.0], weights sum to 1.0).

**Fitness interpretation:**

| Fitness Range | Interpretation | Typical Operator Action |
|---|---|---|
| [0.80, 1.00] | Elite pattern. High predictive power, stable, novel, compresses efficiently. | Prioritize for CMDB rule encoding; recommend as detection template. |
| [0.60, 0.80) | Established pattern. Performing well but not elite. | Monitor; include in operator dashboards. |
| [0.40, 0.60) | Marginal pattern. Mixed evidence; may be improving or declining. | Watch for trajectory; do not act on it yet. |
| [0.20, 0.40) | Weak pattern. Low predictive or structural value. | Candidate for selection pressure (culling if below replacement threshold). |
| [0.00, 0.20) | Dying pattern. Effectively inactive or proven useless. | Archive unless recombination is pending. |

---

## 4. Selection Operator

### 4.1 Purpose

Selection determines which individuals survive to the next generation. It applies pressure to cull low-fitness individuals when the population approaches the cap, while preserving elite individuals unconditionally.

### 4.2 Selection Algorithm

Selection runs at the end of each generation cycle (see Section 7), after all fitness scores have been recomputed:

```
FUNCTION select(Ω, POP_CAP=50, ELITE_THRESHOLD=0.70, CULLING_THRESHOLD=0.25):

    # Step 1: Unconditionally preserve elite individuals
    elite = {I for I in Ω if f(I) >= ELITE_THRESHOLD}

    # Step 2: If population size <= POP_CAP, no culling needed beyond threshold
    survivors = {I for I in Ω if f(I) >= CULLING_THRESHOLD}

    # Step 3: If population still exceeds POP_CAP after threshold culling,
    # apply tournament selection to fill remaining slots up to POP_CAP.
    # Elite individuals are already included.
    if len(survivors) > POP_CAP:
        non_elite_survivors = survivors - elite
        # Sort non-elite by descending fitness, take top (POP_CAP - |elite|)
        slots_remaining = POP_CAP - len(elite)
        top_non_elite = sorted(non_elite_survivors,
                               key=lambda I: f(I),
                               reverse=True)[:slots_remaining]
        survivors = elite | set(top_non_elite)

    # Step 4: Archive culled individuals (never delete)
    culled = Ω - survivors
    for I in culled:
        archive(I, reason='culled_generation_g', generation=g)

    return survivors
```

**Parameters:**

| Parameter | Value | Rationale |
|---|---|---|
| `POP_CAP` | 50 per partition | Bounds storage and computation. See Section 2.3. |
| `ELITE_THRESHOLD` | 0.70 | Individuals above this fitness are never subject to culling pressure. |
| `CULLING_THRESHOLD` | 0.25 | Individuals below this fitness are culled unconditionally (unless elite — contradiction resolved by elite check taking precedence). In practice, elite individuals will always be above culling threshold. |

**Rank-based softening**: If culling would reduce the population below `POP_FLOOR = 3` for a partition that has been active for at least 3 generations, the lowest-fitness survivors are preserved (up to POP_FLOOR) regardless of culling threshold. This prevents total population extinction in partitions with temporarily poor evidence quality.

### 4.3 Archival Policy

Culled individuals are moved to `pattern_individual_archive` (Section 9.2) with their full fitness trajectory intact. They are not recoverable into the active population automatically, but can be reintroduced manually via operator action if a pattern re-emerges and is discovered again (which produces a new individual with the culled individual's ancestry linked).

---

## 5. Mutation Operator

### 5.1 Purpose

Mutation generates new candidate individuals by making small modifications to an existing individual's genotype (compression rule). It explores the neighborhood of proven patterns: "if this pattern is strong, are nearby patterns also strong?"

### 5.2 Mutation Operations

Three mutation operations are defined, applied independently:

**Operation M1: Single-Dimension Relaxation**

Replace one non-wildcard condition in `ρ` with a wildcard `*`. This generalizes the pattern by removing one constraint.

```
Example:
ρ  = (H, L, *, H, L)   # specificity=4
M1 → (H, L, *, H, *)   # specificity=3 (relaxed entity overlap constraint)
M1 → (*, L, *, H, L)   # specificity=3 (relaxed semantic constraint)
```

M1 is applicable when `specificity(ρ) >= 1` (at least one non-wildcard condition exists).

**Operation M2: Single-Dimension Tightening**

Replace one wildcard condition in `ρ` with a specific band value `L`, `M`, or `H` sampled from the band distribution of the matching population in the most recent compression event.

```
Example:
ρ  = (H, L, *, H, L)   # specificity=4
# In the last compression event, temporal scores for matches were:
#   band_L: 5 matches, band_M: 12 matches, band_H: 16 matches
# Sample proportionally → H has highest weight
M2 → (H, L, H, H, L)   # specificity=5 (tightened temporal to H)
```

M2 is applicable when `specificity(ρ) < 5` (at least one wildcard exists). The tightened value is sampled proportionally from the empirical band distribution observed in the parent pattern's matching population, not uniformly at random. This ensures mutations are guided by actual data.

**Operation M3: Single-Dimension Band Shift**

Replace one non-wildcard condition with an adjacent band value.

```
Band adjacency: L ↔ M ↔ H (L and H are not adjacent)

Example:
ρ  = (H, L, *, H, L)
M3 → (M, L, *, H, L)   # semantic shifted H → M
M3 → (H, M, *, H, L)   # topological shifted L → M
```

M3 is applicable when `specificity(ρ) >= 1`. It explores the boundary of the pattern's structural region.

### 5.3 Mutation Rate and Child Admission

At each generation cycle, at most `MUT_CHILDREN_PER_INDIVIDUAL = 2` mutation children are generated per parent individual. For each parent:

1. Select a mutation operation uniformly at random from the applicable operations for this genotype.
2. Apply the operation. If the operation requires a choice (which dimension to mutate, which band to assign), make the choice guided by the empirical population data (M2) or uniformly at random (M1, M3).
3. Generate the child individual with:
   - `genotype` = mutated rule
   - `fitness` = 0.0 (computed in the next generation cycle after evidence accumulates)
   - `ancestry` = [parent.id]
   - `generation` = g + 1
   - `generation_born` = current generation

**Admission gate**: A mutation child is admitted to the population only if:
- It does not already exist in the active population (identical genotype check)
- It does not already exist in the archive (identical genotype check — re-admitting archived patterns is prohibited)
- The population has not reached `POP_CAP` after adding elite individuals and existing survivors (selection runs before admission; mutations fill remaining slots up to cap)

**Mutation generation budget**: At most `MUT_BUDGET_PER_GEN = 5` new individuals from mutation are added to the population per partition per generation cycle. If multiple parents generate children, admissions are processed in descending order of parent fitness.

---

## 6. Recombination Operator

### 6.1 Purpose

Recombination generates new candidate individuals by combining the genotypes of two parent individuals. It tests whether two proven patterns can merge into a single, more general rule that captures both of their populations.

### 6.2 Recombination Eligibility

Two individuals `I_a` and `I_b` are eligible for recombination when:

1. They belong to the same partition `(tenant_id, failure_mode_profile)`.
2. Both have `f >= RECOMB_MIN_FITNESS = 0.40` (both parents must be at least marginal — recombining two weak patterns is unlikely to produce a strong child).
3. Their genotypes differ in at most `RECOMB_MAX_DIFFER = 3` dimensions (more than 3 differing conditions would produce an uninformative all-wildcard rule).
4. They are not already in a parent-child relationship (a parent's mutation child should not immediately be recombined with its parent).

### 6.3 Recombination Algorithm

**Intersection operator**: The child's genotype is the **intersection** of the two parents' conditions. For each dimension position:

```
FUNCTION recombine_genotypes(ρ_a, ρ_b):
    child_conditions = []
    for i in range(5):
        if ρ_a[i] == ρ_b[i]:
            child_conditions.append(ρ_a[i])   # agreement → keep
        elif ρ_a[i] == '*' or ρ_b[i] == '*':
            child_conditions.append('*')       # one wildcard → wildcard wins
        else:
            child_conditions.append('*')       # disagreement → generalize to wildcard
    return tuple(child_conditions)
```

**Semantics**: The child rule matches any pattern matched by EITHER parent (generalization). This is the logical OR / union of the two parents' populations.

**Specificity check**: If the resulting child has `specificity == 0` (all wildcards), it matches every pattern and is uninformative. This child is discarded without admission.

**Example**:
```
Parent A: (H, L, *, H, L)   # high semantic, low topo, any temp, high oper, low ent
Parent B: (H, L, H, *, L)   # high semantic, low topo, high temp, any oper, low ent
Child:    (H, L, *, *, L)   # high semantic, low topo, any temp, any oper, low ent
```
The child generalizes across both the temporal and operational dimensions, exploring whether the common semantic + topological + entity structure is sufficient without constraining the other two.

### 6.4 Recombination Scheduling

Recombination is evaluated for all eligible pairs within a partition at each generation cycle. To prevent combinatorial explosion:

- Maximum pairs evaluated per cycle per partition: `RECOMB_MAX_PAIRS = 20`.
- If eligible pairs exceed 20, select the 20 with the highest combined fitness `f(I_a) + f(I_b)`.
- At most `RECOMB_BUDGET_PER_GEN = 3` new individuals from recombination are admitted per partition per generation cycle.

Recombination children are admitted after mutation children (mutation has priority for the remaining slots up to `POP_CAP`).

---

## 7. Generation Schedule

### 7.1 Batch Processing

Evolution runs as a **periodic batch job**, decoupled from all real-time snap processing. It is NOT triggered by individual snap decisions or surprise events.

**Default schedule**: Every `GENERATION_INTERVAL_DAYS = 7` (weekly) per partition.

**Rationale**:
- Fitness components `PP`, `NV`, and `CG` require a minimum observation window (`PP_WINDOW_DAYS = 30`, compression window = 24 hours up to 14 days). Running evolution more frequently than weekly provides diminishing evidence quality — fitness scores would be computed on overlapping, barely-changed data windows.
- The generation schedule must be coarser than the pattern compression schedule (24 hours). Evolution consumes compression events that have already been produced; running before compression has processed the latest data wastes a cycle.
- Weekly cadence aligns with typical NOC review cycles, making operator-visible fitness trajectories interpretable on a human timescale.

### 7.2 Generation Execution Order

Within a single generation cycle for partition `(tenant_id, failure_mode_profile)`:

```
1. RECOMPUTE FITNESS
   For each active individual I in Ω:
       PP(I), ST(I), NV(I), CG(I) → f(I, g)
       Append f(I, g) to I.fitness_trajectory

2. SELECTION
   Apply select(Ω) → survivors
   Archive culled individuals

3. MUTATION
   For each survivor I in descending fitness order:
       Generate up to MUT_CHILDREN_PER_INDIVIDUAL=2 mutation children
       Admit up to MUT_BUDGET_PER_GEN=5 children total

4. RECOMBINATION
   Identify eligible pairs among survivors
   Evaluate up to RECOMB_MAX_PAIRS=20 pairs
   Admit up to RECOMB_BUDGET_PER_GEN=3 children total

5. NEW PATTERN INGESTION
   Query compression_discovery_event for new DOMINANT/STANDARD TRUE_DISCOVERY events
   since last generation cycle. For each new event not already in Ω and not in archive:
       Create new individual with genotype=dominant_rule
       Admit to population (subject to POP_CAP)

6. PERSIST
   Write updated individuals, new individuals, and archived individuals to storage
   Write generation_log record (Section 9.3)

7. EMIT EVENTS
   Emit EvolutionGenerationEvent (Section 9.4) for downstream consumers
```

### 7.3 Partition Independence

Each partition `(tenant_id, failure_mode_profile)` runs its generation cycle independently. The schedules are staggered by hashing the partition key to avoid simultaneous load spikes:

```
generation_offset_hours = hash(tenant_id + failure_mode_profile) % 168
# 168 = 7 * 24 hours in a week
# Each partition runs at a fixed day/time within the week
```

---

## 8. Failure Mode: Insufficient Prerequisite Data

### 8.1 Prerequisite Status Check

Before executing a generation cycle for a partition, the evolution engine performs a prerequisite status check:

```
FUNCTION check_prerequisites(tenant_id, failure_mode_profile):

    status = {}

    # Prerequisite 1: Outcome calibration (PP component)
    # Requires: at least 1 calibration_history record with applied=TRUE in the last 90 days
    calibration_ok = exists(
        calibration_history WHERE tenant_id=... AND failure_mode_profile=...
        AND applied=TRUE AND calibration_timestamp >= now() - 90 days
    )
    status['calibration'] = 'OK' if calibration_ok else 'INSUFFICIENT'

    # Prerequisite 2: Surprise engine (NV component)
    # Requires: surprise_distribution_state has total_mass >= 30 for this partition
    # (i.e., the histogram is past cold-start per Mechanism #1 Section 9.1)
    surprise_ok = exists(
        surprise_distribution_state WHERE tenant_id=... AND failure_mode_profile=...
        AND dimension='composite' AND total_mass >= 30
    )
    status['surprise'] = 'OK' if surprise_ok else 'INSUFFICIENT'

    # Prerequisite 3: Pattern compression (CG component)
    # Requires: at least 1 compression_discovery_event in the last 14 days
    compression_ok = exists(
        compression_discovery_event WHERE tenant_id=... AND failure_mode_profile=...
        AND created_at >= now() - 14 days
    )
    status['compression'] = 'OK' if compression_ok else 'INSUFFICIENT'

    return status
```

### 8.2 Behavior Under Insufficient Prerequisites

| Scenario | Behavior |
|---|---|
| All three prerequisites OK | Run generation cycle normally. |
| One prerequisite INSUFFICIENT | Use default value for that fitness component (PP_DEFAULT, NV_DEFAULT, or CG_DEFAULT). Log a warning in `generation_log`. Proceed with reduced fitness signal quality. |
| Two prerequisites INSUFFICIENT | Skip generation cycle entirely. Log SKIPPED in `generation_log` with reason. Do not advance generation counter. Emit operational metric `evolution_generation_skipped{tenant_id, failure_mode_profile}`. |
| All three prerequisites INSUFFICIENT | Skip. Log. Metric. The mechanism is inactive for this partition until prerequisites recover. |
| No active individuals in population AND no qualifying compression events in 90 days | Mark partition as DORMANT in `evolution_partition_state`. Do not schedule further cycles until a new compression discovery event arrives. |

**Re-activation**: A DORMANT partition is re-activated when a new `CompressionDiscoveryEvent` with `review_verdict='TRUE_DISCOVERY'` or `discovery_class='DOMINANT'` arrives for that partition. The evolution engine re-schedules the partition on the next weekly cycle.

### 8.3 Graceful Degradation

When only one prerequisite is insufficient, the fitness function degrades gracefully:

- **Calibration insufficient (no PP)**: The fitness function reweights remaining components proportionally:
  ```
  f(I) = (0.25/0.65)*ST + (0.15/0.65)*NV + (0.25/0.65)*CG
  ```
  The normalization `0.65 = 0.25 + 0.15 + 0.25` ensures the result remains in [0.0, 1.0].

- **Surprise engine insufficient (no NV)**: Reweight to `(0.35/0.85)*PP + (0.25/0.85)*ST + (0.25/0.85)*CG`.

- **Compression insufficient (no CG)**: Reweight to `(0.35/0.75)*PP + (0.25/0.75)*ST + (0.15/0.75)*NV`.

Degraded fitness is flagged in the individual's `fitness_metadata` JSONB field so downstream consumers know the score was computed with partial evidence.

---

## 9. Storage Schema

### 9.1 Table: `pattern_individual`

Active population members.

```sql
CREATE TABLE pattern_individual (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id               TEXT NOT NULL,
    failure_mode_profile    TEXT NOT NULL,

    -- Genotype: the compression rule
    -- Stored in the same format as compression_discovery_event.rules JSONB
    genotype                JSONB NOT NULL,
    -- Example: {"cond_sem":"H","cond_topo":"L","cond_temp":"*",
    --           "cond_oper":"H","cond_ent":"L","specificity":4}

    -- Fitness
    fitness_current         REAL NOT NULL DEFAULT 0.0,
        CONSTRAINT chk_pi_fitness CHECK (fitness_current >= 0.0 AND fitness_current <= 1.0),
    fitness_trajectory      REAL[] NOT NULL DEFAULT '{}',
        -- Array of fitness scores ordered by generation, index 0 = birth generation
    fitness_metadata        JSONB,
        -- Per-generation fitness breakdown: {"pp": 0.72, "st": 0.81, "nv": 0.33,
        --  "cg": 0.61, "degraded_components": ["nv"]}
        -- Stores the MOST RECENT generation's breakdown only

    -- Ancestry
    parent_ids              UUID[] NOT NULL DEFAULT '{}',
        -- Empty array: born from external discovery (no evolutionary parents)
        -- One element: born from mutation
        -- Two elements: born from recombination
    origin_type             TEXT NOT NULL
        CHECK (origin_type IN ('DISCOVERED', 'MUTATION', 'RECOMBINATION')),
    origin_discovery_event_id UUID,
        -- FK to compression_discovery_event.event_id if origin_type='DISCOVERED'
        -- NULL for mutation/recombination children

    -- Generation tracking
    generation_born         INTEGER NOT NULL,
        -- The generation cycle number when this individual was created
    generation_current      INTEGER NOT NULL,
        -- The most recent generation cycle that computed fitness for this individual
    generations_alive       INTEGER NOT NULL DEFAULT 0,
        -- Count of generation cycles this individual has participated in

    -- Lifecycle
    status                  TEXT NOT NULL DEFAULT 'ACTIVE'
        CHECK (status IN ('ACTIVE', 'ARCHIVED')),
    archived_at             TIMESTAMPTZ,
    archive_reason          TEXT,

    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Primary lookup: all active individuals for a partition
CREATE INDEX idx_pi_partition_active
    ON pattern_individual (tenant_id, failure_mode_profile, fitness_current DESC)
    WHERE status = 'ACTIVE';

-- Ancestry lookup: find all children of a given parent
CREATE INDEX idx_pi_parent_ids
    ON pattern_individual USING GIN (parent_ids);

-- Genotype lookup: find if a genotype already exists in the population
CREATE INDEX idx_pi_genotype
    ON pattern_individual USING GIN (genotype);

-- Tenant isolation
CREATE INDEX idx_pi_tenant_time
    ON pattern_individual (tenant_id, created_at DESC);
```

### 9.2 Table: `pattern_individual_archive`

Archived (culled) individuals. Identical schema to `pattern_individual` but populated by moving culled rows here.

```sql
CREATE TABLE pattern_individual_archive (
    -- Identical columns to pattern_individual
    -- All columns including fitness_trajectory are preserved
    id                      UUID PRIMARY KEY,
    tenant_id               TEXT NOT NULL,
    failure_mode_profile    TEXT NOT NULL,
    genotype                JSONB NOT NULL,
    fitness_current         REAL NOT NULL,
    fitness_trajectory      REAL[] NOT NULL,
    fitness_metadata        JSONB,
    parent_ids              UUID[] NOT NULL,
    origin_type             TEXT NOT NULL,
    origin_discovery_event_id UUID,
    generation_born         INTEGER NOT NULL,
    generation_at_archive   INTEGER NOT NULL,
    generations_alive       INTEGER NOT NULL,
    archive_reason          TEXT NOT NULL,
    archived_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    original_created_at     TIMESTAMPTZ NOT NULL
);

CREATE INDEX idx_pia_partition
    ON pattern_individual_archive (tenant_id, failure_mode_profile, archived_at DESC);
```

**Archival is permanent**: No automatic mechanism moves an individual from archive back to the active population. Re-entry only occurs if the same genotype is discovered anew (which creates a fresh `pattern_individual` row linking to the archived ancestor via `fitness_metadata`).

### 9.3 Table: `evolution_generation_log`

One row per generation cycle per partition.

```sql
CREATE TABLE evolution_generation_log (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id               TEXT NOT NULL,
    failure_mode_profile    TEXT NOT NULL,
    generation_number       INTEGER NOT NULL,
    generation_started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    generation_completed_at TIMESTAMPTZ,

    -- Population state at start of generation
    pop_size_before         INTEGER NOT NULL,

    -- Fitness statistics at start of generation (before selection)
    fitness_mean            REAL,
    fitness_max             REAL,
    fitness_min             REAL,
    fitness_std             REAL,

    -- Selection outcome
    individuals_culled      INTEGER NOT NULL DEFAULT 0,
    individuals_survived    INTEGER NOT NULL DEFAULT 0,

    -- Offspring admitted
    individuals_mutation    INTEGER NOT NULL DEFAULT 0,
    individuals_recombination INTEGER NOT NULL DEFAULT 0,
    individuals_discovered  INTEGER NOT NULL DEFAULT 0,

    -- Population state at end of generation
    pop_size_after          INTEGER NOT NULL DEFAULT 0,

    -- Prerequisite status
    prerequisite_status     JSONB NOT NULL,
        -- {"calibration": "OK", "surprise": "OK", "compression": "INSUFFICIENT"}
    generation_status       TEXT NOT NULL
        CHECK (generation_status IN ('COMPLETED', 'SKIPPED', 'DEGRADED')),
        -- COMPLETED: all prerequisites OK, full fitness computed
        -- SKIPPED: >= 2 prerequisites insufficient, cycle not run
        -- DEGRADED: 1 prerequisite insufficient, fitness computed with defaults

    skip_reason             TEXT,   -- NULL unless generation_status='SKIPPED'

    UNIQUE (tenant_id, failure_mode_profile, generation_number)
);

CREATE INDEX idx_egl_partition_gen
    ON evolution_generation_log (tenant_id, failure_mode_profile, generation_number DESC);
```

### 9.4 Table: `evolution_partition_state`

One row per partition. Tracks the current generation counter and dormancy status.

```sql
CREATE TABLE evolution_partition_state (
    tenant_id               TEXT NOT NULL,
    failure_mode_profile    TEXT NOT NULL,
    current_generation      INTEGER NOT NULL DEFAULT 0,
    last_generation_at      TIMESTAMPTZ,
    next_generation_at      TIMESTAMPTZ,
    status                  TEXT NOT NULL DEFAULT 'ACTIVE'
        CHECK (status IN ('ACTIVE', 'DORMANT')),
    dormant_since           TIMESTAMPTZ,
    reactivation_trigger    TEXT,
        -- NULL for ACTIVE; describes what reactivated a DORMANT partition

    PRIMARY KEY (tenant_id, failure_mode_profile)
);
```

### 9.5 Downstream Event: `EvolutionGenerationEvent`

After each completed (non-skipped) generation cycle, the engine emits a summary event for downstream consumers (operator dashboards, alerting):

```python
@dataclass
class EvolutionGenerationEvent:
    tenant_id:              str
    failure_mode_profile:   str
    generation_number:      int
    generation_completed_at: datetime

    # Elite individuals (fitness >= 0.70) at end of generation
    elite_individuals: list[dict]
    # Each dict: {"id": UUID, "genotype": rule, "fitness": float,
    #             "generations_alive": int, "origin_type": str}

    # Fitness improvement: individuals whose fitness increased by >= 0.10
    rising_individuals: list[dict]

    # Newly admitted individuals (mutation + recombination + discovered)
    new_individuals:    list[dict]

    # Culled individuals
    culled_individuals: list[dict]

    # Population-level metrics
    pop_size:           int
    fitness_mean:       float
    fitness_max:        float
    generation_status:  str    # 'COMPLETED' | 'DEGRADED'
```

---

## 10. Concrete Telecom Example

### 10.1 Scenario: DARK_EDGE Pattern Population Evolution for `telco2`

**Context**: The `telco2` tenant has been running Abeyance Memory for 14 weeks. Pattern compression (Mechanism #11) has been producing weekly compression events. The evolution engine has been running for 10 generation cycles on the `(telco2, DARK_EDGE)` partition.

**Starting population (Generation 10)**:

| ID | Genotype | PP | ST | NV | CG | Fitness | Generations Alive | Origin |
|---|---|---|---|---|---|---|---|---|
| I-001 | (H, L, *, H, L) | 0.88 | 0.92 | 0.22 | 0.81 | **0.75** | 9 | DISCOVERED |
| I-002 | (H, L, H, H, L) | 0.79 | 0.84 | 0.31 | 0.63 | **0.68** | 7 | MUTATION of I-001 (M2: * → H in temporal) |
| I-003 | (H, L, *, H, *) | 0.61 | 0.55 | 0.44 | 0.52 | **0.55** | 5 | MUTATION of I-001 (M1: L → * in entity) |
| I-004 | (M, L, *, M, L) | 0.52 | 0.71 | 0.18 | 0.44 | **0.50** | 4 | DISCOVERED |
| I-005 | (H, L, *, *, L) | 0.38 | 0.30 | 0.61 | 0.29 | **0.37** | 3 | RECOMBINATION of I-001 + I-002 |
| I-006 | (M, L, *, H, L) | 0.22 | 0.18 | 0.09 | 0.19 | **0.19** | 2 | MUTATION of I-004 (M3: M → H in oper) |

**Generation 11 execution:**

**Step 1: Fitness recomputation.**

A new batch of snap decisions has arrived since Generation 10. The PP query for I-001 shows that, of 38 labeled decisions matching (H, L, *, H, L) in the last 30 days, 35 were TRUE_POSITIVE (precision = 0.921). The NV query shows 3 DISCOVERY surprise events out of 38 matching decisions (novelty_rate = 0.079, NV = 0.079/0.10 = 0.79). The most recent compression event (day 14 window) shows (H, L, *, H, L) as dominant rule with compression_gain = 0.52. The stability trajectory for I-001 over the last 5 generations: [0.71, 0.73, 0.74, 0.75, ?]. Std=0.016, mean=0.733, CV=0.022, ST=0.978.

```
f(I-001, g=11) = 0.35*0.921 + 0.25*0.978 + 0.15*0.79 + 0.25*0.52
              = 0.322 + 0.245 + 0.119 + 0.130
              = 0.816
```

I-001 is now **elite** (fitness >= 0.70). It has risen from 0.75 to 0.816 — a rising individual.

I-006 with fitness 0.19 is below CULLING_THRESHOLD=0.25 and is not elite. It will be culled.

**Step 2: Selection.**

Survivors: I-001 (0.816), I-002 (0.71 → recomputed), I-003 (0.57 → recomputed), I-004 (0.51 → recomputed), I-005 (0.39 → recomputed). I-006 culled (0.19 < 0.25).

Population after selection: 5 individuals.

**Step 3: Mutation.**

I-001 generates two mutation children (highest fitness):
- M1 applied to (H, L, *, H, L): relax semantic (H → *) → child candidate (*, L, *, H, L), specificity=3.
  - Genotype not in active population or archive. Admitted as I-007.
- M3 applied to (H, L, *, H, L): shift topological (L → M) → (H, M, *, H, L).
  - Genotype not in population. Admitted as I-008.

MUT_BUDGET=5, two admitted. Budget remaining: 3. No further children generated (I-002 would generate next but budget management stops at 5 total).

**Step 4: Recombination.**

Eligible pairs (both fitness >= 0.40, differ in <= 3 dims):
- I-001 (H,L,*,H,L) + I-004 (M,L,*,M,L): differ in sem (H vs M) and oper (H vs M). 2 dimensions differ.
  ```
  Recombination: sem: H≠M → *, topo: L=L → L, temp: *=* → *, oper: H≠M → *, ent: L=L → L
  Child: (*, L, *, *, L)   specificity=2
  ```
  This is a broad rule: "any semantic, low topological, any temporal, any operational, low entity overlap." The child is admitted as I-009 since specificity > 0 and it is not in the population or archive.

RECOMB_BUDGET=3, one admitted.

**Step 5: New pattern ingestion.**

No new `TRUE_DISCOVERY` compression events since last cycle.

**Population at end of Generation 11**: 8 individuals (5 survivors + 2 mutation children + 1 recombination child).

**Step 6: EvolutionGenerationEvent emitted.**

Elite individuals at end of generation: [I-001 (0.816), I-002 (0.71)].
Rising individuals: [I-001 (0.75 → 0.816)].
New individuals: [I-007, I-008, I-009].
Culled: [I-006].

**Operator-facing interpretation:**

The evolution engine surfaces to the NOC dashboard: "The dominant DARK_EDGE pattern `(H, L, *, H, L)` — cross-tracking-area RAN correlations with high semantic and operational affinity — has reached elite fitness (0.816) after 10 weeks of evidence accumulation. It predicts real incidents with 92.1% precision. Two generalization variants `(*, L, *, H, L)` and `(H, M, *, H, L)` have been spawned for exploratory evaluation, as has a broad common-factor child `(*, L, *, *, L)` from recombining the dominant pattern with a secondary DARK_EDGE type. These will be fitness-evaluated in Generation 12 after one week of snap evidence."

**Practical NOC outcome**: The operator can now encode `(H, L, *, H, L)` directly into the CMDB as a standing correlation rule for the `telco2` tenant: "when two RAN fragments share high semantic + high operational scores but low topological + low entity overlap in a DARK_EDGE evaluation, correlate them automatically." This eliminates operator review for 80% of DARK_EDGE snap decisions, reducing alert fatigue while maintaining confidence from the 92.1% precision score.

---

## 11. Integration Points

### 11.1 Inputs Consumed

| Source | Table / Queue | Data Used |
|---|---|---|
| Outcome calibration (phase_4) | `snap_outcome_feedback`, `snap_decision_log` | PP component: precision of matching decisions |
| Surprise engine (phase_3) | `surprise_event` | NV component: DISCOVERY event rate for matching decisions |
| Pattern compression (phase_5) | `compression_discovery_event` | CG component: compression_gain from events containing the genotype; new individual ingestion |
| Snap engine (Tier 1) | `snap_decision_log` | Population queries for PP and NV computation |

### 11.2 Outputs Produced

| Destination | Data |
|---|---|
| `pattern_individual` | Active population with fitness scores and trajectories |
| `pattern_individual_archive` | Culled individuals with full history |
| `evolution_generation_log` | Per-cycle audit log |
| `evolution_partition_state` | Current generation counter and dormancy status |
| Discovery event queue | `EvolutionGenerationEvent` for operator dashboards and alerting |

### 11.3 What This Mechanism Does NOT Do

- Does not modify snap scores, snap thresholds, or weight profiles (those are Tier 1 / phase_4 concerns).
- Does not invoke the LLM or generate embeddings.
- Does not emit new `CompressionDiscoveryEvent` records (it consumes them; it does not produce them).
- Does not modify `surprise_event` records.
- Does not replace operator review — elite patterns are surfaced to operators for manual encoding into CMDB; they are not automatically applied.

---

## 12. Configuration Parameters Summary

| Parameter | Default | Scope | Tunable |
|---|---|---|---|
| `POP_CAP` | 50 per partition | Global | Yes |
| `POP_FLOOR` | 3 | Global | Yes |
| `ELITE_THRESHOLD` | 0.70 | Global | Yes |
| `CULLING_THRESHOLD` | 0.25 | Global | Yes |
| `RECOMB_MIN_FITNESS` | 0.40 | Global | Yes |
| `RECOMB_MAX_DIFFER` | 3 | Global | No (architectural) |
| `RECOMB_MAX_PAIRS` | 20 per partition per cycle | Global | Yes |
| `RECOMB_BUDGET_PER_GEN` | 3 per partition per cycle | Global | Yes |
| `MUT_CHILDREN_PER_INDIVIDUAL` | 2 | Global | Yes |
| `MUT_BUDGET_PER_GEN` | 5 per partition per cycle | Global | Yes |
| `GENERATION_INTERVAL_DAYS` | 7 | Global | Yes (per-tenant override) |
| `PP_WINDOW_DAYS` | 30 | Global | Yes |
| `PP_MIN_DECISIONS` | 5 | Global | Yes |
| `PP_MIN_LABELED` | 3 | Global | Yes |
| `PP_DEFAULT` | 0.40 | Global | Yes |
| `NV_WINDOW_DAYS` | 30 | Global | Yes |
| `NV_MIN_DECISIONS` | 5 | Global | Yes |
| `NV_DEFAULT` | 0.30 | Global | Yes |
| `NV_SATURATION` | 0.10 | Global | Yes |
| `CG_WINDOW_DAYS` | 30 | Global | Yes |
| `CG_DEFAULT` | 0.20 | Global | Yes |
| `ST_WINDOW_GENERATIONS` | 5 | Global | Yes |
| `ST_DEFAULT` | 0.50 | Global | Yes |
| `FITNESS_WEIGHTS` | pp=0.35, st=0.25, nv=0.15, cg=0.25 | Global | Yes (sum must = 1.0) |

---

## 13. Invariants

| ID | Statement | Enforcement |
|---|---|---|
| INV-EV1 | `f(I) ∈ [0.0, 1.0]` for all individuals | Each component in [0.0, 1.0]; weights sum to 1.0; reweighting for degraded fitness preserves normalization |
| INV-EV2 | `|Ω| ≤ POP_CAP` at end of every generation cycle | Selection runs before mutation/recombination admission; admission checks remaining slots |
| INV-EV3 | Archived individuals are never deleted | All culls write to `pattern_individual_archive`; no DELETE operations on either table |
| INV-EV4 | No individual with genotype already in active population is admitted | Genotype uniqueness check before admission in mutation, recombination, and discovery ingestion |
| INV-EV5 | No individual with genotype in archive is admitted via mutation or recombination | Archive genotype check in admission gate |
| INV-EV6 | Recombination child specificity >= 1 | Discard child if `specificity == 0` before admission |
| INV-EV7 | All four fitness components computed before fitness score written | Fitness computed atomically within generation cycle; no partial writes |
| INV-EV8 | Generation cycle skipped (not degraded) if >= 2 prerequisites INSUFFICIENT | Prerequisite check in Section 8.1; generation_status='SKIPPED' if condition met |
| INV-EV9 | Tenant isolation in all queries | `tenant_id` in WHERE clause for all queries; leading column in all primary keys and indexes |
| INV-EV10 | `fitness_trajectory` is append-only per individual | Only append operations; no in-place modification of historical fitness values |
| INV-EV11 | Elite individuals (fitness >= ELITE_THRESHOLD) are never culled in the same generation they achieved elite status | Elite check in selection algorithm precedes culling threshold check |
