# Hypothesis Generation Engine -- Discovery Mechanism #8

**Task**: D3.8 -- Hypothesis Generation Engine
**Version**: 3.0
**Date**: 2026-03-16
**Status**: Specification
**Tier**: 3 (Reasoning -- requires TSLAM-8B text generation)
**Depends On**: T1.1 (TSLAM Serving), T1.4 (Snap Scoring), D1.1 (Surprise Engine)

---

## 1. Problem Statement

The Abeyance Memory subsystem detects recurring snap patterns and surprising score anomalies. These signals are currently terminal -- they produce events that operators must interpret manually. There is no mechanism to convert a recurring pattern into a **falsifiable claim** that the system can track, accumulate evidence for, and ultimately confirm or refute.

The hypothesis generation engine fills this gap. It takes recurring snap patterns (from the accumulation graph) and surprise-triggered escalations (from D1.1) as inputs, uses TSLAM-8B to generate natural-language falsifiable claims, and manages the full lifecycle of each hypothesis from proposal through confirmation or refutation.

**What this is**: A TSLAM-8B-powered reasoning layer that converts statistical patterns into structured, falsifiable hypotheses with explicit confirmation and refutation conditions.

**What this is NOT**: It is not the snap engine (T1.4), not the surprise engine (D1.1), and not the TSLAM serving layer (T1.1). It consumes outputs from all three.

---

## 2. Hypothesis Object Schema

The hypothesis object replaces the placeholder `hypothesis_id` UUID label with a full structured object.

### 2.1 Core Schema

```python
@dataclass
class Hypothesis:
    # Identity
    hypothesis_id: UUID
    tenant_id: str

    # Claim
    claim_text: str                          # Natural language falsifiable claim
    claim_summary: str                       # One-line summary (<120 chars)
    failure_mode_profile: str                # DARK_EDGE, DARK_NODE, etc.

    # Falsifiability conditions
    confirmation_conditions: list[ConfirmationCondition]
    refutation_conditions: list[RefutationCondition]

    # Confidence
    confidence: float                        # [0.0, 1.0] -- current confidence level
    confidence_history: list[ConfidenceUpdate]  # timestamped confidence changes

    # Evidence
    supporting_evidence: list[EvidenceRecord]
    contradicting_evidence: list[EvidenceRecord]

    # Lifecycle
    status: str                              # proposed | testing | confirmed | refuted | retired
    status_history: list[StatusTransition]

    # Provenance
    generation_trigger: GenerationTrigger    # what caused this hypothesis
    tslam_prompt_used: str                   # exact prompt sent to TSLAM
    tslam_raw_response: str                  # exact TSLAM output
    tslam_model_version: str                 # "TSLAM-8B" or "TSLAM-4B"
    tslam_backend: str                       # "vllm" or "llama_cpp"
    generation_latency_ms: int               # wall-clock time for TSLAM call

    # Timestamps
    created_at: datetime                     # UTC
    updated_at: datetime                     # UTC
    confirmed_at: Optional[datetime]
    refuted_at: Optional[datetime]
    retired_at: Optional[datetime]

    # Linkage
    parent_hypothesis_id: Optional[UUID]     # if this refines a prior hypothesis
    superseded_by: Optional[UUID]            # if replaced by a better hypothesis
```

### 2.2 Supporting Types

```python
@dataclass
class ConfirmationCondition:
    condition_id: UUID
    description: str                         # Natural language: "If 3+ more eNB pairs in
                                             # different tracking areas show S1/X2 co-failure
                                             # during maintenance windows"
    metric_expression: Optional[str]         # Machine-evaluable condition (optional)
    satisfied: bool
    satisfied_at: Optional[datetime]
    satisfying_evidence_ids: list[UUID]      # evidence records that satisfied this

@dataclass
class RefutationCondition:
    condition_id: UUID
    description: str                         # "If the next 50 S1_SETUP_FAILURE alarms from
                                             # these tracking areas show no X2 correlation"
    metric_expression: Optional[str]
    triggered: bool
    triggered_at: Optional[datetime]
    triggering_evidence_ids: list[UUID]

@dataclass
class EvidenceRecord:
    evidence_id: UUID
    hypothesis_id: UUID
    tenant_id: str
    evidence_type: str                       # "snap_decision" | "surprise_event" |
                                             # "accumulation_cluster" | "operator_input"
    source_id: UUID                          # FK to snap_decision_log, surprise_event, etc.
    source_table: str                        # table name for provenance
    relevance: str                           # "supporting" | "contradicting" | "neutral"
    impact_on_confidence: float              # delta applied to confidence
    description: str                         # human-readable summary of what this evidence shows
    fragment_ids: list[UUID]                 # fragments involved
    created_at: datetime

@dataclass
class ConfidenceUpdate:
    timestamp: datetime
    old_confidence: float
    new_confidence: float
    reason: str                              # "new_supporting_evidence" | "new_contradicting_evidence"
                                             # | "time_decay" | "operator_override"
    evidence_id: Optional[UUID]              # null for time_decay

@dataclass
class StatusTransition:
    timestamp: datetime
    old_status: str
    new_status: str
    reason: str
    triggered_by: str                        # "evidence_accumulation" | "confidence_threshold"
                                             # | "operator_action" | "time_expiry"

@dataclass
class GenerationTrigger:
    trigger_type: str                        # "recurring_snap_pattern" | "surprise_escalation"
    # For recurring_snap_pattern:
    snap_cluster_fragment_ids: Optional[list[UUID]]
    snap_cluster_size: Optional[int]
    snap_cluster_avg_score: Optional[float]
    # For surprise_escalation:
    surprise_event_id: Optional[UUID]
    composite_surprise: Optional[float]
```

---

## 3. Generation Triggers

Hypothesis generation is triggered by two sources. Both require a minimum evidence threshold before TSLAM is invoked -- TSLAM calls are expensive and should not fire on noise.

### 3.1 Trigger 1: Recurring Snap Pattern

The accumulation graph tracks clusters of fragments connected by snap/affinity relationships. When a cluster grows beyond a threshold, it signals a recurring pattern.

**Trigger condition**:

```
cluster_size >= MIN_CLUSTER_SIZE
AND cluster has grown by >= GROWTH_DELTA fragments in the last GROWTH_WINDOW
AND no active hypothesis already covers this cluster
```

| Parameter | Value | Rationale |
|---|---|---|
| `MIN_CLUSTER_SIZE` | 5 | Minimum fragment cluster to indicate recurrence. Below 5, the pattern may be coincidental. |
| `GROWTH_DELTA` | 2 | At least 2 new fragments added recently, confirming the pattern is active. |
| `GROWTH_WINDOW` | 24 hours | Recency filter -- stale clusters that stopped growing do not trigger. |

**Deduplication**: Before triggering, check `hypothesis` table for any hypothesis with `status IN ('proposed', 'testing')` whose `generation_trigger.snap_cluster_fragment_ids` overlaps >= 50% with the current cluster. If found, route new evidence to the existing hypothesis instead of generating a new one.

### 3.2 Trigger 2: Surprise-Escalated Discovery

When the surprise engine (D1.1) emits a `SurpriseEvent` with `escalation_type = 'DISCOVERY'`, it is eligible for hypothesis generation.

**Trigger condition**:

```
surprise_event.escalation_type == 'DISCOVERY'
AND surprise_event.composite_surprise >= HYPOTHESIS_SURPRISE_FLOOR
AND no active hypothesis already covers the same fragment pair + failure mode
```

| Parameter | Value | Rationale |
|---|---|---|
| `HYPOTHESIS_SURPRISE_FLOOR` | 8.0 bits | Only highly surprising events justify TSLAM invocation. 8.0 bits = P(bin) < 0.4%, well above the 2% escalation threshold. |

**Deduplication**: Check for existing hypotheses where the `new_fragment_id` or `candidate_fragment_id` from the surprise event already appears in `supporting_evidence[].fragment_ids`.

### 3.3 Trigger Evaluation Frequency

Triggers are evaluated:
- **Recurring snap pattern**: After each accumulation graph update cycle (post-snap-scoring for each incoming fragment).
- **Surprise escalation**: Immediately upon receiving a `DISCOVERY` surprise event from the surprise engine's discovery queue.

Both paths converge into the hypothesis generation pipeline (Section 4).

---

## 4. TSLAM-8B Prompt Template

### 4.1 Prompt Structure

The prompt provides TSLAM with structured context about the snap pattern and asks it to generate a falsifiable hypothesis.

```
<|begin_of_text|><|start_header_id|>system<|end_header_id|>

You are a network operations analyst examining patterns in telemetry data from a telecommunications network. Your task is to formulate a falsifiable hypothesis from the evidence provided.

Requirements:
1. State a clear, specific claim about what is happening in the network.
2. The claim must be falsifiable -- it must be possible to prove it wrong.
3. Provide exactly 2-3 confirmation conditions: specific observable outcomes that would increase confidence in the claim.
4. Provide exactly 2-3 refutation conditions: specific observable outcomes that would disprove the claim.
5. Assign an initial confidence score between 0.1 and 0.5 (low confidence -- this is a new hypothesis).

Respond in JSON format only. No commentary outside the JSON block.<|eot_id|><|start_header_id|>user<|end_header_id|>

FAILURE MODE: {failure_mode_profile}
PATTERN TYPE: {trigger_type}
FRAGMENT COUNT: {cluster_size_or_pair_count}

FRAGMENT SUMMARIES:
{fragment_summaries}

SNAP SCORES:
{snap_score_summaries}

ENTITY OVERLAP:
Shared entities: {shared_entities}
Unique to group A: {unique_entities_a}
Unique to group B: {unique_entities_b}

TEMPORAL CONTEXT:
Time range: {time_range_start} to {time_range_end}
Temporal pattern: {temporal_pattern_description}

DIMENSIONAL SURPRISE (if applicable):
{dimension_surprise_summary}

Formulate a falsifiable hypothesis about what this pattern indicates.<|eot_id|><|start_header_id|>assistant<|end_header_id|>
```

### 4.2 Expected Response Schema

TSLAM is prompted to respond in JSON. The `TSLAMService.generate_structured()` method (from T1.1) parses this with schema validation.

```json
{
  "claim": "string -- the falsifiable claim",
  "claim_summary": "string -- one line, <120 chars",
  "initial_confidence": 0.3,
  "confirmation_conditions": [
    {
      "description": "string -- what would confirm this",
      "metric_hint": "string or null -- optional machine-evaluable expression"
    }
  ],
  "refutation_conditions": [
    {
      "description": "string -- what would disprove this",
      "metric_hint": "string or null"
    }
  ]
}
```

**Validation rules applied to TSLAM output**:
1. `claim` must be non-empty and <= 1000 characters.
2. `claim_summary` must be non-empty and <= 120 characters.
3. `initial_confidence` must be in `[0.1, 0.5]`. Values outside this range are clamped.
4. `confirmation_conditions` must have 2-3 entries.
5. `refutation_conditions` must have 2-3 entries.
6. All condition `description` fields must be non-empty.

If validation fails, the raw TSLAM output is logged to `tslam_raw_response`, the hypothesis is created with `status = 'proposed'` and a flag `generation_quality = 'VALIDATION_FAILED'`, and the claim fields are populated with a template fallback (see Section 4.3).

### 4.3 Template Fallback

If TSLAM output fails validation or TSLAM is unavailable, a deterministic template generates the hypothesis:

```
claim_text: "Recurring {failure_mode_profile} pattern detected across {N} fragments
             involving entities [{entity_list}] between {time_start} and {time_end}.
             Requires investigation."
claim_summary: "{failure_mode_profile}: {N} fragments, {entity_count} shared entities"
initial_confidence: 0.15
confirmation_conditions: [
    "Additional fragments matching this pattern appear within 48 hours",
    "Operator confirms the involved entities are operationally related"
]
refutation_conditions: [
    "No new matching fragments appear within 7 days",
    "Operator marks pattern as coincidental"
]
```

This ensures the hypothesis pipeline never stalls due to TSLAM unavailability. Template-generated hypotheses are tagged `generation_method = 'TEMPLATE_FALLBACK'` for filtering.

### 4.4 Context Assembly

The `{fragment_summaries}` placeholder is populated by extracting key fields from each fragment in the cluster:

```python
def assemble_fragment_summary(fragment) -> str:
    return (
        f"Fragment {fragment.fragment_id} [{fragment.failure_mode}]:\n"
        f"  Source: {fragment.source_type} / {fragment.source_identifier}\n"
        f"  Time: {fragment.event_timestamp.isoformat()}\n"
        f"  Entities: {', '.join(fragment.entity_refs)}\n"
        f"  Text excerpt: {fragment.raw_text[:200]}"
    )
```

The total prompt is capped at 3000 tokens input to stay within the `--max-model-len 4096` budget (leaving ~1000 tokens for the response). If the cluster has more fragments than fit in 3000 tokens, the most recent `MAX_PROMPT_FRAGMENTS` (default: 8) are included, with a note indicating how many were omitted.

---

## 5. Hypothesis Lifecycle

### 5.1 State Machine

```
                                    +---> confirmed ---> retired
                                    |
    proposed ---> testing ---+
                                    |
                                    +---> refuted ----> retired
                                    |
                                    +---> retired (time expiry)
```

**Valid transitions**:

| From | To | Trigger |
|---|---|---|
| `proposed` | `testing` | First evidence arrives OR operator approves for testing |
| `proposed` | `retired` | No evidence within `PROPOSED_TTL` (default: 72 hours) |
| `testing` | `confirmed` | Confidence >= `CONFIRMATION_THRESHOLD` AND >= 1 confirmation condition satisfied |
| `testing` | `refuted` | Confidence <= `REFUTATION_THRESHOLD` OR any refutation condition triggered |
| `testing` | `retired` | No new evidence within `TESTING_TTL` (default: 14 days) |
| `confirmed` | `retired` | Operator action OR `CONFIRMED_TTL` (default: 90 days) exceeded |
| `refuted` | `retired` | Automatic after `REFUTED_RETENTION` (default: 30 days) |

**Invalid transitions**: No backwards transitions. A `confirmed` hypothesis cannot go back to `testing`. If new contradicting evidence emerges for a `confirmed` hypothesis, a NEW hypothesis is generated that references the original as `parent_hypothesis_id`.

### 5.2 Lifecycle Parameters

| Parameter | Default | Configurable | Rationale |
|---|---|---|---|
| `CONFIRMATION_THRESHOLD` | 0.75 | Yes (per-tenant) | Confidence must reach 0.75 with at least one confirmation condition satisfied |
| `REFUTATION_THRESHOLD` | 0.10 | Yes (per-tenant) | Confidence drops below 0.10 -- effectively disproven |
| `PROPOSED_TTL` | 72 hours | Yes | Hypotheses without any evidence within 3 days are stale |
| `TESTING_TTL` | 14 days | Yes | Hypotheses without new evidence for 2 weeks are stale |
| `CONFIRMED_TTL` | 90 days | Yes | Confirmed hypotheses age out after 3 months unless renewed |
| `REFUTED_RETENTION` | 30 days | Yes | Refuted hypotheses kept for 30 days for audit, then retired |
| `CONFIDENCE_DECAY_RATE` | 0.01/day | Yes | Daily confidence decay when no new evidence arrives |

### 5.3 Status Transition Evaluation

Status transitions are evaluated at two points:
1. **On evidence arrival**: When new evidence is attached to a hypothesis (Section 6), the lifecycle evaluator checks transition conditions.
2. **Periodic sweep**: A background task runs every `LIFECYCLE_SWEEP_INTERVAL` (default: 1 hour) to check TTL expiry and apply confidence decay.

```
FUNCTION evaluate_transitions(hypothesis):

    IF hypothesis.status == 'proposed':
        IF len(hypothesis.supporting_evidence) + len(hypothesis.contradicting_evidence) > 0:
            transition(hypothesis, 'proposed', 'testing', 'evidence_accumulation')
        ELIF now() - hypothesis.created_at > PROPOSED_TTL:
            transition(hypothesis, 'proposed', 'retired', 'time_expiry')

    ELIF hypothesis.status == 'testing':
        IF hypothesis.confidence >= CONFIRMATION_THRESHOLD
           AND any(c.satisfied for c in hypothesis.confirmation_conditions):
            transition(hypothesis, 'testing', 'confirmed', 'confidence_threshold')
            hypothesis.confirmed_at = now()
        ELIF hypothesis.confidence <= REFUTATION_THRESHOLD:
            transition(hypothesis, 'testing', 'refuted', 'confidence_threshold')
            hypothesis.refuted_at = now()
        ELIF any(r.triggered for r in hypothesis.refutation_conditions):
            transition(hypothesis, 'testing', 'refuted', 'evidence_accumulation')
            hypothesis.refuted_at = now()
        ELIF now() - hypothesis.updated_at > TESTING_TTL:
            transition(hypothesis, 'testing', 'retired', 'time_expiry')

    ELIF hypothesis.status == 'confirmed':
        IF now() - hypothesis.confirmed_at > CONFIRMED_TTL:
            transition(hypothesis, 'confirmed', 'retired', 'time_expiry')
            hypothesis.retired_at = now()

    ELIF hypothesis.status == 'refuted':
        IF now() - hypothesis.refuted_at > REFUTED_RETENTION:
            transition(hypothesis, 'refuted', 'retired', 'time_expiry')
            hypothesis.retired_at = now()
```

---

## 6. Evidence Accumulation

### 6.1 Evidence Sources

New snap decisions and surprise events are evaluated against active hypotheses (status `proposed` or `testing`) to determine if they constitute evidence.

| Source | How Matched to Hypothesis | Evidence Type |
|---|---|---|
| Snap decision record | Fragment entities overlap with hypothesis entity set AND same failure mode profile | `snap_decision` |
| Surprise event (DISCOVERY) | Fragment pair overlaps with hypothesis fragments OR shared entity set | `surprise_event` |
| Accumulation graph cluster update | Cluster merges or grows involving hypothesis fragments | `accumulation_cluster` |
| Operator input | Manual evidence attachment via API | `operator_input` |

### 6.2 Evidence Relevance Scoring

When a new snap decision is a candidate evidence for a hypothesis, its relevance is determined by:

```
FUNCTION score_evidence_relevance(snap_record, hypothesis) -> (relevance, impact):

    # Entity overlap between snap fragments and hypothesis entity set
    snap_entities = entities(snap_record.new_fragment_id) | entities(snap_record.candidate_fragment_id)
    hyp_entities = all_entities_in(hypothesis)
    entity_overlap = jaccard(snap_entities, hyp_entities)

    # Score alignment: does this snap score support or contradict the hypothesis?
    # A hypothesis about recurring patterns expects high snap scores between related fragments.
    IF snap_record.decision IN ('SNAP', 'NEAR_MISS'):
        relevance = 'supporting'
        impact = +0.02 * entity_overlap * snap_record.final_score
    ELIF snap_record.decision == 'NONE' AND entity_overlap > 0.3:
        # High entity overlap but no snap -- this weakly contradicts the hypothesis
        relevance = 'contradicting'
        impact = -0.01 * entity_overlap
    ELSE:
        relevance = 'neutral'
        impact = 0.0

    # Only attach evidence if impact is non-trivial
    IF abs(impact) < MIN_EVIDENCE_IMPACT:
        return None  # discard, not meaningful

    return (relevance, impact)
```

| Parameter | Value | Rationale |
|---|---|---|
| `MIN_EVIDENCE_IMPACT` | 0.005 | Below 0.5% confidence change, evidence is noise |

### 6.3 Confidence Update

When evidence is attached:

```
new_confidence = clamp(hypothesis.confidence + evidence.impact_on_confidence, 0.0, 1.0)
```

Confidence is bounded to `[0.0, 1.0]`. Each update is logged in `confidence_history`.

### 6.4 Confirmation Condition Evaluation

Confirmation conditions generated by TSLAM are natural language. They are evaluated in two ways:

1. **Machine-evaluable** (`metric_expression` is non-null): The expression is evaluated against current system state. Example: `"snap_count(failure_mode='DARK_EDGE', entity_overlap > 0.5, last_48h) >= 3"`. These use a restricted expression evaluator (not `eval()`) that supports a predefined set of aggregate functions over the snap decision log.

2. **Operator-evaluable** (`metric_expression` is null): The condition is presented to operators in the hypothesis review UI. Operators mark conditions as satisfied or not.

**Automatic satisfaction check**: After each evidence attachment, machine-evaluable confirmation conditions are re-evaluated. If a condition transitions from unsatisfied to satisfied, it is marked with `satisfied_at` and the satisfying evidence IDs.

### 6.5 Refutation Condition Evaluation

Refutation conditions follow the same dual-path evaluation. The key difference: a SINGLE triggered refutation condition is sufficient to transition the hypothesis to `refuted`. Confirmation requires BOTH confidence threshold AND at least one satisfied condition.

---

## 7. Async Compatibility and TSLAM Unavailability

### 7.1 Async Generation Pipeline

Hypothesis generation is async-safe. The generation pipeline:

```python
class HypothesisGenerationPipeline:

    def __init__(self, tslam_service: TSLAMService, ...):
        self._tslam = tslam_service
        self._generation_queue: asyncio.Queue[GenerationRequest] = asyncio.Queue(maxsize=100)
        self._retry_queue: asyncio.Queue[GenerationRequest] = asyncio.Queue(maxsize=500)

    async def submit(self, trigger: GenerationTrigger) -> None:
        """Non-blocking submission. Returns immediately."""
        request = GenerationRequest(trigger=trigger, attempt=0, created_at=utcnow())
        try:
            self._generation_queue.put_nowait(request)
        except asyncio.QueueFull:
            # Log dropped request; the trigger data is persisted in the
            # surprise_event or accumulation_graph tables for recovery
            log.warning("Hypothesis generation queue full, request dropped",
                        trigger_type=trigger.trigger_type)

    async def _generation_worker(self) -> None:
        """Long-running worker coroutine. Drains generation queue."""
        while True:
            request = await self._generation_queue.get()
            try:
                hypothesis = await self._generate_hypothesis(request)
                if hypothesis:
                    await self._persist_hypothesis(hypothesis)
            except TSLAMUnavailableError:
                await self._enqueue_retry(request)
            except Exception as e:
                log.error("Hypothesis generation failed", error=str(e),
                          trigger=request.trigger)

    async def _generate_hypothesis(self, request: GenerationRequest) -> Optional[Hypothesis]:
        prompt = self._assemble_prompt(request.trigger)

        # Check TSLAM health before attempting generation
        health = await self._tslam.health()
        if health["status"] in ("error", "loading"):
            raise TSLAMUnavailableError(health)

        # Attempt structured generation with timeout
        try:
            response = await asyncio.wait_for(
                self._tslam.generate_structured(
                    prompt=prompt,
                    schema=HYPOTHESIS_RESPONSE_SCHEMA,
                    max_tokens=800,
                ),
                timeout=TSLAM_HYPOTHESIS_TIMEOUT,
            )
        except asyncio.TimeoutError:
            raise TSLAMUnavailableError("TSLAM generation timed out")

        if response is None:
            # TSLAM returned None (internal failure); use template fallback
            return self._generate_from_template(request.trigger)

        return self._parse_tslam_response(response, request)
```

### 7.2 Retry Queue

When TSLAM is unavailable, generation requests are placed on a retry queue.

```python
async def _enqueue_retry(self, request: GenerationRequest) -> None:
    request.attempt += 1
    if request.attempt > MAX_RETRY_ATTEMPTS:
        # Exhausted retries; generate from template fallback
        hypothesis = self._generate_from_template(request.trigger)
        if hypothesis:
            await self._persist_hypothesis(hypothesis)
        return

    try:
        self._retry_queue.put_nowait(request)
    except asyncio.QueueFull:
        # Template fallback as last resort
        hypothesis = self._generate_from_template(request.trigger)
        if hypothesis:
            await self._persist_hypothesis(hypothesis)

async def _retry_worker(self) -> None:
    """Drains retry queue with exponential backoff."""
    while True:
        request = await self._retry_queue.get()
        delay = RETRY_BASE_DELAY * (2 ** (request.attempt - 1))
        delay = min(delay, RETRY_MAX_DELAY)
        await asyncio.sleep(delay)
        # Re-submit to main generation queue
        await self.submit(request.trigger)
```

| Parameter | Value | Rationale |
|---|---|---|
| `MAX_RETRY_ATTEMPTS` | 3 | 3 retries with exponential backoff: 30s, 60s, 120s |
| `RETRY_BASE_DELAY` | 30 seconds | Allows transient vLLM restarts to resolve |
| `RETRY_MAX_DELAY` | 300 seconds | 5-minute cap on retry delay |
| `TSLAM_HYPOTHESIS_TIMEOUT` | 45 seconds | Slightly longer than the standard 30s TSLAM timeout because hypothesis prompts are longer |

### 7.3 Graceful Degradation

| TSLAM State | Behavior |
|---|---|
| `ready` (vLLM, TSLAM-8B) | Full generation via TSLAM-8B. Best quality. |
| `fallback` (llama-cpp, TSLAM-4B) | Generation via TSLAM-4B. Lower quality but functional. Latency ~30-60s per hypothesis. |
| `error` / `loading` | Template fallback. Hypothesis created with `generation_method = 'TEMPLATE_FALLBACK'`. |
| `not_configured` | Template fallback only. No TSLAM calls attempted. |

Template-generated hypotheses are fully functional in the lifecycle pipeline. They have lower-quality claim text and generic conditions, but evidence accumulation and confidence tracking work identically.

---

## 8. Storage Schema

### 8.1 Hypothesis Table

```sql
CREATE TABLE hypothesis (
    hypothesis_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id            TEXT NOT NULL,

    -- Claim
    claim_text           TEXT NOT NULL,
    claim_summary        VARCHAR(120) NOT NULL,
    failure_mode_profile TEXT NOT NULL,

    -- Falsifiability
    confirmation_conditions JSONB NOT NULL DEFAULT '[]',
    refutation_conditions   JSONB NOT NULL DEFAULT '[]',

    -- Confidence
    confidence           REAL NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
    confidence_history   JSONB NOT NULL DEFAULT '[]',

    -- Lifecycle
    status               TEXT NOT NULL DEFAULT 'proposed'
        CHECK (status IN ('proposed', 'testing', 'confirmed', 'refuted', 'retired')),
    status_history       JSONB NOT NULL DEFAULT '[]',

    -- Generation provenance
    generation_trigger   JSONB NOT NULL,
    generation_method    TEXT NOT NULL DEFAULT 'tslam'
        CHECK (generation_method IN ('tslam', 'TEMPLATE_FALLBACK')),
    tslam_prompt_used    TEXT,
    tslam_raw_response   TEXT,
    tslam_model_version  TEXT,
    tslam_backend        TEXT,
    generation_latency_ms INTEGER,
    generation_quality   TEXT DEFAULT 'OK'
        CHECK (generation_quality IN ('OK', 'VALIDATION_FAILED')),

    -- Linkage
    parent_hypothesis_id UUID REFERENCES hypothesis(hypothesis_id),
    superseded_by        UUID REFERENCES hypothesis(hypothesis_id),

    -- Timestamps
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    confirmed_at         TIMESTAMPTZ,
    refuted_at           TIMESTAMPTZ,
    retired_at           TIMESTAMPTZ
);

-- Tenant isolation: all queries filter by tenant_id
CREATE INDEX idx_hypothesis_tenant_status
    ON hypothesis (tenant_id, status, created_at DESC);

-- Active hypotheses for evidence matching
CREATE INDEX idx_hypothesis_active
    ON hypothesis (tenant_id, failure_mode_profile, created_at DESC)
    WHERE status IN ('proposed', 'testing');

-- Lineage queries
CREATE INDEX idx_hypothesis_parent
    ON hypothesis (parent_hypothesis_id)
    WHERE parent_hypothesis_id IS NOT NULL;
```

### 8.2 Hypothesis Evidence Table

```sql
CREATE TABLE hypothesis_evidence (
    evidence_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    hypothesis_id        UUID NOT NULL REFERENCES hypothesis(hypothesis_id),
    tenant_id            TEXT NOT NULL,

    -- Source
    evidence_type        TEXT NOT NULL
        CHECK (evidence_type IN ('snap_decision', 'surprise_event',
                                  'accumulation_cluster', 'operator_input')),
    source_id            UUID NOT NULL,
    source_table         TEXT NOT NULL,

    -- Relevance
    relevance            TEXT NOT NULL
        CHECK (relevance IN ('supporting', 'contradicting', 'neutral')),
    impact_on_confidence REAL NOT NULL,
    description          TEXT NOT NULL,
    fragment_ids         UUID[] NOT NULL DEFAULT '{}',

    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Evidence lookup by hypothesis
CREATE INDEX idx_evidence_hypothesis
    ON hypothesis_evidence (hypothesis_id, created_at DESC);

-- Evidence by tenant for cross-hypothesis analysis
CREATE INDEX idx_evidence_tenant
    ON hypothesis_evidence (tenant_id, created_at DESC);

-- Deduplication: prevent the same source from being attached twice
CREATE UNIQUE INDEX idx_evidence_unique_source
    ON hypothesis_evidence (hypothesis_id, source_id, evidence_type);
```

### 8.3 Hypothesis Generation Queue Table

Persists generation requests that survive process restarts, complementing the in-memory asyncio queues.

```sql
CREATE TABLE hypothesis_generation_queue (
    request_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id            TEXT NOT NULL,
    trigger_type         TEXT NOT NULL
        CHECK (trigger_type IN ('recurring_snap_pattern', 'surprise_escalation')),
    trigger_payload      JSONB NOT NULL,
    attempt_count        INTEGER NOT NULL DEFAULT 0,
    status               TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'processing', 'completed', 'failed', 'abandoned')),
    last_attempt_at      TIMESTAMPTZ,
    error_message        TEXT,
    result_hypothesis_id UUID REFERENCES hypothesis(hypothesis_id),
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Pending requests for worker pickup
CREATE INDEX idx_gen_queue_pending
    ON hypothesis_generation_queue (status, created_at)
    WHERE status IN ('pending', 'processing');
```

### 8.4 Tenant Isolation

All tables include `tenant_id`. All queries MUST include `tenant_id` in the WHERE clause. The hypothesis engine never performs cross-tenant operations. A hypothesis generated for tenant A cannot accumulate evidence from tenant B.

---

## 9. Provenance

### 9.1 Generation Provenance

Every hypothesis records its complete generation lineage:

1. **Trigger**: `generation_trigger` JSONB captures the full trigger context -- which fragment cluster or surprise event caused generation, including all fragment IDs, scores, and surprise values at the time of generation.

2. **Prompt**: `tslam_prompt_used` stores the exact prompt text sent to TSLAM. This enables prompt debugging and regression testing.

3. **Response**: `tslam_raw_response` stores the exact TSLAM output, including any malformed JSON that failed validation. This enables quality analysis of TSLAM outputs.

4. **Model**: `tslam_model_version` and `tslam_backend` record whether the hypothesis was generated by TSLAM-8B (vLLM) or TSLAM-4B (llama-cpp), enabling quality comparisons across model tiers.

5. **Timing**: `generation_latency_ms` records wall-clock generation time for performance monitoring.

### 9.2 Evolution Provenance

Every state change and confidence update is logged in the JSONB history arrays:

- `status_history`: Array of `StatusTransition` objects. Each records the old/new status, timestamp, reason, and trigger type.
- `confidence_history`: Array of `ConfidenceUpdate` objects. Each records old/new confidence, timestamp, reason, and the evidence ID that caused the change.

These arrays are append-only. The hypothesis table's `updated_at` timestamp is set on every mutation.

### 9.3 Evidence Provenance

Every `EvidenceRecord` in `hypothesis_evidence` records:
- `source_id` + `source_table`: Direct FK to the originating snap decision, surprise event, or accumulation cluster.
- `fragment_ids`: All fragments involved in this evidence, enabling fragment-level tracing.
- `impact_on_confidence`: The exact delta applied, enabling confidence reconstruction from first principles.

### 9.4 Full Reconstruction Guarantee

Given a `hypothesis_id`, the following can be reconstructed:
1. Why it was generated (trigger + prompt + TSLAM response)
2. Every piece of evidence that affected it (evidence table)
3. Every confidence change and why (confidence_history)
4. Every status transition and why (status_history)
5. Its relationship to prior/successor hypotheses (parent/superseded_by)

---

## 10. Concrete Telecom Example

### 10.1 Scenario: Cross-Tracking-Area eNB Failure Correlation

**Background**: Tenant `telco2` operates an LTE network. The surprise engine (D1.1) detected an unusual DARK_EDGE pattern: eNBs in different tracking areas are producing correlated S1_SETUP_FAILURE and X2_HANDOVER_FAILURE alarms during maintenance windows, despite having no topological relationship.

**Step 1: Trigger**

The surprise engine emits a DISCOVERY event:
```
SurpriseEvent:
    composite_surprise: 12.5 bits
    failure_mode_profile: DARK_EDGE
    new_fragment_id: frag-4412-s1
    candidate_fragment_id: frag-7803-x2
    dimension_surprises: {semantic: 11.5, operational: 9.6, topological: 1.2}
```

The hypothesis generation pipeline receives this trigger because `12.5 >= HYPOTHESIS_SURPRISE_FLOOR (8.0)`.

**Step 2: Context Assembly**

The pipeline retrieves the two fragments and their entities:

```
Fragment frag-4412-s1:
    Source: alarm / eNB-4412
    Failure mode: DARK_EDGE
    Entities: [eNB-4412, TA-17, RNC-3, vendor-ericsson, sw-v22.3.1]
    Text: "S1 setup failure on eNB-4412, tracking area 17, cause: transport-resource-unavailable"
    Time: 2026-03-15T02:15:00Z

Fragment frag-7803-x2:
    Source: alarm / eNB-7803
    Failure mode: DARK_EDGE
    Entities: [eNB-7803, TA-23, RNC-7, vendor-ericsson, sw-v22.3.1]
    Text: "X2 handover failure on eNB-7803, tracking area 23, cause: transport-resource-unavailable"
    Time: 2026-03-15T02:18:00Z

Shared entities: [vendor-ericsson, sw-v22.3.1]
```

**Step 3: TSLAM Generation**

The assembled prompt is sent to TSLAM-8B via vLLM. TSLAM responds:

```json
{
    "claim": "Software version 22.3.1 on Ericsson eNBs introduces a transport-layer defect that causes correlated S1 setup failures and X2 handover failures across topologically unrelated base stations during maintenance windows when both signaling paths contend for the same backhaul resources.",
    "claim_summary": "Ericsson sw-v22.3.1 transport defect causes cross-TA S1/X2 failures during maintenance",
    "initial_confidence": 0.25,
    "confirmation_conditions": [
        {
            "description": "At least 3 additional eNB pairs running sw-v22.3.1 in different tracking areas exhibit the same S1/X2 co-failure pattern within the next 48 hours",
            "metric_hint": "snap_count(failure_mode='DARK_EDGE', shared_entity='sw-v22.3.1', last_48h) >= 3"
        },
        {
            "description": "eNBs NOT running sw-v22.3.1 in the same tracking areas do not exhibit the correlation",
            "metric_hint": null
        }
    ],
    "refutation_conditions": [
        {
            "description": "The next 50 DARK_EDGE snap evaluations involving sw-v22.3.1 eNBs show no significant S1/X2 correlation (avg composite score < 0.30)",
            "metric_hint": null
        },
        {
            "description": "eNBs running sw-v22.3.1 on a different vendor platform exhibit the same pattern, indicating the issue is not software-version-specific",
            "metric_hint": null
        }
    ]
}
```

**Step 4: Hypothesis Created**

```
Hypothesis:
    hypothesis_id: hyp-001
    tenant_id: telco2
    claim_text: "Software version 22.3.1 on Ericsson eNBs introduces a transport-layer
                 defect that causes correlated S1 setup failures and X2 handover failures
                 across topologically unrelated base stations during maintenance windows..."
    status: proposed
    confidence: 0.25
    generation_method: tslam
    tslam_model_version: TSLAM-8B
```

**Step 5: Evidence Accumulation (next 36 hours)**

Over the next 36 hours, the snap engine processes three more fragment pairs matching the pattern:

| Evidence | Relevance | Confidence Impact |
|---|---|---|
| eNB-2201/eNB-5544 snap (score 0.61, DARK_EDGE, both sw-v22.3.1) | supporting | +0.018 |
| eNB-3317/eNB-8890 snap (score 0.55, DARK_EDGE, both sw-v22.3.1) | supporting | +0.015 |
| eNB-1102/eNB-6678 snap (score 0.72, DARK_EDGE, both sw-v22.3.1) | supporting | +0.022 |
| eNB-9001/eNB-4420 NONE decision (sw-v22.3.1, high entity overlap but score 0.18) | contradicting | -0.004 |

After first evidence arrives, hypothesis transitions from `proposed` to `testing`.

Confidence after 36 hours: `0.25 + 0.018 + 0.015 + 0.022 - 0.004 = 0.301`

The first confirmation condition (`metric_hint` evaluated: 3 additional pairs found) is now satisfied.

**Step 6: Continued Accumulation**

Over the following week, 12 more supporting evidence records arrive. Confidence climbs to 0.78.

With `confidence (0.78) >= CONFIRMATION_THRESHOLD (0.75)` AND confirmation condition #1 satisfied, the hypothesis transitions to `confirmed`.

**Step 7: Operational Action**

The confirmed hypothesis is surfaced in the Pedkai NOC dashboard with:
- Claim text explaining the sw-v22.3.1 correlation
- Link to all 17 supporting evidence records
- Recommendation: investigate transport-layer behavior in sw-v22.3.1 during maintenance windows

---

## 11. Computational and Resource Impact

### 11.1 TSLAM Call Frequency

Hypothesis generation invokes TSLAM infrequently compared to entity extraction (which runs per fragment). Expected TSLAM call rate for hypothesis generation:

| Trigger | Expected Rate | TSLAM Calls |
|---|---|---|
| Recurring snap pattern | ~1-5 per day per tenant (clusters reaching threshold) | 1 per trigger |
| Surprise escalation (DISCOVERY) | ~2-10 per day per tenant (top 2% of snap evaluations, filtered by 8-bit floor) | 1 per trigger |

**Total**: ~3-15 TSLAM calls per day per tenant for hypothesis generation. At ~3 seconds per call (vLLM) or ~30 seconds (llama-cpp), this is 9-45 seconds or 1.5-7.5 minutes of TSLAM time per day per tenant. Negligible compared to entity extraction workload.

### 11.2 Evidence Matching Overhead

Evidence matching runs on every snap decision against active hypotheses. With `H` active hypotheses per tenant:

- Per snap decision: `O(H)` hypothesis checks, each involving entity set intersection.
- With `H <= 50` (practical upper bound -- 50 concurrent active hypotheses is extreme), this is 50 Jaccard computations per snap decision.
- Jaccard on small entity sets (~10-30 entities) is O(|E|) ~ O(30). Total: O(1500) operations per snap decision.

This is negligible compared to the snap scoring itself (embedding cosine similarity over 1536-dim vectors).

### 11.3 Storage Growth

| Table | Row Size (est.) | Growth Rate | 1-Year Estimate (10 tenants) |
|---|---|---|---|
| `hypothesis` | ~5 KB (claim text + JSONB histories + prompt) | 5-15 per day per tenant | 18-55K rows, ~90-275 MB |
| `hypothesis_evidence` | ~500 bytes | 20-100 per day per tenant | 73-365K rows, ~36-182 MB |
| `hypothesis_generation_queue` | ~1 KB | Transient (completed rows cleaned up weekly) | Negligible |

Total: under 500 MB per year for 10 tenants. Well within Postgres capacity.

---

## 12. Configuration Parameters Summary

| Parameter | Default | Scope | Tunable |
|---|---|---|---|
| `MIN_CLUSTER_SIZE` | 5 | Global | Yes |
| `GROWTH_DELTA` | 2 | Global | Yes |
| `GROWTH_WINDOW` | 24 hours | Global | Yes |
| `HYPOTHESIS_SURPRISE_FLOOR` | 8.0 bits | Global | Yes (per-tenant) |
| `CONFIRMATION_THRESHOLD` | 0.75 | Per-tenant | Yes |
| `REFUTATION_THRESHOLD` | 0.10 | Per-tenant | Yes |
| `PROPOSED_TTL` | 72 hours | Per-tenant | Yes |
| `TESTING_TTL` | 14 days | Per-tenant | Yes |
| `CONFIRMED_TTL` | 90 days | Per-tenant | Yes |
| `REFUTED_RETENTION` | 30 days | Global | Yes |
| `CONFIDENCE_DECAY_RATE` | 0.01/day | Per-tenant | Yes |
| `MIN_EVIDENCE_IMPACT` | 0.005 | Global | Yes |
| `MAX_PROMPT_FRAGMENTS` | 8 | Global | Yes |
| `TSLAM_HYPOTHESIS_TIMEOUT` | 45 seconds | Global | Yes |
| `MAX_RETRY_ATTEMPTS` | 3 | Global | Yes |
| `RETRY_BASE_DELAY` | 30 seconds | Global | Yes |
| `RETRY_MAX_DELAY` | 300 seconds | Global | Yes |
| `LIFECYCLE_SWEEP_INTERVAL` | 1 hour | Global | Yes |

---

## 13. Invariants

| ID | Statement | Enforcement |
|---|---|---|
| INV-H1 | Confidence in `[0.0, 1.0]` | `clamp()` on every confidence update + CHECK constraint in schema |
| INV-H2 | No backward status transitions | `evaluate_transitions()` only allows forward transitions; CHECK constraint prevents direct UPDATE to prior status |
| INV-H3 | Tenant isolation in all operations | `tenant_id` in all table PKs/indexes; all queries filtered by tenant |
| INV-H4 | Every hypothesis has generation provenance | `generation_trigger`, `tslam_prompt_used` (nullable only for template fallback), `generation_method` are NOT NULL |
| INV-H5 | Every evidence record linked to hypothesis | `hypothesis_id` FK NOT NULL in `hypothesis_evidence` |
| INV-H6 | No duplicate evidence from same source | UNIQUE index on `(hypothesis_id, source_id, evidence_type)` |
| INV-H7 | TSLAM unavailability does not block hypothesis creation | Template fallback guarantees hypothesis creation even without TSLAM |
| INV-H8 | All status transitions logged | `status_history` JSONB updated on every transition in `evaluate_transitions()` |
| INV-H9 | All confidence changes logged | `confidence_history` JSONB updated on every evidence attachment and decay tick |
| INV-H10 | Generation requests survive process restart | `hypothesis_generation_queue` table persists pending requests; worker recovers on startup |

---

## Appendix A: Decision Log

| Decision | Alternatives Considered | Rationale |
|---|---|---|
| JSONB for history arrays (not separate tables) | Normalized history tables with FKs | History arrays are append-only and read as a unit. JSONB avoids N+1 queries for hypothesis detail views. Array size is bounded (~hundreds of entries max per hypothesis). |
| Template fallback when TSLAM unavailable (not skip generation) | Skip hypothesis, queue indefinitely | Skipping loses the time-sensitive trigger context. Indefinite queuing accumulates stale requests. Template fallback creates a functional (if lower quality) hypothesis immediately. |
| Confidence as single float (not multi-dimensional) | Per-dimension confidence tracking | Multi-dimensional confidence adds complexity without clear operational benefit at this stage. Confidence is a scalar summary of total evidence weight. Per-dimension breakdown is available through the evidence records themselves. |
| Forward-only status transitions (not bidirectional) | Allow confirmed -> testing on contradicting evidence | Bidirectional transitions create confusing lifecycle histories. Generating a new child hypothesis referencing the parent is cleaner and preserves the confirmed hypothesis's integrity for audit. |
| In-memory async queue with DB persistence backup (not Kafka-only) | Kafka topic for generation requests, in-memory only | Kafka adds dependency complexity for low-volume traffic (3-15 requests/day). In-memory queue provides low-latency; DB backup provides durability. Kafka path available for future scale. |
| Confidence decay over time (not static) | No decay -- confidence only changes with evidence | Without decay, a hypothesis that received early supporting evidence but then went quiet would retain high confidence indefinitely. Decay forces hypotheses to be continuously reinforced or fade, preventing stale high-confidence claims. |
