# Explainability Layer — Abeyance Memory v3.0

**Task**: T6.1 — Explainability Interface and Provenance Assembly
**Version**: 3.0
**Date**: 2026-03-16
**Status**: Specification
**Tier**: Cross-cutting — consumes outputs from all tiers (1, 2, 3)
**Depends On**:
- T1.4 (Snap Scoring) — `snap_decision_log`, `SnapDecisionRecord`
- D1.1 (Surprise Engine) — `surprise_event`, `surprise_distribution_state`
- T3.1 (Bridge Detection) — `bridge_discovery`, `bridge_discovery_provenance`
- D3.8 (Hypothesis Engine) — `hypothesis`, `evidence_record`, `confidence_history`
- T5.2 (Expectation Violation) — `expectation_violation`
- D3.1 (Causal Direction Testing) — `causal_candidate`, `causal_evidence_pair`

---

## 1. Problem Statement

Each discovery mechanism in Abeyance Memory v3.0 generates provenance records. The Snap Engine writes per-dimension scores, mask states, and weight redistribution. The Surprise Engine computes distributional self-information and escalation types. Bridge Detection records betweenness centrality and sub-component topology. The Hypothesis Engine logs TSLAM prompts, raw responses, and confidence evolution. Expectation Violation stores transition probabilities and matrix snapshots. Causal Direction Testing stores lag distributions and evidence fragment pairs.

These provenance records exist independently, scattered across six tables (plus their child tables). No mechanism currently assembles them into a coherent, operator-facing answer to the question: **"Why did the system flag this discovery?"**

The Explainability Layer is that assembly mechanism. It does not generate new provenance — all provenance is already specified per-mechanism. It reads, joins, and renders provenance into structured explanations that answer the operator's question at every level of detail they need.

**Scope**:
- Design the `DiscoveryExplanation` response object
- Design the provenance DAG that traces which signals contributed to a discovery
- Design the per-dimension scoring breakdown (never blended — raw contributions)
- Design the causal trace for Tier 3+ discoveries
- Design the hypothesis evolution log (confidence timeline, evidence attachment log)
- Design the contradiction resolution log
- Design the API response structure
- Specify the query assembly algorithm

**Out of scope**: The mechanisms that generate provenance (already specified). This layer is a read-only consumer of their outputs.

---

## 2. Discovery Identity Model

### 2.1 What Counts as a Discovery

A **discovery** is any event that crosses the escalation boundary into operator-visible territory. There are four discovery entry types in v3.0:

| Entry Type | Source Mechanism | DB Table | Escalation Criterion |
|---|---|---|---|
| `SURPRISE_DISCOVERY` | Surprise Engine (D1.1) | `surprise_event` | `escalation_type = 'DISCOVERY'` |
| `BRIDGE_DISCOVERY` | Bridge Detection (T3.1) | `bridge_discovery` | `classification = 'BRIDGE_DISCOVERY'` |
| `VIOLATION_DISCOVERY` | Expectation Violation (T5.2) | `expectation_violation` | `violation_class IN ('CRITICAL', 'MAJOR')` |
| `CAUSAL_CANDIDATE` | Causal Direction (D3.1) | `causal_candidate` | `confidence_label IN ('HIGH', 'MEDIUM')` |

A `Hypothesis` (from D3.8) is NOT an independent discovery entry type. Hypotheses are generated in response to discoveries and are attached to them as the system's explanatory reasoning layer.

### 2.2 Discovery Registry

A single `discovery_registry` table normalises all four entry types into a common discovery identity:

```sql
CREATE TABLE discovery_registry (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           VARCHAR(64) NOT NULL,

    -- Entry type and FK to source table
    entry_type          VARCHAR(32) NOT NULL
        CHECK (entry_type IN (
            'SURPRISE_DISCOVERY',
            'BRIDGE_DISCOVERY',
            'VIOLATION_DISCOVERY',
            'CAUSAL_CANDIDATE'
        )),
    source_id           UUID NOT NULL,
        -- FK to surprise_event.event_id, bridge_discovery.id,
        -- expectation_violation.id, or causal_candidate.id respectively.
        -- No hard FK because source tables vary. Enforced at application layer.

    -- Denormalised for fast listing without joins
    severity            VARCHAR(16) NOT NULL,
        -- Mapped from source: 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW'
    title               TEXT NOT NULL,   -- one-line description, <= 120 chars
    detected_at         TIMESTAMPTZ NOT NULL,

    -- Lifecycle
    status              VARCHAR(20) NOT NULL DEFAULT 'OPEN'
        CHECK (status IN ('OPEN', 'ACKNOWLEDGED', 'RESOLVED', 'DISMISSED')),
    resolved_at         TIMESTAMPTZ,
    dismissed_reason    TEXT,

    -- Linked hypothesis (set when D3.8 generates a hypothesis for this discovery)
    hypothesis_id       UUID,   -- FK to hypothesis.hypothesis_id (nullable)

    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_discovery_source UNIQUE (tenant_id, entry_type, source_id)
);

CREATE INDEX ix_dr_tenant_time
    ON discovery_registry (tenant_id, detected_at DESC);

CREATE INDEX ix_dr_tenant_status
    ON discovery_registry (tenant_id, status, severity, detected_at DESC);

CREATE INDEX ix_dr_hypothesis
    ON discovery_registry (hypothesis_id)
    WHERE hypothesis_id IS NOT NULL;
```

The `discovery_registry` is the single point of entry for the Explainability Layer. All explanation queries start from a `discovery_registry.id`.

---

## 3. The DiscoveryExplanation Object

### 3.1 Top-Level Structure

```python
@dataclass
class DiscoveryExplanation:
    # Identity
    discovery_id: UUID                          # discovery_registry.id
    tenant_id: str
    entry_type: str                             # SURPRISE_DISCOVERY | BRIDGE_DISCOVERY | ...
    severity: str                               # CRITICAL | HIGH | MEDIUM | LOW
    title: str                                  # one-line summary
    detected_at: datetime

    # Answer to "why was this flagged?"
    flag_reason: FlagReason                     # primary signal that triggered escalation

    # Provenance DAG
    provenance_dag: ProvenanceDAG               # all contributing signals, linked

    # Per-dimension scoring breakdown (always present for SURPRISE_DISCOVERY)
    snap_scoring: Optional[SnapScoringExplanation]

    # Causal trace (present for VIOLATION_DISCOVERY and CAUSAL_CANDIDATE)
    causal_trace: Optional[CausalTrace]

    # Hypothesis evolution (present when a hypothesis has been generated)
    hypothesis_evolution: Optional[HypothesisEvolution]

    # Contradiction resolution log (present when contradicting evidence exists)
    contradiction_log: Optional[ContradictionLog]

    # Raw provenance links (for deep inspection / API consumers)
    raw_provenance_refs: list[ProvenanceRef]
```

### 3.2 FlagReason

The primary answer to "why was this flagged?" — written in terms an operator understands, backed by the exact numeric signal.

```python
@dataclass
class FlagReason:
    mechanism: str          # "SURPRISE_ENGINE" | "BRIDGE_DETECTION" |
                            # "EXPECTATION_VIOLATION" | "CAUSAL_DIRECTION"
    signal_type: str        # "STATISTICAL_ANOMALY" | "TOPOLOGY_BRIDGE" |
                            # "TRANSITION_VIOLATION" | "TEMPORAL_PRECEDENCE"

    # Human-readable explanation
    plain_text: str         # e.g. "This snap score (0.68) is in the top 2% of
                            # surprising scores for DARK_EDGE patterns in this tenant.
                            # Specifically, it fell in a score bin with only 0.018%
                            # probability mass, compared to the normal peak around 0.35."

    # The numeric signal
    primary_metric_name: str   # e.g. "composite_surprise_bits"
    primary_metric_value: float
    primary_metric_threshold: float
    primary_metric_units: str  # "bits" | "normalized_betweenness" | "bits" | "confidence"

    # What dimensions drove the primary metric (for SURPRISE_DISCOVERY)
    driving_dimensions: list[DrivingDimension]  # which per-dimension scores were surprising
```

```python
@dataclass
class DrivingDimension:
    dimension: str          # "semantic" | "topological" | "temporal" |
                            # "operational" | "entity_overlap"
    score: float            # the per-dimension score value
    surprise_bits: float    # per-dimension surprise (from SurpriseEvent.dimension_surprises)
    percentile_rank: float  # e.g. 0.99 means "top 1% most surprising for this dimension"
    available: bool         # was this dimension available (mask=True) during scoring?
```

### 3.3 ProvenanceDAG

The provenance DAG is a directed acyclic graph of all signals that contributed to this discovery. Each node is a signal source; edges represent "was produced by" or "triggered" relationships.

```python
@dataclass
class ProvenanceDAG:
    nodes: list[ProvenanceNode]
    edges: list[ProvenanceEdge]
    root_node_id: str       # the node representing the discovery itself

@dataclass
class ProvenanceNode:
    node_id: str            # unique within this DAG (not a UUID — a local label)
    node_type: str          # "DISCOVERY" | "SNAP_DECISION" | "SURPRISE_EVENT" |
                            # "BRIDGE_DISCOVERY" | "VIOLATION_RECORD" |
                            # "CAUSAL_CANDIDATE" | "HYPOTHESIS" | "FRAGMENT" |
                            # "ENTITY" | "ACCUMULATION_CLUSTER"
    source_table: str       # e.g. "snap_decision_log"
    source_id: str          # UUID of the source record (as string)
    label: str              # human-readable label for this node
    timestamp: Optional[datetime]   # when this node was created/observed

    # Summary data for display (avoids requiring a second API call)
    summary: dict           # key fields from the source record

@dataclass
class ProvenanceEdge:
    from_node_id: str
    to_node_id: str
    relationship: str       # "PRODUCED_BY" | "TRIGGERED_BY" | "SUPPORTED_BY" |
                            # "CONTRADICTED_BY" | "SCORED_AGAINST" |
                            # "BRIDGE_CONNECTS" | "PRECEDED_BY"
    label: Optional[str]    # human-readable edge label
```

**DAG construction rules**:

| Discovery Type | Root Node | First-level children | Second-level children |
|---|---|---|---|
| `SURPRISE_DISCOVERY` | `DISCOVERY` | `SURPRISE_EVENT` | `SNAP_DECISION` → `FRAGMENT` (pair) |
| `BRIDGE_DISCOVERY` | `DISCOVERY` | `BRIDGE_DISCOVERY` | sub-component `FRAGMENT` nodes → `ENTITY` nodes per domain |
| `VIOLATION_DISCOVERY` | `DISCOVERY` | `VIOLATION_RECORD` | `FRAGMENT` (triggering) + `FRAGMENT` (prior state) + `ENTITY` |
| `CAUSAL_CANDIDATE` | `DISCOVERY` | `CAUSAL_CANDIDATE` | `CAUSAL_EVIDENCE_PAIR` sample → `FRAGMENT` pairs |

When a hypothesis is present, a `HYPOTHESIS` node is added as a child of the `DISCOVERY` root with relationship `TRIGGERED_BY`.

### 3.4 ProvenanceRef

Raw references for API consumers that want to build their own views:

```python
@dataclass
class ProvenanceRef:
    ref_type: str           # "SNAP_DECISION" | "SURPRISE_EVENT" | "FRAGMENT" | etc.
    table: str              # exact table name
    id: str                 # UUID
    role: str               # "primary_signal" | "supporting" | "evidence_fragment" | etc.
```

---

## 4. Per-Dimension Scoring Breakdown

### 4.1 Design Principle

Scores are **never blended in the explanation**. The operator sees each dimension separately. The breakdown answers: "Which dimensions drove this snap score, and was each dimension reliable?"

### 4.2 SnapScoringExplanation

```python
@dataclass
class SnapScoringExplanation:
    # Source identity
    snap_decision_id: UUID
    fragment_a_id: UUID
    fragment_b_id: UUID
    failure_mode_profile: str

    # Per-dimension breakdown — five separate entries, never blended
    dimensions: list[DimensionBreakdown]

    # Composite computation trace
    raw_composite: float            # weighted sum before temporal modifier
    temporal_modifier: float        # [0.5, 1.0]
    final_score: float              # raw_composite * temporal_modifier
    threshold_applied: float        # after Sidak correction
    decision: str                   # "SNAP" | "NEAR_MISS" | "AFFINITY" | "NONE"

    # Weight redistribution summary
    weight_redistribution_occurred: bool
    dimensions_unavailable: list[str]   # dimensions excluded due to mask=False
    weight_mass_redistributed: float    # total weight mass that was redistributed

    # Calibration status
    calibration_status: str         # "INITIAL_ESTIMATE" | "EMPIRICALLY_VALIDATED"
    calibration_note: Optional[str] # e.g. "Weights are initial estimates; empirical
                                    # validation requires 500+ labeled outcomes"

    # Multiple comparisons
    multiple_comparisons_k: int
    sidak_correction_applied: bool
```

```python
@dataclass
class DimensionBreakdown:
    dimension: str              # "semantic" | "topological" | "temporal" |
                                # "operational" | "entity_overlap"
    available: bool             # mask state: was this dimension computable?
    unavailable_reason: Optional[str]
        # "mask_semantic_A=False (LLM embedding call failed for fragment A)"
        # "mask_topological_B=False (no topological neighbourhood for fragment B)"
        # None if available

    score: Optional[float]      # [0.0, 1.0] or None if unavailable
    base_weight: float          # from weight profile (before redistribution)
    adjusted_weight: float      # after redistribution (= base_weight if all available)
    contribution: Optional[float]
        # adjusted_weight * score — the exact contribution to raw_composite
        # None if unavailable

    # Surprise context (populated when this breakdown is part of a SURPRISE_DISCOVERY)
    surprise_bits: Optional[float]
    surprise_percentile_rank: Optional[float]
        # fraction of historical scores for this dimension that were LESS surprising
        # than the current score (e.g., 0.97 = this score is more surprising than
        # 97% of historical dimension scores for this failure mode in this tenant)

    # Human-readable interpretation
    interpretation: str
        # e.g. "Semantic similarity 0.82 is unusually HIGH for DARK_EDGE patterns
        # (typical range 0.20–0.45 in this tenant). This is the primary driver of
        # the high composite surprise."
        # or: "Topological similarity unavailable — LLM embedding call for fragment
        # A failed. Weight redistributed proportionally to available dimensions.
        # This means the topological signal, which carries 30% of base weight for
        # DARK_EDGE, is absent from this score."
```

### 4.3 Interpretation Generation

The `interpretation` field for each dimension is generated deterministically from thresholds — no LLM is involved. The rules are:

**For available dimensions**:
```
IF score is in top 5% of historical distribution for this dimension:
    "unusually HIGH for [profile] patterns"
ELIF score is in bottom 5%:
    "unusually LOW for [profile] patterns"
ELSE:
    "within normal range for [profile] patterns"

Append: "(typical range [p10]–[p90] in this tenant)"
```

**For unavailable dimensions**:
```
"[dimension] unavailable — [reason]. Weight (base=[base_weight:.0%]) redistributed
proportionally to the [n] available dimensions. Score excludes this signal."
```

**Weight redistribution summary** (appended to composite explanation when redistribution_occurred=True):
```
"Note: [n] dimension(s) were unavailable ([dim_list]), accounting for [redistributed_pct:.0%]
of base weight. The displayed adjusted weights account for this redistribution. The composite
score reflects only the [m] available dimensions."
```

---

## 5. Causal Trace (Tier 3+ Discoveries)

### 5.1 When a Causal Trace is Included

A `CausalTrace` is included in the explanation when the discovery is of type `VIOLATION_DISCOVERY` or `CAUSAL_CANDIDATE`, or when the discovery has a linked `Hypothesis` that references causal evidence.

For `SURPRISE_DISCOVERY` and `BRIDGE_DISCOVERY`, a causal trace is included only if a `CausalCandidate` record exists for entities mentioned in the discovery's fragments.

### 5.2 CausalTrace Structure

```python
@dataclass
class CausalTrace:
    # Directional candidates that are relevant to this discovery
    candidates: list[CausalCandidateSummary]

    # Expectation violations relevant to the same entities
    related_violations: list[ViolationSummary]

    # Cross-reference: does a violation and a causal candidate point to the same pair?
    correlated_signals: list[CorrelatedSignal]

    # Epistemological caveat — always included
    caveat: str
        # Always: "Temporal precedence is a necessary but not sufficient condition for
        # causation. These candidates indicate consistent directional ordering, not
        # confirmed causal relationships. Alternative explanations include common causes,
        # instrumentation delay, and coincidental co-occurrence."
```

```python
@dataclass
class CausalCandidateSummary:
    causal_candidate_id: UUID
    entity_a_identifier: str    # presumed cause
    entity_a_domain: str
    entity_b_identifier: str    # presumed effect
    entity_b_domain: str

    # The key statistics
    mean_lag_seconds: float
    mean_lag_human: str         # e.g. "~14 minutes"
    directional_fraction: float
    sample_size: int
    confidence: float
    confidence_label: str       # HIGH | MEDIUM | LOW

    # How this candidate relates to the current discovery
    relevance_to_discovery: str
        # e.g. "ROUTER-22 (TRANSPORT) appears as entity in the triggering fragment.
        # ENB-4412 (RAN) appears in the bridge cluster. This candidate suggests
        # the transport event preceded the RAN event by ~14 minutes in 87% of
        # 31 co-occurring cases over the past 90 days."

    # Sample evidence pair (single representative example)
    example_evidence: Optional[CausalEvidenceExample]

@dataclass
class CausalEvidenceExample:
    ts_a: datetime
    ts_b: datetime
    lag_seconds: float
    state_key_a: str
    state_key_b: str
    fragment_a_excerpt: str     # raw_text[:150] of fragment A
    fragment_b_excerpt: str     # raw_text[:150] of fragment B

@dataclass
class ViolationSummary:
    violation_id: UUID
    entity_identifier: str
    entity_domain: str
    from_state: str
    to_state: str
    severity_bits: float
    violation_class: str
    expected_most_probable_state: str
    expected_most_probable_p: float
    observed_probability: float
    event_timestamp: datetime
    interpretation: str
        # e.g. "Entity TL-0087 (TRANSPORT) transitioned from LINK_DOWN:ALARM:MAJOR
        # to CASCADING_FAILURE:ALARM:CRITICAL. In 750 prior transitions from this
        # state, this has never occurred. Expected: RECOVERY:ALARM:CLEAR (89.3%
        # probability). Severity: 9.56 bits (MAJOR)."

@dataclass
class CorrelatedSignal:
    causal_candidate_id: UUID
    violation_id: UUID
    correlation_type: str
        # "SAME_ENTITY_PAIR" — violation and causal candidate involve the same two entities
        # "SHARED_ENTITY" — one entity appears in both
        # "TEMPORAL_OVERLAP" — violation occurred within the lag window of the candidate
    significance: str
        # Human-readable: "The VIOLATION_DISCOVERY on TL-0087 (CASCADING_FAILURE)
        # occurred at 14:32 UTC, within the mean lag window (842s ± 310s) of the
        # TRANSPORT→RAN causal candidate for ROUTER-22→ENB-4412. This temporal
        # alignment is consistent with the causal hypothesis."
```

---

## 6. Hypothesis Evolution Log

### 6.1 When Included

The `HypothesisEvolution` block is included when `discovery_registry.hypothesis_id` is non-null, i.e., when the Hypothesis Engine (D3.8) has generated a hypothesis for this discovery.

### 6.2 HypothesisEvolution Structure

```python
@dataclass
class HypothesisEvolution:
    hypothesis_id: UUID
    current_status: str         # proposed | testing | confirmed | refuted | retired
    current_confidence: float

    # The claim
    claim_text: str
    claim_summary: str
    failure_mode_profile: str

    # Generation provenance — full traceability of how this hypothesis was produced
    generation: HypothesisGeneration

    # Confidence timeline — every confidence change, in order
    confidence_timeline: list[ConfidenceTimelineEntry]

    # Evidence log — all supporting and contradicting evidence attached
    evidence_log: list[EvidenceLogEntry]

    # Condition status
    confirmation_conditions: list[ConditionStatus]
    refutation_conditions: list[ConditionStatus]

    # Status transitions
    status_history: list[StatusHistoryEntry]

    # Linkage
    parent_hypothesis_id: Optional[UUID]
    superseded_by: Optional[UUID]

@dataclass
class HypothesisGeneration:
    trigger_type: str           # "recurring_snap_pattern" | "surprise_escalation"
    generation_method: str      # "TSLAM_8B" | "TEMPLATE_FALLBACK"
    tslam_model_version: Optional[str]
    generation_latency_ms: Optional[int]

    # For TSLAM_8B generation: full traceability
    tslam_prompt_used: Optional[str]     # exact prompt sent
    tslam_raw_response: Optional[str]    # exact TSLAM output (before parsing)
    generation_quality: str             # "VALIDATED" | "VALIDATION_FAILED"

    # For recurring_snap_pattern trigger
    snap_cluster_size: Optional[int]
    snap_cluster_avg_score: Optional[float]
    snap_cluster_fragment_ids: Optional[list[UUID]]

    # For surprise_escalation trigger
    surprise_event_id: Optional[UUID]
    composite_surprise_at_trigger: Optional[float]

@dataclass
class ConfidenceTimelineEntry:
    timestamp: datetime
    old_confidence: float
    new_confidence: float
    delta: float                # new - old
    direction: str              # "INCREASE" | "DECREASE" | "NO_CHANGE"
    reason: str
        # "new_supporting_evidence: snap_decision <id> (DARK_EDGE, score=0.71)"
        # "new_contradicting_evidence: operator_input"
        # "time_decay: no new evidence for 48h"
        # "operator_override"
    evidence_id: Optional[UUID]

@dataclass
class EvidenceLogEntry:
    evidence_id: UUID
    evidence_type: str          # "snap_decision" | "surprise_event" | etc.
    source_id: UUID
    source_table: str
    relevance: str              # "supporting" | "contradicting" | "neutral"
    impact_on_confidence: float
    description: str            # human-readable summary
    fragment_ids: list[UUID]
    created_at: datetime

@dataclass
class ConditionStatus:
    condition_id: UUID
    description: str
    metric_expression: Optional[str]
    satisfied_or_triggered: bool
    satisfied_at: Optional[datetime]
    satisfying_evidence_ids: list[UUID]

@dataclass
class StatusHistoryEntry:
    timestamp: datetime
    old_status: str
    new_status: str
    reason: str
    triggered_by: str
```

---

## 7. Contradiction Resolution Log

### 7.1 When Included

The `ContradictionLog` is included when the hypothesis has `contradicting_evidence` entries, or when a `SURPRISE_DISCOVERY` has per-dimension surprises that point in different directions (e.g., semantic unusually high while topological unusually low).

### 7.2 ContradictionLog Structure

```python
@dataclass
class ContradictionLog:
    has_contradictions: bool

    # Dimension-level contradictions (SURPRISE_DISCOVERY)
    dimension_contradictions: list[DimensionContradiction]

    # Evidence-level contradictions (from hypothesis engine)
    evidence_contradictions: list[EvidenceContradiction]

    # System resolution: how did the scoring/hypothesis handle the contradiction?
    resolution_method: str
        # "WEIGHT_REDISTRIBUTION" — unavailable dimension excluded, weight redistributed
        # "COMPOSITE_AVERAGING" — contradicting dimensions averaged into composite score;
        #   net result depends on weights and magnitudes
        # "HYPOTHESIS_CONFIDENCE_DECAY" — contradicting evidence reduced confidence
        # "OPERATOR_PENDING" — no automated resolution; awaiting operator review
    resolution_explanation: str

@dataclass
class DimensionContradiction:
    dimension_a: str            # e.g. "semantic"
    score_a: float              # e.g. 0.82 (unusually HIGH)
    surprise_a: float           # e.g. 11.5 bits
    dimension_b: str            # e.g. "topological"
    score_b: float              # e.g. 0.12 (within normal range)
    surprise_b: float           # e.g. 1.2 bits

    contradiction_type: str
        # "HIGH_LOW_DIVERGENCE" — one dimension unusually high, another unusually low
        # "AVAILABILITY_MISMATCH" — one available, one masked out
    significance: str
        # e.g. "Semantic similarity (0.82, surprise=11.5 bits) is highly elevated while
        # topological similarity (0.12, surprise=1.2 bits) is normal. For DARK_EDGE
        # patterns, topology is expected to be the primary signal (base weight 30%).
        # This inversion — high semantic, low topological — suggests the fragments are
        # semantically related but structurally distant, which is the discovery signal."

@dataclass
class EvidenceContradiction:
    supporting_evidence_count: int
    contradicting_evidence_count: int
    net_confidence_impact: float    # sum of all evidence impacts
    most_significant_contradiction: Optional[EvidenceLogEntry]
    contradiction_summary: str
        # e.g. "3 supporting snap decisions contributed +0.06 confidence.
        # 1 contradicting operator input contributed -0.02 confidence.
        # Net: +0.04. The contradiction has not reversed the positive trajectory."
```

---

## 8. Provenance DAG Assembly Algorithm

### 8.1 Entry Point

The assembly algorithm is triggered by a `GET /api/v1/discoveries/{discovery_id}/explanation` request. It runs as a single async function that issues parallelised DB queries.

### 8.2 Assembly Steps

```
FUNCTION assemble_explanation(discovery_id, tenant_id) -> DiscoveryExplanation:

    # Step 1: Load discovery registry entry
    registry = SELECT * FROM discovery_registry
               WHERE id = :discovery_id AND tenant_id = :tenant_id

    IF registry is None: raise DiscoveryNotFound

    # Step 2: Load primary source record (parallel with step 3)
    primary_source = load_primary_source(registry.entry_type, registry.source_id)

    # Step 3: Load hypothesis (parallel with step 2)
    hypothesis = None
    IF registry.hypothesis_id is not None:
        hypothesis = load_hypothesis(registry.hypothesis_id)

    # Step 4: Build FlagReason
    flag_reason = build_flag_reason(registry.entry_type, primary_source)

    # Step 5: Build per-dimension scoring breakdown (SURPRISE_DISCOVERY only)
    snap_scoring = None
    IF registry.entry_type == 'SURPRISE_DISCOVERY':
        snap_decision = load_snap_decision(primary_source.snap_decision_id)
        snap_scoring = build_snap_scoring_explanation(primary_source, snap_decision)

    # Step 6: Build causal trace (VIOLATION_DISCOVERY, CAUSAL_CANDIDATE, or
    #         when causal candidates exist for discovery entities)
    causal_trace = None
    IF registry.entry_type IN ('VIOLATION_DISCOVERY', 'CAUSAL_CANDIDATE'):
        causal_trace = build_causal_trace(primary_source, tenant_id)
    ELSE:
        entities = extract_entity_ids_from(primary_source)
        candidates = load_causal_candidates_for_entities(entities, tenant_id)
        IF candidates:
            causal_trace = build_causal_trace_from_candidates(candidates, primary_source)

    # Step 7: Build hypothesis evolution
    hypothesis_evolution = None
    IF hypothesis is not None:
        hypothesis_evolution = build_hypothesis_evolution(hypothesis)

    # Step 8: Build contradiction log
    contradiction_log = build_contradiction_log(
        snap_scoring, hypothesis_evolution, registry.entry_type
    )

    # Step 9: Build provenance DAG
    provenance_dag = build_provenance_dag(
        registry, primary_source, snap_scoring,
        hypothesis, causal_trace
    )

    # Step 10: Build raw provenance refs
    raw_refs = collect_raw_provenance_refs(
        registry, primary_source, snap_scoring, hypothesis
    )

    RETURN DiscoveryExplanation(
        discovery_id=discovery_id,
        entry_type=registry.entry_type,
        severity=registry.severity,
        title=registry.title,
        detected_at=registry.detected_at,
        flag_reason=flag_reason,
        provenance_dag=provenance_dag,
        snap_scoring=snap_scoring,
        causal_trace=causal_trace,
        hypothesis_evolution=hypothesis_evolution,
        contradiction_log=contradiction_log,
        raw_provenance_refs=raw_refs,
    )
```

### 8.3 Parallelisation Strategy

Steps 2 and 3 (primary source + hypothesis load) are parallelised with `asyncio.gather()`. Steps 5, 6, 7 can also be parallelised once the primary source is available. The assembly function must not block on sequential queries where joins are avoidable.

```python
# Parallel load pattern
primary_source, hypothesis = await asyncio.gather(
    load_primary_source(entry_type, source_id),
    load_hypothesis(hypothesis_id) if hypothesis_id else asyncio.sleep(0),
)

snap_scoring_task = build_snap_scoring_explanation(...) if entry_type == 'SURPRISE_DISCOVERY' else None
causal_trace_task = build_causal_trace(...)
hypothesis_evolution_task = build_hypothesis_evolution(hypothesis) if hypothesis else None

results = await asyncio.gather(
    snap_scoring_task or _null(),
    causal_trace_task,
    hypothesis_evolution_task or _null(),
)
```

### 8.4 Data Freshness Guarantee

The explanation is assembled from a snapshot of the current DB state. It is NOT cached. Hypothesis confidence, evidence log, and condition status change as new evidence arrives. The `GET /explanation` endpoint always returns current state. Caching of explanation responses is the responsibility of the API gateway layer and must use TTL of at most 60 seconds.

---

## 9. API Response Structure

### 9.1 Endpoint

```
GET /api/v1/discoveries/{discovery_id}/explanation
```

Authentication: tenant-scoped JWT. The endpoint validates that the discovery belongs to the tenant in the JWT claims.

Query parameters:
- `depth`: `full` (default) | `summary` | `provenance_only`
  - `summary`: returns only `flag_reason` and `title`, not `snap_scoring` or `causal_trace`
  - `provenance_only`: returns only `provenance_dag` and `raw_provenance_refs`
  - `full`: returns the complete `DiscoveryExplanation`

### 9.2 Response Schema (JSON)

```json
{
  "discovery_id": "uuid",
  "tenant_id": "string",
  "entry_type": "SURPRISE_DISCOVERY | BRIDGE_DISCOVERY | VIOLATION_DISCOVERY | CAUSAL_CANDIDATE",
  "severity": "CRITICAL | HIGH | MEDIUM | LOW",
  "title": "string",
  "detected_at": "ISO8601",

  "flag_reason": {
    "mechanism": "string",
    "signal_type": "string",
    "plain_text": "string",
    "primary_metric_name": "string",
    "primary_metric_value": 0.0,
    "primary_metric_threshold": 0.0,
    "primary_metric_units": "string",
    "driving_dimensions": [
      {
        "dimension": "string",
        "score": 0.0,
        "surprise_bits": 0.0,
        "percentile_rank": 0.0,
        "available": true
      }
    ]
  },

  "provenance_dag": {
    "root_node_id": "string",
    "nodes": [
      {
        "node_id": "string",
        "node_type": "string",
        "source_table": "string",
        "source_id": "uuid",
        "label": "string",
        "timestamp": "ISO8601 or null",
        "summary": {}
      }
    ],
    "edges": [
      {
        "from_node_id": "string",
        "to_node_id": "string",
        "relationship": "string",
        "label": "string or null"
      }
    ]
  },

  "snap_scoring": {
    "snap_decision_id": "uuid",
    "fragment_a_id": "uuid",
    "fragment_b_id": "uuid",
    "failure_mode_profile": "string",
    "dimensions": [
      {
        "dimension": "string",
        "available": true,
        "unavailable_reason": null,
        "score": 0.0,
        "base_weight": 0.0,
        "adjusted_weight": 0.0,
        "contribution": 0.0,
        "surprise_bits": null,
        "surprise_percentile_rank": null,
        "interpretation": "string"
      }
    ],
    "raw_composite": 0.0,
    "temporal_modifier": 0.0,
    "final_score": 0.0,
    "threshold_applied": 0.0,
    "decision": "string",
    "weight_redistribution_occurred": false,
    "dimensions_unavailable": [],
    "weight_mass_redistributed": 0.0,
    "calibration_status": "string",
    "calibration_note": "string or null",
    "multiple_comparisons_k": 1,
    "sidak_correction_applied": false
  },

  "causal_trace": {
    "candidates": [
      {
        "causal_candidate_id": "uuid",
        "entity_a_identifier": "string",
        "entity_a_domain": "string",
        "entity_b_identifier": "string",
        "entity_b_domain": "string",
        "mean_lag_seconds": 0.0,
        "mean_lag_human": "string",
        "directional_fraction": 0.0,
        "sample_size": 0,
        "confidence": 0.0,
        "confidence_label": "string",
        "relevance_to_discovery": "string",
        "example_evidence": null
      }
    ],
    "related_violations": [
      {
        "violation_id": "uuid",
        "entity_identifier": "string",
        "entity_domain": "string",
        "from_state": "string",
        "to_state": "string",
        "severity_bits": 0.0,
        "violation_class": "string",
        "expected_most_probable_state": "string",
        "expected_most_probable_p": 0.0,
        "observed_probability": 0.0,
        "event_timestamp": "ISO8601",
        "interpretation": "string"
      }
    ],
    "correlated_signals": [],
    "caveat": "string"
  },

  "hypothesis_evolution": {
    "hypothesis_id": "uuid",
    "current_status": "string",
    "current_confidence": 0.0,
    "claim_text": "string",
    "claim_summary": "string",
    "failure_mode_profile": "string",
    "generation": {
      "trigger_type": "string",
      "generation_method": "string",
      "tslam_model_version": "string or null",
      "generation_latency_ms": 0,
      "generation_quality": "string",
      "snap_cluster_size": null,
      "snap_cluster_avg_score": null,
      "surprise_event_id": null,
      "composite_surprise_at_trigger": null
    },
    "confidence_timeline": [
      {
        "timestamp": "ISO8601",
        "old_confidence": 0.0,
        "new_confidence": 0.0,
        "delta": 0.0,
        "direction": "INCREASE",
        "reason": "string",
        "evidence_id": "uuid or null"
      }
    ],
    "evidence_log": [],
    "confirmation_conditions": [],
    "refutation_conditions": [],
    "status_history": []
  },

  "contradiction_log": {
    "has_contradictions": false,
    "dimension_contradictions": [],
    "evidence_contradictions": [],
    "resolution_method": "string",
    "resolution_explanation": "string"
  },

  "raw_provenance_refs": [
    {
      "ref_type": "string",
      "table": "string",
      "id": "uuid",
      "role": "string"
    }
  ]
}
```

### 9.3 Discovery List Endpoint

```
GET /api/v1/discoveries
```

Query parameters:
- `tenant_id`: required (from JWT, not query param — included here for documentation)
- `status`: `OPEN` | `ACKNOWLEDGED` | `RESOLVED` | `DISMISSED` | `all` (default: `OPEN`)
- `severity`: `CRITICAL` | `HIGH` | `MEDIUM` | `LOW` | `all` (default: all)
- `entry_type`: filter by discovery type (optional)
- `from`: ISO8601 timestamp lower bound for `detected_at`
- `to`: ISO8601 timestamp upper bound for `detected_at`
- `limit`: default 50, max 200
- `offset`: default 0

Response: paginated list of discovery registry entries with `flag_reason` but without full explanation blocks (`snap_scoring`, `causal_trace`, etc.). Operators drill into individual discoveries for the full explanation.

### 9.4 Batch Explanation Endpoint

```
POST /api/v1/discoveries/batch-explain
Body: { "discovery_ids": ["uuid", ...], "depth": "summary" }
```

Returns an array of `DiscoveryExplanation` objects at `depth=summary`. Used for bulk review workflows. Maximum 20 IDs per request.

---

## 10. Concrete Walkthrough: SURPRISE_DISCOVERY Explanation

This section traces a complete explanation assembly for the telecom example from the Surprise Engine spec (D1.1 Section 10).

### 10.1 Scenario

Tenant `telco2`. DARK_EDGE failure mode. Fragment pair: `eNB-4412` (S1_SETUP_FAILURE) vs `eNB-7803` (X2_HANDOVER_FAILURE). Final snap score: 0.68. Composite surprise: 12.5 bits. Surprise threshold: 8.3 bits. Escalation type: `DISCOVERY`.

### 10.2 FlagReason Output

```json
{
  "mechanism": "SURPRISE_ENGINE",
  "signal_type": "STATISTICAL_ANOMALY",
  "plain_text": "This snap score (0.68) is in the top 2% of most surprising scores for DARK_EDGE patterns in tenant telco2. The score fell in a histogram bin (0.68–0.70) with only 0.018% probability mass, compared to the normal peak distribution around 0.35 ± 0.08. The surprise value (12.5 bits) exceeds the 98th-percentile threshold (8.3 bits) derived from the last ~848 DARK_EDGE evaluations. Two dimensions drove the surprise: semantic similarity (0.82) is unusually high for DARK_EDGE patterns in this tenant, and operational similarity (0.78) is similarly elevated.",
  "primary_metric_name": "composite_surprise_bits",
  "primary_metric_value": 12.5,
  "primary_metric_threshold": 8.3,
  "primary_metric_units": "bits",
  "driving_dimensions": [
    {
      "dimension": "semantic",
      "score": 0.82,
      "surprise_bits": 11.5,
      "percentile_rank": 0.99,
      "available": true
    },
    {
      "dimension": "operational",
      "score": 0.78,
      "surprise_bits": 9.6,
      "percentile_rank": 0.97,
      "available": true
    }
  ]
}
```

### 10.3 SnapScoringExplanation Output (five dimensions, never blended)

```json
{
  "snap_decision_id": "<uuid>",
  "fragment_a_id": "<eNB-4412-fragment-uuid>",
  "fragment_b_id": "<eNB-7803-fragment-uuid>",
  "failure_mode_profile": "DARK_EDGE",
  "dimensions": [
    {
      "dimension": "semantic",
      "available": true,
      "unavailable_reason": null,
      "score": 0.82,
      "base_weight": 0.15,
      "adjusted_weight": 0.15,
      "contribution": 0.123,
      "surprise_bits": 11.5,
      "surprise_percentile_rank": 0.99,
      "interpretation": "Semantic similarity 0.82 is unusually HIGH for DARK_EDGE patterns (typical range 0.20–0.45 in this tenant). This is the primary driver of the high composite surprise. Both fragments describe RAN signaling failures, producing high semantic overlap despite the eNBs being in different tracking areas."
    },
    {
      "dimension": "topological",
      "available": true,
      "unavailable_reason": null,
      "score": 0.12,
      "base_weight": 0.30,
      "adjusted_weight": 0.30,
      "contribution": 0.036,
      "surprise_bits": 1.2,
      "surprise_percentile_rank": 0.28,
      "interpretation": "Topological similarity 0.12 is within normal range for DARK_EDGE patterns (typical range 0.05–0.30 in this tenant). The two eNBs are in different tracking areas with no direct topological relationship, which is consistent with a DARK_EDGE discovery target — the connection is unknown precisely because the topology does not reflect it."
    },
    {
      "dimension": "temporal",
      "available": true,
      "unavailable_reason": null,
      "score": 0.71,
      "base_weight": 0.10,
      "adjusted_weight": 0.10,
      "contribution": 0.071,
      "surprise_bits": null,
      "surprise_percentile_rank": null,
      "interpretation": "Temporal pattern similarity 0.71 is within normal range. Both alarms occurred during the same maintenance window, which is reflected in the temporal embedding. This dimension always available (deterministic computation, no LLM dependency)."
    },
    {
      "dimension": "operational",
      "available": true,
      "unavailable_reason": null,
      "score": 0.78,
      "base_weight": 0.15,
      "adjusted_weight": 0.15,
      "contribution": 0.117,
      "surprise_bits": 9.6,
      "surprise_percentile_rank": 0.97,
      "interpretation": "Operational similarity 0.78 is unusually HIGH for DARK_EDGE patterns (typical range 0.30–0.50 in this tenant). Same vendor, same software version, same change record. This secondary surprise driver indicates a shared operational context between two structurally unrelated eNBs."
    },
    {
      "dimension": "entity_overlap",
      "available": true,
      "unavailable_reason": null,
      "score": 0.08,
      "base_weight": 0.30,
      "adjusted_weight": 0.30,
      "contribution": 0.024,
      "surprise_bits": null,
      "surprise_percentile_rank": null,
      "interpretation": "Entity overlap (Jaccard) 0.08 is low — different eNBs with few shared entity references. This is expected for a DARK_EDGE pattern where the connection is not yet captured in the topology graph."
    }
  ],
  "raw_composite": 0.371,
  "temporal_modifier": 0.95,
  "final_score": 0.352,
  "threshold_applied": 0.72,
  "decision": "NEAR_MISS",
  "weight_redistribution_occurred": false,
  "dimensions_unavailable": [],
  "weight_mass_redistributed": 0.0,
  "calibration_status": "INITIAL_ESTIMATE",
  "calibration_note": "DARK_EDGE profile weights are initial estimates. Empirical validation requires 500+ labeled outcomes. Until validated, treat weight contributions as approximations of relative importance.",
  "multiple_comparisons_k": 2,
  "sidak_correction_applied": true
}
```

### 10.4 Provenance DAG (simplified)

```
DISCOVERY (id: <dr-uuid>)
  └─[TRIGGERED_BY]─> SURPRISE_EVENT (id: <se-uuid>)
       └─[PRODUCED_BY]─> SNAP_DECISION (id: <sd-uuid>)
            ├─[SCORED_AGAINST]─> FRAGMENT (eNB-4412 S1_SETUP_FAILURE, id: <fa-uuid>)
            └─[SCORED_AGAINST]─> FRAGMENT (eNB-7803 X2_HANDOVER_FAILURE, id: <fb-uuid>)
```

If a hypothesis was generated:
```
DISCOVERY
  ├─[TRIGGERED_BY]─> SURPRISE_EVENT
  │    └─[PRODUCED_BY]─> SNAP_DECISION
  │         ├─[SCORED_AGAINST]─> FRAGMENT (eNB-4412)
  │         └─[SCORED_AGAINST]─> FRAGMENT (eNB-7803)
  └─[TRIGGERED_BY]─> HYPOTHESIS (id: <h-uuid>)
       ├─[SUPPORTED_BY]─> SNAP_DECISION (subsequent evidence)
       └─[SUPPORTED_BY]─> SNAP_DECISION (subsequent evidence)
```

---

## 11. Concrete Walkthrough: BRIDGE_DISCOVERY Explanation

For the bridge detection example (T3.1 Section 6), the explanation focuses on the structural finding rather than per-dimension scoring.

### 11.1 FlagReason Output

```json
{
  "mechanism": "BRIDGE_DETECTION",
  "signal_type": "TOPOLOGY_BRIDGE",
  "plain_text": "Fragment F12 (site power brownout impact assessment) is the sole connecting fragment between two otherwise-disjoint clusters in the accumulation graph. Removing this fragment would split a 12-node cluster into a 6-node power-grid cluster (TRANSPORT/POWER domain) and a 5-node RAN cluster (RAN domain). Fragment F12 lies on 27 of 55 shortest paths between node pairs (betweenness centrality: 0.455), well above the discovery threshold of 0.30. It spans 3 entity domains: SITE, TRANSPORT, and RAN — indicating a cross-domain linkage invisible to pairwise scoring.",
  "primary_metric_name": "betweenness_centrality",
  "primary_metric_value": 0.455,
  "primary_metric_threshold": 0.30,
  "primary_metric_units": "normalized_betweenness",
  "driving_dimensions": []
}
```

The `ProvenanceDAG` for a bridge discovery includes sub-component nodes:

```
DISCOVERY
  └─[TRIGGERED_BY]─> BRIDGE_DISCOVERY (F12, BC=0.455)
       ├─[BRIDGE_CONNECTS]─> CLUSTER (power-grid-cluster-NRH04, 6 fragments, TRANSPORT/POWER)
       │    └─[CONTAINS]─> FRAGMENT (F1..F6)
       └─[BRIDGE_CONNECTS]─> CLUSTER (ran-cluster-ENB2241, 5 fragments, RAN)
            └─[CONTAINS]─> FRAGMENT (F7..F11)
```

---

## 12. Storage for Explanation Metadata

The explanation assembly is stateless — it assembles from existing tables on demand. However, two pieces of metadata are stored:

### 12.1 Explanation Audit Log

```sql
CREATE TABLE explanation_audit_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       VARCHAR(64) NOT NULL,
    discovery_id    UUID NOT NULL,
    requested_by    VARCHAR(200) NOT NULL,   -- operator identifier from JWT
    requested_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    depth           VARCHAR(20) NOT NULL,    -- full | summary | provenance_only
    assembly_duration_ms INTEGER NOT NULL,  -- wall-clock time for assembly
    dag_node_count  INTEGER,
    dag_edge_count  INTEGER
);

CREATE INDEX ix_eal_tenant_disc
    ON explanation_audit_log (tenant_id, discovery_id, requested_at DESC);
```

**Purpose**: Audit trail for who requested which explanation and when. Assembly duration provides observability for explanation query performance. No explanation content is stored here — explanations are assembled on demand from source tables.

### 12.2 discovery_registry Population

The `discovery_registry` table (Section 2.2) must be populated when source records are created. This is done by event hooks:

| Source Event | Hook | Populates `discovery_registry` |
|---|---|---|
| `surprise_event` INSERT with `escalation_type='DISCOVERY'` | Post-insert trigger in surprise engine | Yes |
| `bridge_discovery` INSERT with `classification='BRIDGE_DISCOVERY'` | Post-insert in bridge detector | Yes |
| `expectation_violation` INSERT with `violation_class IN ('CRITICAL','MAJOR')` | Post-insert in violation detector | Yes |
| `causal_candidate` INSERT with `confidence_label IN ('HIGH','MEDIUM')` | Post-insert in causal direction job | Yes |
| `hypothesis` creation | Post-creation in hypothesis engine | Updates `discovery_registry.hypothesis_id` for linked discovery |

The `title` for each entry type is generated deterministically at insertion:

| Entry Type | Title Template |
|---|---|
| `SURPRISE_DISCOVERY` | `"[{failure_mode}] Surprising snap score ({score:.2f}, {surprise:.1f} bits) — {fragment_count} fragments"` |
| `BRIDGE_DISCOVERY` | `"[{severity}] Bridge fragment across {n} entity domains connecting {sub_a_domain}({n_a}) and {sub_b_domain}({n_b}) clusters"` |
| `VIOLATION_DISCOVERY` | `"[{violation_class}] {entity_identifier} ({domain}): unexpected {to_state} from {from_state} ({severity_bits:.1f} bits)"` |
| `CAUSAL_CANDIDATE` | `"[{confidence_label}] {entity_a} ({domain_a}) → {entity_b} ({domain_b}): {mean_lag_human}, {directional_fraction:.0%} directional, n={sample_size}"` |

---

## 13. Invariants

| ID | Statement | Enforcement |
|---|---|---|
| EXP-INV-1 | Every `DiscoveryExplanation` contains a non-null `flag_reason` | Assembly function raises if `flag_reason` cannot be built — this would indicate a source table inconsistency |
| EXP-INV-2 | `snap_scoring.dimensions` always contains exactly 5 entries (one per dimension) | Assembly populates all five; unavailable dimensions get `available=False`, `score=None` |
| EXP-INV-3 | `DimensionBreakdown.contribution` is null iff `available=False` | Contribution is `adjusted_weight * score`; if score is null, contribution is null |
| EXP-INV-4 | `sum(contribution for d in dimensions if d.available)` == `raw_composite` (within float tolerance 1e-6) | Verified during assembly; if check fails, an EXP-ASSEMBLY-ERROR metric is emitted and the discrepancy is included in the response |
| EXP-INV-5 | `CausalTrace.caveat` is always populated (never null) | Hardcoded string in assembly function |
| EXP-INV-6 | `HypothesisEvolution.generation.tslam_prompt_used` is never returned in `depth=summary` responses | Depth filter strips TSLAM prompt and raw response for summary depth |
| EXP-INV-7 | All explanation queries include `tenant_id` in every WHERE clause | Assembly function passes `tenant_id` to every sub-query; no cross-tenant joins |
| EXP-INV-8 | `discovery_registry` has exactly one entry per `(tenant_id, entry_type, source_id)` | UNIQUE constraint on the registry table |
| EXP-INV-9 | `explanation_audit_log` records every explanation request | Audit log INSERT is in the same transaction as the API response serialisation |
| EXP-INV-10 | `SnapScoringExplanation` is non-null if and only if `entry_type = 'SURPRISE_DISCOVERY'` | Assembly conditionally builds snap scoring based on entry type |

---

## 14. Computed Fields Not Stored Elsewhere

The following fields are computed during explanation assembly from stored provenance, not stored independently:

| Field | Source Data | Computation |
|---|---|---|
| `DimensionBreakdown.interpretation` | `score`, `surprise_bits`, historical percentile from `surprise_distribution_state` | Rule-based text (no LLM) per Section 4.3 |
| `DimensionBreakdown.surprise_percentile_rank` | `surprise_bits`, `dimension_surprises` from `surprise_event`, `surprise_distribution_state` histogram bins | Cumulative distribution function over histogram bins |
| `CausalCandidateSummary.mean_lag_human` | `mean_lag_seconds` | Deterministic: `{n}h {m}m` or `~{n} minutes` |
| `CausalCandidateSummary.relevance_to_discovery` | `entity_a_identifier`, `entity_b_identifier` cross-referenced against discovery fragment entity refs | Entity intersection check |
| `ContradictionLog.resolution_explanation` | `weight_redistribution_occurred`, `evidence_contradictions` | Rule-based text |
| `FlagReason.plain_text` | All primary source fields | Rule-based text, not LLM |
| `ViolationSummary.interpretation` | `from_state`, `to_state`, `total_from_count`, `expected_most_probable_state`, `expected_most_probable_p`, `severity_bits`, `violation_class` | Rule-based text per Section 5.2 |
| `ProvenanceNode.label` | `node_type` + source record fields | Rule-based label generation |

None of these computed fields require a TSLAM call. The explanation layer operates without LLM dependency.

---

## 15. Files Changed

| File | Change | Status |
|---|---|---|
| `backend/app/models/abeyance_orm.py` | Add `DiscoveryRegistryORM`, `ExplanationAuditLogORM` | Modify |
| `backend/app/services/abeyance/explainability.py` | New file — `ExplanationAssembler` class | New |
| `backend/app/api/v1/discoveries.py` | New file — GET/LIST/BATCH discovery and explanation endpoints | New |
| `backend/app/services/abeyance/surprise_engine.py` | Add post-insert hook to populate `discovery_registry` | Modify |
| `backend/app/services/abeyance/bridge_detector.py` | Add post-insert hook to populate `discovery_registry` | Modify |
| `backend/app/services/abeyance/violation_detector.py` | Add post-insert hook to populate `discovery_registry` | Modify |
| `backend/app/services/abeyance/causal_direction.py` | Add post-insert hook to populate `discovery_registry` | Modify |
| `backend/app/services/abeyance/hypothesis_engine.py` | Add hook to update `discovery_registry.hypothesis_id` on hypothesis creation | Modify |
| `alembic/versions/<new>.py` | Migration: create `discovery_registry`, `explanation_audit_log` | New |

No changes to snap scoring, embedding, or enrichment paths.

---

Generated: 2026-03-16 | Task T6.1 | Abeyance Memory v3.0 | Explainability Layer
