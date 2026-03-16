# Expectation Violation Detection -- Discovery Mechanism #9

**Task**: T5.2 -- Expectation Violation Detection
**Version**: 3.0
**Date**: 2026-03-16
**Status**: Specification
**Tier**: 3 (Reasoning -- depends on Tier 1 + Tier 2 infrastructure)
**Depends on**:
- Tier 1: Surprise Metrics Engine (D1.1) -- surprise scoring formula, Laplace smoothing convention
- Tier 2: Temporal Sequence Modelling (D2.1) -- `entity_sequence_log`, `transition_matrix`, `transition_matrix_version` tables; consumer interface (`get_transitions_from`, `get_transition_probability`)
**Enables**: Hypothesis Generation (T5.3), Causal Direction Testing (T5.4)

---

## 1. Problem Statement

The Temporal Sequence infrastructure (D2.1) computes transition probability matrices per `(tenant_id, entity_domain)`. These matrices encode what the system has learned about normal entity state progressions: the standard failure lifecycle, recovery patterns, and steady-state self-transitions.

The Surprise Engine (D1.1) detects anomalous snap scores -- individual pairwise evaluations that deviate from the scoring distribution. But it cannot detect anomalous **entity behaviour over time**. An entity that skips expected intermediate states, takes a never-before-seen transition, or follows a pattern inconsistent with its domain's learned norms will not necessarily produce surprising snap scores.

Expectation Violation Detection bridges this gap. It compares each observed entity state transition against the transition probability matrix and flags deviations. It answers the question: "Given what we have learned about how entities of this type behave, is this transition expected or anomalous?"

**What this is**: A real-time evaluator that consumes entity sequence log updates, looks up the observed transition in the matrix, computes a violation severity using the same information-theoretic foundation as the Surprise Engine, and persists explainable violation records.

**What this is NOT**: This does NOT build or maintain the transition matrix (D2.1 does that). This does NOT generate hypotheses about why the violation occurred (T5.3 does that). This does NOT score snap decisions (D1.1 does that).

---

## 2. Definitions

### 2.1 Observed Transition

When a new entry is appended to `entity_sequence_log` for entity E at time t with `state_key = S_new`, and the immediately prior entry for entity E has `state_key = S_prev`, the **observed transition** is the ordered pair `(S_prev, S_new)`.

### 2.2 Expected Distribution

For the observed transition's `from_state = S_prev`, the **expected distribution** is the set of all rows in `transition_matrix` where `(tenant_id, entity_domain, from_state) = (T, D, S_prev)`. This is the full conditional distribution `P(to_state | S_prev)` as learned from historical observations.

### 2.3 Violation

A **violation** occurs when the observed transition has low probability under the expected distribution. Formally, the transition `(S_prev, S_new)` is a violation when its violation severity exceeds the configured threshold.

### 2.4 Violation Severity

Violation severity is the Shannon self-information of the observed transition, using the Laplace-smoothed probability from the matrix:

```
severity(S_prev -> S_new) = -log2(P_smoothed(S_new | S_prev))
```

This reuses the same information-theoretic foundation as D1.1 (surprise = -log2(P)), applied to transition probabilities rather than score distributions.

### 2.5 Never-Seen Transition

A transition `(S_prev, S_new)` where no row exists in `transition_matrix` for this `(from_state, to_state)` pair. The transition has zero observed count. After Laplace smoothing, the probability is non-zero but very small, producing high violation severity.

---

## 3. Algorithm

### 3.1 Trigger Point

The violation detector is invoked inline with the temporal sequence recording path, immediately after `record_observation()` and `incremental_update()` complete in D2.1:

```
enrichment_chain.enrich()
  -> creates AbeyanceFragmentORM (fragment F)
  -> creates FragmentEntityRefORM entries (entity refs E1, E2, ...)
  -> calls temporal_sequence.record_observation(session, tenant_id, fragment F, entity_refs)
  -> calls temporal_sequence.incremental_update(session, ...) [per entity]
  -> calls violation_detector.evaluate_transition(session, tenant_id, entity, S_prev, S_new)
```

### 3.2 Core Algorithm

```python
async def evaluate_transition(
    session: AsyncSession,
    tenant_id: str,
    entity_id: UUID,
    entity_identifier: str,
    entity_domain: str,
    from_state: str,
    to_state: str,
    event_timestamp: datetime,
    fragment_id: UUID,
    prev_fragment_id: UUID,
) -> Optional[ViolationRecord]:
    """
    Evaluate whether the observed transition (from_state -> to_state)
    violates the expected distribution for this entity domain.

    Returns a ViolationRecord if severity exceeds threshold, else None.
    """

    # --- 1. Matrix confidence gate ---
    from_row_summary = await get_from_state_summary(
        session, tenant_id, entity_domain, from_state
    )

    if from_row_summary is None:
        # from_state has never been seen as a source state in the matrix.
        # No expectations exist. Cannot evaluate violation.
        # Emit metric and return.
        return None

    total_from_count = from_row_summary.total_from_count
    matrix_version = from_row_summary.matrix_version
    confidence = _categorize_confidence(total_from_count)

    if confidence == "INSUFFICIENT":
        # Fewer than 5 transitions observed from this state.
        # Matrix is too sparse for meaningful violation detection.
        return None

    if confidence == "LOW_CONFIDENCE":
        # 5-19 transitions. Per D2.1 Section 7.2, T5.2 ignores LOW_CONFIDENCE.
        # Record as suppressed for observability, do not emit violation.
        return None

    # Require STABLE (20-99) or HIGH_CONFIDENCE (>=100) to proceed.

    # --- 2. Retrieve expected distribution ---
    expected_transitions = await get_transitions_from(
        session, tenant_id, entity_domain, from_state,
        min_confidence="STABLE",
    )
    # expected_transitions: list of TransitionRow, each with
    #   .to_state, .transition_count, .total_from_count, .probability

    # --- 3. Compute Laplace-smoothed probability ---
    observed_row = _find_transition(expected_transitions, to_state)
    observed_count = observed_row.transition_count if observed_row else 0

    # V = number of distinct to_states observed from from_state, plus 1
    # for the unseen-state pseudocount (per D2.1 Section 7.3)
    vocabulary_size = len(expected_transitions) + 1
    alpha = 1  # Laplace pseudocount

    p_smoothed = (observed_count + alpha) / (total_from_count + alpha * vocabulary_size)

    # --- 4. Compute violation severity ---
    severity = -math.log2(p_smoothed)
    severity = min(severity, SEVERITY_CAP)  # cap at 20.0 bits

    # --- 5. Determine expected state (most probable transition) ---
    expected_transitions_sorted = sorted(
        expected_transitions, key=lambda r: r.probability, reverse=True
    )
    most_probable_state = expected_transitions_sorted[0].to_state if expected_transitions_sorted else None
    most_probable_p = expected_transitions_sorted[0].probability if expected_transitions_sorted else 0.0

    # --- 6. Threshold check ---
    threshold = _get_violation_threshold(
        confidence, total_from_count, entity_domain
    )

    if severity < threshold:
        return None  # Transition is within expected bounds

    # --- 7. Build and persist violation record ---
    # Capture top-K expected transitions for explainability
    top_k_expected = [
        {
            "to_state": row.to_state,
            "probability": row.probability,
            "count": row.transition_count,
        }
        for row in expected_transitions_sorted[:5]
    ]

    violation = ViolationRecord(
        tenant_id=tenant_id,
        entity_id=entity_id,
        entity_identifier=entity_identifier,
        entity_domain=entity_domain,
        from_state=from_state,
        to_state=to_state,
        event_timestamp=event_timestamp,
        fragment_id=fragment_id,
        prev_fragment_id=prev_fragment_id,
        severity_bits=severity,
        observed_probability=p_smoothed,
        expected_most_probable_state=most_probable_state,
        expected_most_probable_p=most_probable_p,
        top_k_expected=top_k_expected,
        total_from_count=total_from_count,
        vocabulary_size=vocabulary_size,
        confidence_category=confidence,
        matrix_version=matrix_version,
        violation_threshold=threshold,
        violation_class=_classify_violation(severity, confidence),
    )

    await persist_violation(session, violation)
    await enqueue_for_discovery(violation)

    return violation
```

### 3.3 Laplace Smoothing Detail

The smoothing formula follows D2.1 Section 7.3 exactly:

```
P_smoothed(S_new | S_prev) = (count(S_prev -> S_new) + alpha) / (total_from_count + alpha * V)
```

Where:
- `count(S_prev -> S_new)`: raw transition count from the matrix. Zero if the transition has never been observed.
- `alpha = 1`: Laplace pseudocount.
- `V = |observed to_states from S_prev| + 1`: the vocabulary of known target states plus one slot for any unseen state.
- `total_from_count`: total transitions observed departing from `S_prev`.

This ensures:
- Never-seen transitions get probability `1 / (total_from_count + V)`, which is small but non-zero.
- `-log2(P_smoothed)` is always finite.
- Observed transitions retain their relative ordering -- smoothing redistributes a small amount of mass from observed to unobserved transitions.

### 3.4 Severity Cap

Severity is capped at 20.0 bits, consistent with D1.1's `SURPRISE_CAP`. This prevents pathological values when a never-seen transition occurs against a very large `total_from_count`.

```
SEVERITY_CAP = 20.0  # bits
```

---

## 4. Violation Severity Scoring

### 4.1 Severity Interpretation

| Severity (bits) | P_smoothed | Interpretation |
|---|---|---|
| 0 - 2 | > 0.25 | Common transition. No violation. |
| 2 - 5 | 0.03 - 0.25 | Uncommon but observed. Mild deviation. |
| 5 - 8 | 0.004 - 0.03 | Rare transition. Moderate violation. |
| 8 - 12 | 0.0002 - 0.004 | Very rare or near-boundary transition. Significant violation. |
| 12 - 16 | < 0.0002 | Extremely rare or never-before-seen. Critical violation. |
| 16 - 20 | << 0.0001 | Effectively unprecedented. Maximum severity. |

### 4.2 Violation Classification

Violations are classified into severity tiers for downstream triage:

```python
def _classify_violation(severity_bits: float, confidence: str) -> str:
    """
    Classify a violation based on severity and matrix confidence.
    """
    if severity_bits >= 12.0:
        return "CRITICAL"
    elif severity_bits >= 8.0:
        return "MAJOR"
    elif severity_bits >= 5.0:
        return "MODERATE"
    else:
        return "MINOR"
```

The `confidence` category (STABLE vs HIGH_CONFIDENCE) is stored alongside but does not change the classification. Downstream consumers may weight HIGH_CONFIDENCE violations more heavily.

---

## 5. Threshold: Minimum Matrix Confidence

### 5.1 Confidence Gate

The violation detector enforces a strict confidence gate before evaluating transitions. This prevents false violations from sparse matrices.

| Confidence Category | total_from_count | Violation Detector Behaviour |
|---|---|---|
| `INSUFFICIENT` | < 5 | **Skip entirely.** No evaluation. No record. |
| `LOW_CONFIDENCE` | 5 - 19 | **Skip.** Per D2.1 mandate. Metric emitted for observability. |
| `STABLE` | 20 - 99 | **Evaluate.** Apply elevated threshold (Section 5.2). |
| `HIGH_CONFIDENCE` | >= 100 | **Evaluate.** Apply standard threshold. |

### 5.2 Dynamic Violation Threshold

The violation threshold adapts based on matrix confidence. A matrix with fewer observations produces noisier probability estimates, so the threshold is raised to suppress false violations:

```python
# Domain-specific base thresholds (bits)
DOMAIN_BASE_THRESHOLDS = {
    "RAN": 5.0,
    "TRANSPORT": 5.5,
    "IP": 5.0,
    "CORE": 6.0,
    "VNF": 5.5,
    "DEFAULT": 5.5,
}

def _get_violation_threshold(
    confidence: str,
    total_from_count: int,
    entity_domain: str,
) -> float:
    """
    Compute the violation threshold based on confidence and domain.
    """
    base = DOMAIN_BASE_THRESHOLDS.get(entity_domain, DOMAIN_BASE_THRESHOLDS["DEFAULT"])

    if confidence == "STABLE":
        # 20-99 observations: raise threshold by 2 bits to compensate
        # for higher variance in probability estimates.
        return base + 2.0
    elif confidence == "HIGH_CONFIDENCE":
        # 100+ observations: use base threshold.
        return base

    # INSUFFICIENT and LOW_CONFIDENCE should not reach here (gated in step 1).
    return float("inf")
```

**Rationale for domain-specific thresholds**: CORE domain entities (e.g., MME, SGW) have slower state cycles and rarer failure transitions. A transition that looks unusual in RAN (where entities cycle rapidly through states) may be normal scarcity in CORE. The CORE threshold is set higher (6.0 bits) to account for this.

### 5.3 Threshold Summary

| Confidence | RAN | TRANSPORT | IP | CORE | VNF |
|---|---|---|---|---|---|
| STABLE (20-99) | 7.0 | 7.5 | 7.0 | 8.0 | 7.5 |
| HIGH_CONFIDENCE (100+) | 5.0 | 5.5 | 5.0 | 6.0 | 5.5 |

---

## 6. Expected vs Observed: Explainability Record

### 6.1 Design Principle

Every violation record stores both what was observed and what was expected, so that operators and downstream mechanisms can understand the violation without re-querying the matrix (which may have been updated since the violation was recorded).

### 6.2 Stored Comparison

Each `ViolationRecord` includes:

1. **Observed transition**: `(from_state, to_state)` -- what actually happened.
2. **Observed probability**: `p_smoothed` -- the Laplace-smoothed probability of the observed transition.
3. **Expected most probable state**: the `to_state` with the highest probability from `from_state`.
4. **Expected most probable probability**: the probability of that most-probable transition.
5. **Top-K expected**: the top 5 transitions sorted by probability, with their counts and probabilities.
6. **Severity**: `-log2(p_smoothed)` -- how surprising the observed transition is.

This allows a consumer to reconstruct the reasoning:

> "From state X, the system expected transition to state A (P=0.947) or state B (P=0.053). Instead, the entity transitioned to state C (P_smoothed=0.003, severity=8.4 bits). This is a MAJOR violation."

### 6.3 Top-K Expected Format

```json
{
  "top_k_expected": [
    {"to_state": "NOMINAL:ALARM:CLEAR", "probability": 0.947, "count": 710},
    {"to_state": "DARK_NODE:ALARM:CRITICAL", "probability": 0.053, "count": 40},
    {"to_state": "CASCADING_FAILURE:ALARM:CRITICAL", "probability": 0.003, "count": 0}
  ]
}
```

The third entry (count=0) appears when the observed transition is a never-seen state that gets included via the Laplace pseudocount. Its probability is the smoothed estimate.

---

## 7. Storage Schema

### 7.1 Table: `expectation_violation`

| Column Name | Type | Nullable | Default | Constraints | Notes |
|---|---|---|---|---|---|
| id | UUID | NO | gen_random_uuid() | PRIMARY KEY | Violation record ID |
| tenant_id | VARCHAR(100) | NO | - | NOT NULL | Tenant isolation (INV-7) |
| entity_id | UUID | NO | - | NOT NULL, FK -> shadow_entity.id | Entity that violated |
| entity_identifier | VARCHAR(500) | NO | - | NOT NULL | Denormalized for display |
| entity_domain | VARCHAR(50) | NO | - | NOT NULL | Domain partition |
| from_state | VARCHAR(200) | NO | - | NOT NULL | Source state (state_key) |
| to_state | VARCHAR(200) | NO | - | NOT NULL | Observed target state (state_key) |
| event_timestamp | TIMESTAMPTZ | NO | - | NOT NULL | When the transition occurred |
| fragment_id | UUID | NO | - | NOT NULL, FK -> abeyance_fragment.id | Fragment that caused the transition |
| prev_fragment_id | UUID | NO | - | NOT NULL, FK -> abeyance_fragment.id | Fragment that established the from_state |
| severity_bits | REAL | NO | - | NOT NULL | Violation severity in bits: -log2(P_smoothed) |
| observed_probability | REAL | NO | - | NOT NULL | P_smoothed(to_state given from_state) |
| expected_most_probable_state | VARCHAR(200) | YES | NULL | - | Highest-probability to_state from matrix |
| expected_most_probable_p | REAL | YES | NULL | - | Probability of the most probable transition |
| top_k_expected | JSONB | NO | - | NOT NULL | Top 5 expected transitions with probabilities and counts |
| total_from_count | INTEGER | NO | - | NOT NULL | Total transitions from from_state at evaluation time |
| vocabulary_size | INTEGER | NO | - | NOT NULL | Number of distinct to_states + 1 (for Laplace) |
| confidence_category | VARCHAR(20) | NO | - | NOT NULL | STABLE or HIGH_CONFIDENCE |
| matrix_version | INTEGER | NO | - | NOT NULL | transition_matrix.matrix_version at evaluation time |
| violation_threshold | REAL | NO | - | NOT NULL | Threshold applied at evaluation time |
| violation_class | VARCHAR(20) | NO | - | NOT NULL | CRITICAL, MAJOR, MODERATE, MINOR |
| created_at | TIMESTAMPTZ | NO | now() | NOT NULL, server_default | Row creation time |
| reviewed | BOOLEAN | NO | FALSE | NOT NULL, DEFAULT | Operator/system review status |
| reviewed_at | TIMESTAMPTZ | YES | NULL | - | When reviewed |
| review_verdict | VARCHAR(30) | YES | NULL | CHECK | Operator disposition |

#### 7.1.1 CHECK Constraints

```sql
ALTER TABLE expectation_violation
  ADD CONSTRAINT chk_ev_severity_range
    CHECK (severity_bits >= 0.0 AND severity_bits <= 20.0);

ALTER TABLE expectation_violation
  ADD CONSTRAINT chk_ev_prob_range
    CHECK (observed_probability >= 0.0 AND observed_probability <= 1.0);

ALTER TABLE expectation_violation
  ADD CONSTRAINT chk_ev_confidence
    CHECK (confidence_category IN ('STABLE', 'HIGH_CONFIDENCE'));

ALTER TABLE expectation_violation
  ADD CONSTRAINT chk_ev_class
    CHECK (violation_class IN ('CRITICAL', 'MAJOR', 'MODERATE', 'MINOR'));

ALTER TABLE expectation_violation
  ADD CONSTRAINT chk_ev_verdict
    CHECK (review_verdict IS NULL OR review_verdict IN
           ('TRUE_VIOLATION', 'FALSE_ALARM', 'KNOWN_PATTERN', 'EXPECTED_MAINTENANCE', 'DEFERRED'));
```

#### 7.1.2 Indexes

| Index Name | Columns | Type | Notes |
|---|---|---|---|
| ix_ev_tenant_time | (tenant_id, event_timestamp DESC) | BTREE | Primary query: recent violations for a tenant. |
| ix_ev_entity | (tenant_id, entity_id, event_timestamp DESC) | BTREE | Entity-scoped query: violation history for a specific entity. |
| ix_ev_unreviewed | (tenant_id, violation_class, created_at) WHERE reviewed = FALSE | BTREE, PARTIAL | Triage queue: unreviewed violations ordered by class and time. |
| ix_ev_severity | (tenant_id, entity_domain, severity_bits DESC) | BTREE | "What are the most severe violations in this domain?" |
| ix_ev_from_state | (tenant_id, entity_domain, from_state) | BTREE | Pattern query: which from_states are generating violations? |
| ix_ev_matrix_version | (tenant_id, entity_domain, matrix_version) | BTREE | Provenance: which matrix version was used? |
| ix_ev_fragment | (fragment_id) | BTREE | Reverse lookup from fragment to violations it caused. |

#### 7.1.3 Retention

Violation records follow a tiered retention policy:

| violation_class | Retention | Rationale |
|---|---|---|
| CRITICAL | 1095 days (3 years) | Long-term pattern analysis and audit trail. |
| MAJOR | 730 days (2 years) | Aligns with fragment max_lifetime_days. |
| MODERATE | 365 days (1 year) | Sufficient for seasonal pattern analysis. |
| MINOR | 180 days (6 months) | Short-lived, high-volume. |

Retention pruning runs as part of the maintenance sweep.

---

## 8. Provenance

### 8.1 Full Provenance Chain

Every violation record stores enough context to reconstruct the evaluation without accessing the (potentially updated) transition matrix:

| Provenance Element | Storage Column | Purpose |
|---|---|---|
| Observed transition | `from_state`, `to_state` | What happened |
| Triggering fragment | `fragment_id` | Which fragment caused this transition |
| Prior fragment | `prev_fragment_id` | Which fragment established the from_state |
| Entity | `entity_id`, `entity_identifier`, `entity_domain` | Who it happened to |
| When | `event_timestamp` | When the transition occurred |
| Matrix version | `matrix_version` | Which version of the transition matrix was consulted |
| Matrix state at evaluation | `total_from_count`, `vocabulary_size` | Size of the evidence base at evaluation time |
| Smoothed probability | `observed_probability` | The P_smoothed value used in severity computation |
| Severity | `severity_bits` | The computed -log2(P_smoothed) |
| Expected distribution snapshot | `top_k_expected` (JSONB) | The top 5 alternatives with probabilities and counts |
| Most probable alternative | `expected_most_probable_state`, `expected_most_probable_p` | What the system expected to happen |
| Confidence | `confidence_category` | How much data backed the matrix at evaluation time |
| Threshold | `violation_threshold` | The threshold applied (varies by confidence and domain) |
| Classification | `violation_class` | CRITICAL / MAJOR / MODERATE / MINOR |

### 8.2 Matrix Version Linkage

The `matrix_version` column links to `transition_matrix_version` (D2.1 Section 3.3), enabling:

- Determining the observation window that produced the matrix (`window_start`, `window_end`).
- Determining how many total transitions and distinct states were in the matrix at that version.
- Determining whether the violation was evaluated against an incrementally-updated or fully-recomputed matrix (`trigger` column in version table).

### 8.3 Fragment Pair Linkage

Both `fragment_id` (the fragment that caused the new state) and `prev_fragment_id` (the fragment that established the prior state) are stored. This allows an operator to inspect both fragments side-by-side to understand the transition context:

```sql
-- Reconstruct the violation context
SELECT
  ev.*,
  f_new.raw_text AS new_fragment_text,
  f_new.source_type AS new_source,
  f_prev.raw_text AS prev_fragment_text,
  f_prev.source_type AS prev_source
FROM expectation_violation ev
JOIN abeyance_fragment f_new ON ev.fragment_id = f_new.id
JOIN abeyance_fragment f_prev ON ev.prev_fragment_id = f_prev.id
WHERE ev.id = :violation_id;
```

---

## 9. Telecom Example

### 9.1 Scenario: Unexpected Cascade from link_down

**Setup**: Tenant `telco2`, entity domain `TRANSPORT`. The transition matrix for TRANSPORT has been accumulating data for 180 days across 200 transport links. The matrix reflects the standard transport link failure lifecycle.

**Normal lifecycle** (from the matrix):

```
NOMINAL:TELEMETRY_EVENT:INFO
  -> NOMINAL:TELEMETRY_EVENT:INFO                 P=0.982  (count=24,550)
  -> DARK_ATTRIBUTE:TELEMETRY_EVENT:WARNING        P=0.014  (count=350)
  -> LINK_DOWN:ALARM:MAJOR                         P=0.004  (count=100)

LINK_DOWN:ALARM:MAJOR
  -> RECOVERY:ALARM:CLEAR                          P=0.893  (count=670)   <-- expected
  -> LINK_DOWN:ALARM:MAJOR                         P=0.067  (count=50)    (self-transition, link still down)
  -> DARK_NODE:ALARM:CRITICAL                      P=0.040  (count=30)    (escalation to node-level)

RECOVERY:ALARM:CLEAR
  -> NOMINAL:TELEMETRY_EVENT:INFO                  P=0.964  (count=645)
  -> DARK_ATTRIBUTE:TELEMETRY_EVENT:WARNING         P=0.036  (count=24)
```

**Matrix state for from_state = LINK_DOWN:ALARM:MAJOR**:
- `total_from_count = 750` (HIGH_CONFIDENCE)
- `matrix_version = 47`
- `vocabulary_size = 3` (three distinct to_states observed) + 1 = 4 for Laplace

### 9.2 Observed Event

At 14:32 UTC, transport link `TL-0087` (entity_id: `d4e5f6...`) transitions from `LINK_DOWN:ALARM:MAJOR` to `CASCADING_FAILURE:ALARM:CRITICAL`.

This state (`CASCADING_FAILURE:ALARM:CRITICAL`) has **never been observed** as a target from `LINK_DOWN:ALARM:MAJOR`. It is a never-seen transition.

### 9.3 Evaluation Walkthrough

**Step 1: Confidence gate**
- `total_from_count = 750` -> `HIGH_CONFIDENCE`. Proceed.

**Step 2: Retrieve expected distribution**
- Returns the three rows listed above (RECOVERY:ALARM:CLEAR, LINK_DOWN:ALARM:MAJOR self, DARK_NODE:ALARM:CRITICAL).

**Step 3: Laplace-smoothed probability**
- `observed_count = 0` (CASCADING_FAILURE:ALARM:CRITICAL never seen from this from_state)
- `alpha = 1`
- `V = 3 + 1 = 4` (3 observed to_states + 1 unseen slot)
- `P_smoothed = (0 + 1) / (750 + 1 * 4) = 1 / 754 = 0.001326`

**Step 4: Violation severity**
- `severity = -log2(0.001326) = 9.56 bits`

**Step 5: Expected state**
- Most probable: `RECOVERY:ALARM:CLEAR` at P=0.893.
- The system expected the link to recover. Instead, it cascaded.

**Step 6: Threshold check**
- Domain: TRANSPORT, Confidence: HIGH_CONFIDENCE.
- Threshold: `5.5 bits`.
- `9.56 >= 5.5` -- **VIOLATION TRIGGERED**.

**Step 7: Violation record**

```json
{
  "id": "a1b2c3d4-...",
  "tenant_id": "telco2",
  "entity_id": "d4e5f6...",
  "entity_identifier": "TL-0087",
  "entity_domain": "TRANSPORT",
  "from_state": "LINK_DOWN:ALARM:MAJOR",
  "to_state": "CASCADING_FAILURE:ALARM:CRITICAL",
  "event_timestamp": "2026-03-16T14:32:00Z",
  "severity_bits": 9.56,
  "observed_probability": 0.001326,
  "expected_most_probable_state": "RECOVERY:ALARM:CLEAR",
  "expected_most_probable_p": 0.893,
  "top_k_expected": [
    {"to_state": "RECOVERY:ALARM:CLEAR", "probability": 0.893, "count": 670},
    {"to_state": "LINK_DOWN:ALARM:MAJOR", "probability": 0.067, "count": 50},
    {"to_state": "DARK_NODE:ALARM:CRITICAL", "probability": 0.040, "count": 30}
  ],
  "total_from_count": 750,
  "vocabulary_size": 4,
  "confidence_category": "HIGH_CONFIDENCE",
  "matrix_version": 47,
  "violation_threshold": 5.5,
  "violation_class": "MAJOR"
}
```

### 9.4 Operator Interpretation

The violation record tells the operator:

> Transport link TL-0087 went from LINK_DOWN (major) to CASCADING_FAILURE (critical). In 750 prior transitions from LINK_DOWN, this has never happened. The expected outcome was RECOVERY (89.3% of the time) or staying in LINK_DOWN (6.7%) or escalating to DARK_NODE (4.0%). A cascading failure from a single link down is a never-before-seen pattern. Severity: 9.56 bits (MAJOR).

This is actionable: the cascading failure may indicate a hidden dependency between TL-0087 and other transport elements, a firmware bug that turns isolated link failures into cascades, or a topology change that the CMDB has not yet captured.

### 9.5 Contrast: Expected Transition (No Violation)

At 15:10 UTC, transport link `TL-0092` transitions from `LINK_DOWN:ALARM:MAJOR` to `RECOVERY:ALARM:CLEAR`.

- `P_smoothed(RECOVERY:ALARM:CLEAR | LINK_DOWN:ALARM:MAJOR) = (670 + 1) / (750 + 4) = 671/754 = 0.890`
- `severity = -log2(0.890) = 0.168 bits`
- Threshold: 5.5 bits.
- `0.168 < 5.5` -- no violation. This is the normal recovery path.

---

## 10. Edge Cases

### 10.1 First Observation for an Entity

When `record_observation()` appends the first entry for an entity, there is no prior state. The `incremental_update()` returns early (D2.1 Section 5.3.1), and the violation detector is not invoked. No violation can be evaluated without a from_state.

### 10.2 Self-Transition Violations

A self-transition `(S, S)` can be a violation if the entity domain's matrix shows that self-transitions from state S are rare. Example: a CORE entity in `MAINTENANCE:CHANGE_RECORD:INFO` is expected to transition to `NOMINAL:TELEMETRY_EVENT:INFO` (maintenance complete) within a few observations. Repeated self-transitions (maintenance stuck) would have decreasing probability if the matrix shows the self-transition as rare. In practice, self-transitions at stable states like NOMINAL have probability >0.9 and will never trigger violations.

### 10.3 Matrix Recompute During Evaluation

The transition matrix may be recomputed (full recompute, D2.1 Section 5.3.2) between the time the violation detector reads the matrix and the time it persists the violation record. This is handled by:

1. Recording `matrix_version` at read time.
2. Using the read values (counts, probabilities) for the evaluation -- no re-read.
3. The violation record is a snapshot of the evaluation, not a pointer to the current matrix state.

### 10.4 State Vocabulary Growth

When a fragment introduces a new state_key that has never appeared in the matrix (neither as from_state nor to_state), the transition `(S_prev, S_new_unknown)` is evaluated as a never-seen transition. Laplace smoothing handles this correctly. The violation severity will be high, which is the correct signal -- a previously unknown state is inherently surprising.

### 10.5 Timestamp Ordering Anomalies

If a late-arriving fragment has an `event_timestamp` that falls between two already-recorded entries for the same entity, the D2.1 sequence log records it in chronological order (indexed by `(event_timestamp, id)`). However, the violation detector is invoked at recording time, not replay time. The late arrival creates a transition against the most-recent-prior entry at recording time, which may differ from what a chronological scan would produce. This is acceptable: the alternative (re-evaluating the entire sequence on every late arrival) is prohibitively expensive. The full matrix recompute (D2.1 Section 5.3.2) corrects the matrix periodically.

---

## 11. Integration Points

### 11.1 Input: Temporal Sequence Service

The violation detector is invoked by the temporal sequence service after `record_observation()` and `incremental_update()`:

```python
# In temporal_sequence.py, after recording and matrix update:
async def process_new_observation(
    session, tenant_id, fragment, entity_refs
):
    entries_count = await record_observation(session, tenant_id, fragment, entity_refs)

    for ref in entity_refs:
        if ref.entity_id is None:
            continue

        # Get previous state for this entity
        prev_entry = await _get_previous_entry(session, tenant_id, ref.entity_id, fragment.event_timestamp)
        if prev_entry is None:
            continue

        new_state_key = derive_state_key(fragment)[3]

        # Update matrix
        await incremental_update(
            session, tenant_id, ref.entity_id, ref.entity_domain,
            new_state_key, fragment.event_timestamp
        )

        # Evaluate violation
        await violation_detector.evaluate_transition(
            session=session,
            tenant_id=tenant_id,
            entity_id=ref.entity_id,
            entity_identifier=ref.entity_identifier,
            entity_domain=ref.entity_domain,
            from_state=prev_entry.state_key,
            to_state=new_state_key,
            event_timestamp=fragment.event_timestamp,
            fragment_id=fragment.id,
            prev_fragment_id=prev_entry.fragment_id,
        )
```

### 11.2 Output: Discovery Queue

`CRITICAL` and `MAJOR` violations are placed on the discovery queue (in-process queue or Kafka topic `abeyance.discovery.violation`) for consumption by the hypothesis generation mechanism (T5.3).

`MODERATE` and `MINOR` violations are persisted but not enqueued. They are available for batch analysis and pattern detection.

### 11.3 Output: Operational Metrics

```
# Prometheus metrics emitted by the violation detector

violation_detector_evaluated_total{tenant_id, entity_domain}
    # Counter: total transitions evaluated (passed confidence gate)

violation_detector_violations_total{tenant_id, entity_domain, violation_class}
    # Counter: violations emitted, by class

violation_detector_skipped_insufficient{tenant_id, entity_domain}
    # Counter: transitions skipped due to INSUFFICIENT confidence

violation_detector_skipped_low_confidence{tenant_id, entity_domain}
    # Counter: transitions skipped due to LOW_CONFIDENCE

violation_detector_severity_bits{tenant_id, entity_domain}
    # Histogram: distribution of severity values for all evaluated transitions

violation_detector_never_seen_total{tenant_id, entity_domain}
    # Counter: violations where observed_count was 0 (never-seen transitions)
```

### 11.4 Output: Surprise Engine Cross-Reference

When a violation is detected, the violation detector checks whether a surprise event (D1.1) was also emitted for the same fragment. If both fire, the violation record includes a cross-reference. This is stored as an optional column:

```sql
ALTER TABLE expectation_violation
  ADD COLUMN correlated_surprise_event_id UUID REFERENCES surprise_event(event_id);
```

Dual-signal events (both surprise and violation) are prioritised by the hypothesis generator.

---

## 12. Computational Complexity

### 12.1 Per Transition Evaluation

| Operation | Complexity | Notes |
|---|---|---|
| Confidence gate (read total_from_count) | O(1) | Single indexed lookup on `ix_tm_from_state` |
| Get expected distribution | O(K) | K = number of distinct to_states from this from_state. Typically 3-10. |
| Laplace smoothing | O(1) | Arithmetic on two integers |
| Severity computation | O(1) | Single log2 |
| Threshold lookup | O(1) | Dictionary lookup by domain |
| Build top-K | O(K log K) | Sort K transitions. K is small. |
| Persist violation | O(1) | Single INSERT when threshold exceeded |

**Total per transition**: O(K log K) where K is the fan-out from the from_state. For typical telecom entities, K ranges from 2 to 15. Effectively constant-time.

### 12.2 Memory

The violation detector is stateless -- it reads from the transition matrix on each invocation. No in-memory histograms or rolling windows. The only persistent state is the `expectation_violation` table.

### 12.3 I/O

- **Read**: 1-2 indexed queries per transition (confidence gate + expected distribution, which can be combined into one query).
- **Write**: 1 INSERT per violation. At typical violation rates (< 1% of transitions), this is sparse.

---

## 13. Configuration Parameters Summary

| Parameter | Value | Scope | Tunable |
|---|---|---|---|
| `SEVERITY_CAP` | 20.0 bits | Global | No (aligned with D1.1) |
| `LAPLACE_ALPHA` | 1 | Global | No (standard Laplace smoothing) |
| `MIN_CONFIDENCE_FOR_EVALUATION` | STABLE (total_from_count >= 20) | Global | Yes (per-domain override possible) |
| `DOMAIN_BASE_THRESHOLDS` | RAN: 5.0, TRANSPORT: 5.5, IP: 5.0, CORE: 6.0, VNF: 5.5 | Per-domain | Yes |
| `CONFIDENCE_UPLIFT_BITS` | 2.0 | Global | Yes |
| `TOP_K_EXPECTED` | 5 | Global | Yes |
| `VIOLATION_RETENTION_CRITICAL` | 1095 days | Global | Yes |
| `VIOLATION_RETENTION_MAJOR` | 730 days | Global | Yes |
| `VIOLATION_RETENTION_MODERATE` | 365 days | Global | Yes |
| `VIOLATION_RETENTION_MINOR` | 180 days | Global | Yes |
| `ENQUEUE_MIN_CLASS` | MAJOR | Global | Yes (which classes go to discovery queue) |

---

## 14. Invariants

| ID | Statement | Enforcement |
|---|---|---|
| INV-V1 | Severity value in `[0.0, 20.0]` bits | `min(-log2(...), SEVERITY_CAP)` + Laplace smoothing prevents -log2(0) |
| INV-V2 | No violation evaluation on matrices with total_from_count < 20 | Confidence gate rejects INSUFFICIENT and LOW_CONFIDENCE |
| INV-V3 | Laplace-smoothed probability is always > 0 | `alpha=1` ensures numerator >= 1, denominator >= V > 0 |
| INV-V4 | Every violation record contains the matrix_version used at evaluation time | Set at read time, stored immutably |
| INV-V5 | Tenant isolation in all queries and storage | `tenant_id` present and leading in all indexes; all queries scoped by tenant |
| INV-V6 | No mutation of transition_matrix by the violation detector | Read-only consumer of matrix data; D2.1 owns all writes |
| INV-V7 | All violation records persisted before enqueue | `persist_violation()` called before `enqueue_for_discovery()` |
| INV-V8 | `top_k_expected` is a point-in-time snapshot, not a live reference | JSONB stored at evaluation time; survives matrix recompute |
| INV-V9 | `violation_class` is derivable from `severity_bits` | Classification is deterministic given severity; stored for index performance |
| INV-V10 | Probability values sum correctly under Laplace smoothing | `sum(P_smoothed(to | from) for all to in V) = 1.0` by construction |

---

## 15. Migration

### 15.1 Alembic Steps

```
1. CREATE TABLE expectation_violation (Section 7.1)
2. ADD CHECK CONSTRAINTS (Section 7.1.1)
3. CREATE INDEXES (Section 7.1.2)
4. ALTER TABLE -- add correlated_surprise_event_id column (Section 11.4)
```

All tables are new. No existing schema is modified.

### 15.2 Dependencies

This migration MUST run after:
- D2.1 migration (entity_sequence_log, transition_matrix, transition_matrix_version)
- D1.1 migration (surprise_event table -- for the FK on correlated_surprise_event_id)

### 15.3 Rollback

```sql
DROP TABLE IF EXISTS expectation_violation;
```

No other tables are modified by this migration.

---

Generated: 2026-03-16 | Task T5.2 | Abeyance Memory v3.0 | Discovery Mechanism #9 | Tier 3
