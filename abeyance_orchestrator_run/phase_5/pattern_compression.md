# Pattern Compression Discovery -- Discovery Mechanism #11

**Task**: D11.1 -- Pattern Compression Discovery
**Version**: 3.0
**Date**: 2026-03-16
**Status**: Specification
**Tier**: 4 (Advanced -- requires Tiers 1-3 stable)
**Dependencies**:
- Snap scoring (phase_1/snap_scoring.md): provides per-dimension scores and snap decisions
- Surprise engine (phase_3/surprise_engine.md): provides `SurpriseEvent` records with provenance

---

## 1. Problem Statement

Tiers 1-3 of the discovery pipeline operate on individual snap pairs and surprise events. They detect that a specific pair of fragments is unusual, but they do not ask whether a *set* of surprising snap patterns can be collapsed into a single, simpler rule.

The central observation: if ten DARK_EDGE fragments across an operator's network all trigger surprise events because they share high semantic similarity and high operational similarity with low topological similarity and low entity overlap, that is not ten isolated anomalies. It is one rule:

```
DARK_EDGE patterns where (S_sem > 0.75 AND S_oper > 0.70 AND S_topo < 0.25 AND S_ent < 0.15)
```

**Pattern compression discovery** collapses a population of snap patterns into a minimal grammar of rules. The compression gain -- how much shorter the rule representation is than the raw pattern list -- is the discovery signal. High compression gain means a latent, general structure has been found. Low compression gain means the patterns are noise.

---

## 2. Definitions

### 2.1 Snap Pattern

A **snap pattern** `π` is the per-dimension score signature of a snap decision record, discretized into ordinal bands:

```
π = (band_sem, band_topo, band_temp, band_oper, band_ent, failure_mode)
```

Each per-dimension score `S_d ∈ [0.0, 1.0]` is mapped to an ordinal band:

| Band label | Score range | Meaning |
|---|---|---|
| `L` | [0.00, 0.33) | Low similarity |
| `M` | [0.33, 0.67) | Medium similarity |
| `H` | [0.67, 1.00] | High similarity |
| `X` | NULL | Dimension unavailable (mask=FALSE) |

**Example**: A DARK_EDGE snap decision with `S_sem=0.82, S_topo=0.12, S_temp=0.71, S_oper=0.78, S_ent=0.08` encodes as:

```
π = (H, L, H, H, L, DARK_EDGE)
```

**Rationale for 3-band discretization**: Per-dimension scores from the snap engine are noisy estimates. A 3-band discretization captures the structural shape of a scoring pattern without overfitting to floating-point variation. The `X` band preserves mask information, allowing compression to distinguish patterns where a dimension was absent from patterns where it was zero.

### 2.2 Pattern Population

A **pattern population** `Π` for a given `(tenant_id, failure_mode_profile, time_window)` is the multiset of all snap patterns recorded in that window:

```
Π = {π_1, π_2, ..., π_N}
```

Each element is a discretized snap pattern as defined in 2.1. The `failure_mode_profile` is always fixed within a population (cross-profile aggregation would conflate structurally different scoring regimes).

### 2.3 Compression Rule

A **compression rule** `ρ` is a partial assignment over the five dimension bands plus failure mode:

```
ρ = (cond_sem, cond_topo, cond_temp, cond_oper, cond_ent, failure_mode)
```

Where each `cond_d` is one of:
- A specific band value: `L`, `M`, `H`, or `X`
- A wildcard `*` (matches any band value including `X`)

A rule `ρ` **matches** a pattern `π` when every non-wildcard condition in `ρ` matches the corresponding band in `π`.

**Example rule**:

```
ρ = (H, L, *, H, L, DARK_EDGE)
```

This rule matches any DARK_EDGE pattern with high semantic similarity, low topological similarity, any temporal similarity, high operational similarity, and low entity overlap.

### 2.4 Rule Coverage

The **coverage** of a rule `ρ` over population `Π` is the count of patterns that `ρ` matches:

```
coverage(ρ, Π) = |{π ∈ Π : ρ matches π}|
```

### 2.5 Rule Specificity

The **specificity** of a rule `ρ` is the number of non-wildcard conditions (excluding `failure_mode`, which is always fixed):

```
specificity(ρ) = |{d ∈ {sem, topo, temp, oper, ent} : cond_d ≠ *}|
```

Specificity ranges from 0 (all wildcards, matches everything) to 5 (fully specified pattern, matches only one exact signature).

---

## 3. Pattern Grammar

### 3.1 Grammar Definition

The pattern language `L` is a context-free grammar over 5 dimension slots and 1 failure-mode slot:

```
Pattern  ::= Rule+
Rule     ::= (Cond_sem, Cond_topo, Cond_temp, Cond_oper, Cond_ent, FailureMode)
Cond_d   ::= 'L' | 'M' | 'H' | 'X' | '*'
FailureMode ::= 'DARK_EDGE' | 'DARK_NODE' | 'IDENTITY_MUTATION' | 'PHANTOM_CI' | 'DARK_ATTRIBUTE'
```

A **description** `D` of a population `Π` is a set of rules `{ρ_1, ..., ρ_k}` such that every pattern in `Π` is matched by at least one rule in `D`. The description is an exact cover if no pattern is matched by more than one rule (a covering set otherwise; for this specification, covering sets are permitted and preferred for robustness).

### 3.2 Description Length

The **description length** `DL(D)` of a description `D` is the total information content required to specify it, measured in bits:

Each rule requires:
- 5 condition slots, each with 5 possible values {L, M, H, X, *}: `5 × log2(5) = 5 × 2.322 = 11.61 bits` per rule
- The failure mode is fixed for the population, so it costs 0 bits within a population

```
DL(D) = |D| × 11.61 bits
```

**Rationale**: This is a minimum description length (MDL) framing. A description with fewer rules is a shorter description of the same data. When the rule set is shorter than the raw pattern enumeration, structure has been found.

The **baseline description length** `DL_baseline(Π)` is the cost of describing the population as a list of distinct patterns with their counts:

```
distinct_patterns = |{π : π ∈ Π}|     (number of unique patterns)
DL_baseline(Π) = distinct_patterns × 11.61 bits
```

This is the cost of the null hypothesis: "no structure, every pattern is its own rule."

---

## 4. Compression Algorithm

### 4.1 Overview

The compression algorithm is a **greedy set cover with MDL pruning**. It produces a minimal set of rules that covers the pattern population, iteratively selecting the rule that achieves the best gain at each step.

This is the "SEQUITUR-style compression applied to categorical snap signatures" approach: find the most frequent generalizations first, commit to them, then compress the residual.

### 4.2 Input and Output

**Input**:
- `Π`: pattern population (multiset of snap patterns) for a fixed `(tenant_id, failure_mode_profile, time_window)`
- `MIN_COVERAGE`: minimum number of patterns a rule must match to be included (default: 3)
- `MAX_RULES`: maximum number of rules in the output description (default: 20)

**Output**:
- `D`: set of compression rules
- `compression_gain`: scalar discovery signal (defined in Section 5)
- `uncovered_count`: number of patterns in `Π` not matched by any rule in `D`

### 4.3 Algorithm

```
FUNCTION compress_patterns(Π, MIN_COVERAGE=3, MAX_RULES=20):

    # Step 1: Discretize all snap patterns into the 5-band signature
    Π_disc = [discretize(π) for π in Π]

    # Step 2: Count pattern frequencies
    freq = frequency_count(Π_disc)         # map: pattern → count
    distinct_count = len(freq)

    # Step 3: Generate candidate rules by generalization
    # For each distinct pattern, generate all 2^5 = 32 partial masks
    # (replacing each subset of conditions with wildcards)
    candidates = {}    # rule → coverage_count
    for pattern, count in freq.items():
        for mask in all_bitmasks(5):       # 32 masks: 00000 to 11111
            rule = apply_mask(pattern, mask)    # replace masked dims with '*'
            candidates[rule] = candidates.get(rule, 0) + count

    # Step 4: Filter candidates by minimum coverage
    viable = {r: c for r, c in candidates.items() if c >= MIN_COVERAGE}

    # Step 5: Greedy MDL-guided rule selection
    selected_rules = []
    remaining = dict(freq)                 # patterns not yet covered
    covered_count = 0

    while remaining and len(selected_rules) < MAX_RULES:

        # Score each viable rule on remaining patterns
        best_rule = None
        best_score = -inf

        for rule in viable:
            # Coverage of this rule on remaining patterns
            rule_coverage = sum(cnt for pat, cnt in remaining.items()
                                if rule_matches(rule, pat))
            if rule_coverage == 0:
                continue

            # MDL score: patterns covered per bit of rule description
            # Prefer high-coverage, low-specificity rules
            score = rule_coverage / (specificity(rule) + 1)
            # +1 prevents division by zero for the all-wildcard rule
            # and penalizes specificity (higher specificity = more bits = lower score)

            if score > best_score:
                best_score = score
                best_rule = rule

        if best_rule is None:
            break    # no more rules can cover remaining patterns

        selected_rules.append(best_rule)
        covered_count += sum(cnt for pat, cnt in remaining.items()
                              if rule_matches(best_rule, pat))

        # Remove covered patterns from remaining
        remaining = {pat: cnt for pat, cnt in remaining.items()
                     if not rule_matches(best_rule, pat)}

    # Step 6: Compute compression gain
    cg = compression_gain(distinct_count, selected_rules, len(Π_disc))

    uncovered = sum(remaining.values())

    RETURN selected_rules, cg, uncovered
```

### 4.4 Generalization Step Detail

The `apply_mask` function replaces conditions at masked dimension positions with wildcards:

```
FUNCTION apply_mask(pattern, mask):
    # mask is a 5-bit integer; bit i=1 means "keep condition i",
    # bit i=0 means "replace with wildcard"
    rule = list(pattern)     # [cond_sem, cond_topo, cond_temp, cond_oper, cond_ent]
    for i in range(5):
        if not (mask >> i) & 1:
            rule[i] = '*'
    return tuple(rule)
```

The mask `11111` (binary) produces the original pattern with no wildcards (maximally specific). The mask `00000` produces the all-wildcard rule `(*, *, *, *, *)` (matches everything).

Total candidate rules generated per distinct pattern: 32.
Total candidate rules generated across a population with `K` distinct patterns: at most `K × 32`, deduplicated. In practice the deduplication reduces this substantially because many patterns generalize to the same rule.

### 4.5 Bounded Computation

**Time complexity**:

| Step | Cost | Note |
|---|---|---|
| Discretization | O(N) | One pass over N patterns |
| Frequency count | O(N) | Hash map accumulation |
| Candidate generation | O(K × 32) = O(K) | K = distinct patterns, K ≤ N |
| Candidate filtering | O(K × 32) | One filter pass |
| Greedy selection (outer loop) | O(MAX_RULES) iterations | Bounded by MAX_RULES=20 |
| Greedy scoring (inner loop) | O(viable × K) | Per outer iteration |
| Total greedy | O(MAX_RULES × viable × K) | See bound below |

**Viable rule bound**: Each viable rule covers at least `MIN_COVERAGE` patterns. The maximum number of viable rules is bounded by `K × 32 / MIN_COVERAGE` in the worst case. With `K ≤ 3^5 = 243` (at most 243 distinct 5-band patterns for a fixed failure mode), `MIN_COVERAGE=3`, and 32 masks: viable ≤ `243 × 32 / 3 = 2592`.

**Absolute worst-case**: `MAX_RULES × viable × K = 20 × 2592 × 243 = 12,599,280` operations. Each operation is a hash lookup and integer comparison. At 100M operations/second this is 126ms.

**Practical case**: Real populations have far fewer distinct patterns. A tenant with 500 snap events and typical 3-band clustering produces K ≤ 30-50 distinct patterns. Actual runtime: < 5ms.

**Hard cap enforcement**: `MAX_RULES=20` and `MIN_COVERAGE=3` are enforced as preconditions. If the population has fewer than `MIN_COVERAGE × 2 = 6` patterns total, the algorithm returns immediately with no rules and `compression_gain = 0.0`.

```
if len(Π_disc) < MIN_COVERAGE * 2:
    return [], 0.0, len(Π_disc)
```

**Memory**: The candidates dictionary holds at most `K × 32` entries. With K ≤ 243 and each entry being a 5-tuple plus count: < 100 KB. The pattern population itself is held in memory only during compression (not persisted in raw form); the population is loaded from `snap_decision_log` via a bounded query.

---

## 5. Compression Gain Metric

### 5.1 Quantitative Definition

Let:
- `K` = number of distinct patterns in `Π` before compression (baseline description length in rules)
- `R` = number of rules in the selected description `D` after compression (compressed description length in rules)
- `N` = total pattern count (size of the multiset `Π`)
- `C` = count of patterns covered by `D` (patterns explained by the compressed rules)

The **coverage ratio** is:

```
coverage_ratio = C / N
```

The **compression ratio** is:

```
compression_ratio = (K - R) / K          for K > 0, else 0.0
```

The **compression gain** (scalar discovery signal) combines both:

```
compression_gain = compression_ratio × coverage_ratio
                 = ((K - R) / K) × (C / N)
```

**Range**: `[0.0, 1.0]`.

- `compression_gain = 0.0`: No compression achieved. Either `K = R` (no rules collapsed), `K = 0` (empty population), or `C = 0` (no patterns covered).
- `compression_gain = 1.0`: Perfect compression. All patterns collapsed into one rule (`R = 1, K > 1`) and that rule covers all patterns (`C = N`).
- `compression_gain = 0.5`: Moderate compression. Either half the patterns collapsed with full coverage, or full collapse with half coverage.

### 5.2 Interpretation

The compression gain measures two things simultaneously:

1. **Structural regularity** (`compression_ratio`): How much did the rule count shrink? High ratio means many distinct patterns generalize to few rules -- the population has latent structure.

2. **Completeness** (`coverage_ratio`): How much of the population does the compressed description explain? Low coverage means many patterns are noise or outliers that resist generalization.

A discovery requires both: a structurally regular pattern that explains most of the population. Pure noise produces low compression ratio (all patterns are unique, rules don't generalize). Pure signal produces high compression ratio AND high coverage.

### 5.3 Worked Example (Telecom)

**Scenario**: Tenant `telco2`, failure mode `DARK_EDGE`, time window = last 7 days.

**Population** (N=45 snap patterns after discretization):

```
Pattern               Count
(H, L, H, H, L)        18    ← dominant pattern
(H, L, M, H, L)         9    ← similar to dominant
(H, L, L, H, L)         6    ← similar to dominant
(M, L, H, M, L)         5    ← weaker variant
(L, H, L, L, H)         4    ← opposite: topological dominant
(M, M, L, L, M)         3    ← noise-like
```

**Distinct patterns K = 6**.

**Greedy compression** (MIN_COVERAGE=3):

Iteration 1: Evaluate candidate rules. The rule `(H, L, *, H, L)` covers patterns 1+2+3 = 18+9+6 = 33 patterns. Its score = `33 / (4 + 1) = 6.6`. This wins. Select it.

Remaining after covering patterns 1-3: patterns 4, 5, 6 (12 patterns total).

Iteration 2: Rule `(M, L, H, M, L)` covers 5 patterns with specificity 4: score = `5/5 = 1.0`. Rule `(L, H, L, L, H)` covers 4 patterns with specificity 4: score = `4/5 = 0.8`. Select `(M, L, H, M, L)`.

Remaining: patterns 5, 6 (7 patterns).

Iteration 3: `(L, H, L, L, H)` covers 4 patterns: score = `4/5 = 0.8`. `(M, M, L, L, M)` covers 3 patterns: score = `3/4 = 0.75`. Select `(L, H, L, L, H)`.

Remaining: pattern 6 (3 patterns). Coverage = 3 = MIN_COVERAGE. Rule `(M, M, L, L, M)` covers 3: score = `3/4 = 0.75`. Select it.

Remaining: empty.

**Result**: D = {`(H, L, *, H, L)`, `(M, L, H, M, L)`, `(L, H, L, L, H)`, `(M, M, L, L, M)`}

R = 4 rules, C = 45 patterns covered, N = 45, K = 6.

```
compression_ratio = (6 - 4) / 6 = 0.333
coverage_ratio    = 45 / 45    = 1.000
compression_gain  = 0.333 × 1.000 = 0.333
```

**Interpretation**: The dominant rule `(H, L, *, H, L)` describes 73% of all DARK_EDGE events in the past week. It generalizes across temporal similarity levels -- the temporal dimension does not discriminate this pattern. The structural finding: cross-tracking-area alarm correlations (low topological, high semantic and operational) are the dominant DARK_EDGE failure mode for this tenant, regardless of when they occur.

---

## 6. Discovery Signal: When Compression Gain Triggers Discovery

### 6.1 Primary Threshold

A compression gain constitutes a **discovery** when:

```
compression_gain >= DISCOVERY_THRESHOLD     (default: 0.40)
AND coverage_ratio >= MIN_COVERAGE_RATIO    (default: 0.50)
AND R >= 1                                  (at least one rule found)
AND N >= MIN_POPULATION_SIZE                (default: 20)
```

All four conditions must hold simultaneously.

**Rationale for each condition**:

- `compression_gain >= 0.40`: A gain of 0.40 means the description is at least 40% more efficient than the baseline (or the population has high structural regularity with high coverage). The threshold of 0.40 is chosen to exclude populations where only 1-2 patterns happen to merge (which gives compression_gain ≈ 0.15-0.25 for a typical K=6 population) while including cases where a genuinely dominant rule structure has emerged.

- `coverage_ratio >= 0.50`: At least half the patterns must be explained by the compressed rules. This prevents a spurious "discovery" where 3 patterns out of 100 compress nicely but 97 remain unexplained.

- `R >= 1`: Trivial check -- empty rule sets cannot be discoveries.

- `N >= MIN_POPULATION_SIZE = 20`: Compression gain on very small populations (N < 20) is numerically unreliable. With 5 or 10 patterns, a single coincidence can produce high apparent compression.

### 6.2 Dominant Rule Condition (Optional Refinement)

A discovery is classified as **DOMINANT** (a stronger signal, higher operator priority) when the single highest-coverage rule `ρ*` in `D` satisfies:

```
coverage(ρ*, Π) / N >= DOMINANT_COVERAGE_THRESHOLD    (default: 0.50)
AND specificity(ρ*) <= 3
```

This identifies cases where more than half the population collapses into a single rule with at most 3 constrained dimensions -- the simplest and most actionable form of discovery.

### 6.3 Novelty Condition

A discovery is classified as **NOVEL** when the dominant rule `ρ*` has not appeared in the discovery log for this `(tenant_id, failure_mode_profile)` within the past `NOVELTY_WINDOW_DAYS` (default: 30 days):

```
novel = (ρ* not in recent_discovery_rules(tenant_id, failure_mode_profile, 30 days))
```

A non-novel discovery (same rule found again within the window) is downgraded to `RECURRING_PATTERN` classification, which is tracked for stability monitoring but does not generate a new discovery event.

### 6.4 Discovery Event Record

```python
@dataclass
class CompressionDiscoveryEvent:
    # Identity
    event_id: UUID
    tenant_id: str
    failure_mode_profile: str
    timestamp: datetime                    # UTC

    # Population
    time_window_start: datetime
    time_window_end: datetime
    population_size: int                   # N
    distinct_pattern_count: int            # K

    # Compression result
    rules: list[CompressionRule]           # D = selected rules
    rule_count: int                        # R
    covered_count: int                     # C
    uncovered_count: int                   # N - C

    # Metrics
    compression_ratio: float               # (K - R) / K
    coverage_ratio: float                  # C / N
    compression_gain: float                # compression_ratio × coverage_ratio

    # Dominant rule
    dominant_rule: Optional[CompressionRule]      # highest-coverage rule
    dominant_rule_coverage: int                   # count of patterns it matches
    dominant_rule_coverage_fraction: float        # dominant_rule_coverage / N

    # Classification
    discovery_class: str                   # 'DOMINANT' | 'STANDARD' | 'RECURRING_PATTERN'
    is_novel: bool

    # Provenance
    source_snap_decision_ids: list[UUID]   # snap decisions in the population window
    # Not ALL decisions -- bounded to at most 1000 representatives per event
```

---

## 7. Evaluation Schedule and Population Construction

### 7.1 Trigger

Pattern compression runs as a **periodic batch job**, not in the hot snap evaluation path. It is decoupled from the per-snap surprise engine (Tier 1).

**Schedule**: Every `COMPRESSION_WINDOW_HOURS` (default: 24 hours) per `(tenant_id, failure_mode_profile)` partition, or on-demand via operator request.

**Rationale**: Compression gain is meaningful only over populations of sufficient size (N >= 20). Running per-snap-event would produce empty or unreliable results for most evaluations. A 24-hour window accumulates enough events for statistically reliable compression on typical telecom deployments.

### 7.2 Population Query

The pattern population is constructed from snap decisions in the evaluation window:

```sql
SELECT
    score_semantic, score_topological, score_temporal,
    score_operational, score_entity_overlap,
    mask_semantic_available, mask_topological_available,
    mask_operational_available,
    id
FROM snap_decision_log
WHERE
    tenant_id = :tenant_id
    AND failure_mode_profile = :failure_mode_profile
    AND timestamp >= :window_start
    AND timestamp < :window_end
    AND decision IN ('SNAP', 'NEAR_MISS')  -- only meaningful snap events
LIMIT 5000;    -- hard cap for bounded computation
```

The `LIMIT 5000` cap prevents unbounded memory consumption for tenants with very high snap throughput. For most telecom tenants producing 10-200 SNAP/NEAR_MISS events per day, this cap is never reached.

### 7.3 Minimum Population Guard

If the query returns fewer than `MIN_POPULATION_SIZE = 20` rows for a partition, the job logs an `INSUFFICIENT_POPULATION` notice (not an error) and skips compression for that partition in this cycle. No discovery event is emitted.

---

## 8. Storage Schema

### 8.1 Compression Discovery Event Table

```sql
CREATE TABLE compression_discovery_event (
    event_id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id              TEXT NOT NULL,
    failure_mode_profile   TEXT NOT NULL,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Population window
    time_window_start      TIMESTAMPTZ NOT NULL,
    time_window_end        TIMESTAMPTZ NOT NULL,
    population_size        INTEGER NOT NULL,
    distinct_pattern_count INTEGER NOT NULL,

    -- Compression result
    rules                  JSONB NOT NULL,   -- array of rule objects
    rule_count             INTEGER NOT NULL,
    covered_count          INTEGER NOT NULL,
    uncovered_count        INTEGER NOT NULL,

    -- Metrics
    compression_ratio      REAL NOT NULL,
    coverage_ratio         REAL NOT NULL,
    compression_gain       REAL NOT NULL,

    -- Dominant rule
    dominant_rule          JSONB,            -- null if no dominant rule
    dominant_coverage_fraction REAL,

    -- Classification
    discovery_class        TEXT NOT NULL
        CHECK (discovery_class IN ('DOMINANT', 'STANDARD', 'RECURRING_PATTERN')),
    is_novel               BOOLEAN NOT NULL,

    -- Review lifecycle
    reviewed               BOOLEAN NOT NULL DEFAULT FALSE,
    reviewed_at            TIMESTAMPTZ,
    review_verdict         TEXT
        CHECK (review_verdict IS NULL OR review_verdict IN
               ('TRUE_DISCOVERY', 'FALSE_ALARM', 'KNOWN_PATTERN', 'DEFERRED')),

    CONSTRAINT chk_gain_range CHECK (compression_gain >= 0.0 AND compression_gain <= 1.0),
    CONSTRAINT chk_cov_range  CHECK (coverage_ratio >= 0.0 AND coverage_ratio <= 1.0)
);

CREATE INDEX idx_cde_tenant_time
    ON compression_discovery_event (tenant_id, created_at DESC);

CREATE INDEX idx_cde_unreviewed
    ON compression_discovery_event (tenant_id, failure_mode_profile, created_at)
    WHERE reviewed = FALSE AND discovery_class != 'RECURRING_PATTERN';
```

### 8.2 Rule Storage Format (JSONB)

Each rule in the `rules` array is stored as:

```json
{
  "cond_sem":  "H",
  "cond_topo": "L",
  "cond_temp": "*",
  "cond_oper": "H",
  "cond_ent":  "L",
  "coverage":  33,
  "coverage_fraction": 0.733,
  "specificity": 4
}
```

The `dominant_rule` field is a single rule object (the highest-coverage rule) or `null`.

---

## 9. Concrete Telecom Example

### 9.1 Scenario: Cross-Tracking-Area RAN Correlation Discovery

**Tenant**: `telco2`
**Failure mode**: `DARK_EDGE`
**Evaluation window**: 2026-03-09 to 2026-03-16 (7 days)

**Background**: The snap engine has been scoring pairs of alarm fragments from an LTE radio access network. Over the past week, numerous SNAP and NEAR_MISS decisions have accumulated. Operators have not examined them individually.

**Population query result**: 156 snap decisions (N=156 after filtering to SNAP/NEAR_MISS).

**Discretization**: Each snap decision's per-dimension scores are mapped to bands. The resulting pattern multiset (showing top patterns):

```
Pattern (sem, topo, temp, oper, ent)    Count    Source
(H, L, H, H, L)                          61      S1_SETUP + X2_HANDOVER pairs
(H, L, M, H, L)                          38      S1_SETUP + S1_PATH_SWITCH pairs
(H, L, L, H, L)                          19      same pair types, off-peak hours
(M, H, L, M, H)                          14      intra-RNC pairs (expected)
(L, H, H, L, H)                           8      timing sync pairs (expected)
(M, L, X, M, L)                           7      LLM-unavailable scoring (mask)
(H, M, H, H, M)                           5      hybrid pairs
(L, L, L, L, L)                           4      near-zero-score near-misses
```

K = 8 distinct patterns.

**Compression** (MIN_COVERAGE=3, MAX_RULES=20):

**Iteration 1**: Best rule for remaining population (N=156):

Candidate `(H, L, *, H, L)` covers patterns 1+2+3 = 61+38+19 = 118 patterns.
Score = 118 / (4+1) = 23.6. **Selected.**

Remaining: 38 patterns (patterns 4-8).

**Iteration 2**: Best rule for remaining 38:

`(M, H, L, M, H)` covers 14, score = 14/5 = 2.8.
`(L, H, H, L, H)` covers 8, score = 8/4 = 2.0.
`(M, H, *, M, H)` covers 14, score = 14/3 = 4.7. **Selected** (relaxes temporal condition).

Remaining: 24 patterns.

**Iteration 3**: `(L, H, *, L, H)` covers 8, score = 8/3 = 2.67. **Selected.**

Remaining: 16 patterns.

**Iteration 4**: `(M, L, X, M, L)` covers 7, score = 7/4 = 1.75. **Selected.**

Remaining: 9 patterns.

**Iteration 5**: `(H, M, H, H, M)` covers 5, score = 5/4 = 1.25. **Selected.**

Remaining: 4 patterns.

`(L, L, L, L, L)` covers 4, but coverage = 4 >= MIN_COVERAGE=3. Score = 4/5 = 0.8. **Selected.**

Remaining: empty.

**Result**: D = 6 rules. R=6, C=156, N=156, K=8.

```
compression_ratio = (8 - 6) / 8 = 0.250
coverage_ratio    = 156 / 156   = 1.000
compression_gain  = 0.250 × 1.000 = 0.250
```

This does NOT trigger discovery (0.250 < DISCOVERY_THRESHOLD=0.40).

**Now, day 14** (two-week window): The same cross-tracking-area pattern has continued to dominate. With 340 snap decisions over 14 days:

```
Pattern (sem, topo, temp, oper, ent)    Count
(H, L, H, H, L)                         142
(H, L, M, H, L)                          89
(H, L, L, H, L)                          43
-- all other patterns --                  66
```

K = 9 distinct patterns (one new noise pattern appeared). Dominant rule `(H, L, *, H, L)` now covers 274/340 = 80.6% of the population.

```
compression: K=9, R=5 (dominant rule absorbs 80% of population)
compression_ratio = (9 - 5) / 9 = 0.444
coverage_ratio    = 340 / 340   = 1.000
compression_gain  = 0.444 × 1.000 = 0.444
```

`0.444 >= 0.40`: **Discovery triggered.**

Dominant rule check: `(H, L, *, H, L)` covers 274/340 = 80.6% >= 50%, specificity=4 <= 3? No, specificity=4 > 3.

Relaxed version: `(H, L, *, H, *)` covers 274+0 patterns (entity overlap is always L in dominant patterns): same count. Specificity=3. **Dominant classification applies.**

**Discovery event emitted**:
- `discovery_class = 'DOMINANT'`
- `is_novel = True` (first occurrence in this tenant)
- `dominant_rule = (H, L, *, H, L)` -- "High semantic, Low topological, Any temporal, High operational, Low entity overlap"
- `compression_gain = 0.444`
- Human-readable interpretation: "Cross-area RAN alarm pairs with high semantic and operational correlation but low topological connection are the dominant DARK_EDGE failure mode for this tenant. The temporal dimension does not discriminate -- this pattern occurs across all time-of-day and day-of-week bands."

**Operator action**: Investigate why geographically distant RAN elements (low topology) share vendor software state (high operational) and alarm semantics (high semantic) without sharing monitoring entity context (low entity overlap). Root cause hypothesis: a common software version deployed across multiple tracking areas is producing correlated S1 and X2 failures independently. The CMDB lacks a cross-tracking-area dependency edge -- this is the dark edge.

---

## 10. Integration with Upstream Tiers

### 10.1 Relationship to Snap Scoring (Tier 1)

Pattern compression consumes `SnapDecisionRecord` rows from `snap_decision_log` via the bounded query in Section 7.2. It reads the per-dimension scores and mask availability flags. It does not write to or modify snap decisions.

The five scoring dimensions from snap scoring (semantic, topological, temporal, operational, entity overlap) map directly to the five compression rule conditions. The mask state (`X` band) is preserved through compression: a rule with `cond_temp = 'X'` describes a population where the temporal embedding was unavailable for the majority of snap decisions.

### 10.2 Relationship to Surprise Engine (Tier 1)

The surprise engine detects surprising individual snap pairs. Pattern compression detects surprising population-level structure. These are complementary:

- Surprise engine: "This specific pair (eNB-4412, eNB-7803) produced an unusual score."
- Pattern compression: "Over the past two weeks, 80% of DARK_EDGE snap events follow the same structural rule."

Pattern compression can be run as a follow-up to clusters of `DISCOVERY`-type surprise events: if multiple surprise events from the same failure mode partition accumulate over a time window, the compression job is triggered on-demand for that partition. This on-demand trigger is an enhancement; the default schedule (Section 7.1) is sufficient for baseline operation.

### 10.3 Output to Tier 2+

`CompressionDiscoveryEvent` records with `is_novel = True` and `discovery_class` in `{'DOMINANT', 'STANDARD'}` are placed on the discovery evaluation queue for Tier 2+ processing. The dominant rule and its coverage fraction are the primary inputs for downstream hypothesis generation.

---

## 11. Configuration Parameters Summary

| Parameter | Default | Scope | Tunable |
|---|---|---|---|
| `BAND_LOW_THRESHOLD` | 0.33 | Global | Yes |
| `BAND_HIGH_THRESHOLD` | 0.67 | Global | Yes |
| `MIN_COVERAGE` | 3 | Global | Yes |
| `MAX_RULES` | 20 | Global | No (hard bound) |
| `DISCOVERY_THRESHOLD` | 0.40 | Global | Yes (per-tenant override) |
| `MIN_COVERAGE_RATIO` | 0.50 | Global | Yes |
| `MIN_POPULATION_SIZE` | 20 | Global | Yes |
| `DOMINANT_COVERAGE_THRESHOLD` | 0.50 | Global | Yes |
| `DOMINANT_SPECIFICITY_MAX` | 3 | Global | Yes |
| `NOVELTY_WINDOW_DAYS` | 30 | Global | Yes (per-tenant override) |
| `COMPRESSION_WINDOW_HOURS` | 24 | Per-tenant | Yes |
| `POPULATION_QUERY_LIMIT` | 5000 | Global | No (hard bound) |

---

## 12. Invariants

| ID | Statement | Enforcement |
|---|---|---|
| INV-C1 | compression_gain in [0.0, 1.0] | Both component ratios are in [0.0, 1.0] by construction; product is in [0.0, 1.0] |
| INV-C2 | Every rule covers at least MIN_COVERAGE patterns | Candidate filter in Step 4 of algorithm |
| INV-C3 | Rule count R <= MAX_RULES | Outer loop bound in greedy selection |
| INV-C4 | Population capped at 5000 patterns | LIMIT in population query |
| INV-C5 | No discovery emitted for N < MIN_POPULATION_SIZE | Population guard in Section 7.3 |
| INV-C6 | Compression reads snap decisions; never writes them | No write path to snap_decision_log |
| INV-C7 | Each rule condition is in {L, M, H, X, *} | Discretization maps to fixed vocabulary; mask=FALSE → X |
| INV-C8 | Failure mode fixed within a population | Population query includes failure_mode_profile in WHERE clause |
| INV-C9 | Tenant isolation in all queries | tenant_id in all WHERE clauses and primary keys |
