# T3.3 -- Negative Evidence / Disconfirmation Engine

**Task**: T3.3
**Phase**: 3 -- Discovery Mechanisms
**Tier**: 1 -- Foundation (no LLM dependency)
**Generated**: 2026-03-16
**Status**: Specification complete -- ready for implementation
**Remediates**: F-4.4 (Moderate)

---

## 1. Purpose and Scope

### 1.1 Problem Statement

Finding F-4.4 from the v2 forensic audit:

> No negative evidence mechanism to mark fragments as irrelevant beyond time-based decay. The system can only corroborate or snap; no operator-driven reclassification or accelerated decay for investigated non-relevant evidence.

The Abeyance Memory system accumulates fragments and discovers correlations (snaps), but has no mechanism for the inverse: recording that a fragment or pattern has been investigated and found irrelevant. This creates two concrete problems:

1. **Pollution**: Investigated-but-irrelevant fragments remain ACTIVE at high decay scores, continuing to participate in snap evaluations and generating false positive correlations until natural time-based decay clears them (up to 270 days for TICKET_TEXT sources).

2. **Recurrence**: When a pattern is disconfirmed (e.g., an operator investigates a cluster of alarms and determines they are benign), the system has no memory of this determination. Future fragments matching the same pattern enter with full relevance and repeat the false positive cycle.

### 1.2 This Task

This specification defines the complete Negative Evidence mechanism:

- **Operator-driven disconfirmation**: API for reclassifying ACTIVE fragments as "investigated, not relevant"
- **System-driven disconfirmation**: Internal pathway for automated diagnostic pipelines to mark fragments
- **Accelerated decay trigger**: Calls `apply_accelerated_decay()` from T2.5 on disconfirmed fragments
- **Propagation**: Disconfirmed patterns reduce snap scores for similar future fragments within a bounded radius
- **Storage**: Disconfirmation record schema with full provenance

### 1.3 Design Constraints

- **Tier 1 -- Foundation**: No LLM calls. Operates entirely on existing embeddings, entity sets, and snap scores.
- **Monotonic decay invariant (INV-2)**: Disconfirmation can only accelerate decay (reduce scores), never increase them.
- **T2.5 interface**: This mechanism calls `apply_accelerated_decay()` as specified in the decay engine interface. It does NOT modify that interface.
- **Tenant isolation (INV-7)**: All disconfirmation operations are tenant-scoped.

### 1.4 Out of Scope

- Changes to the `apply_accelerated_decay()` method signature or behavior (T2.5 owns that)
- LLM-based reasoning about why a fragment is irrelevant (Tier 2+ concern)
- UI design for the operator disconfirmation workflow (frontend concern)
- Modifications to the snap engine scoring algorithm (T1.4 owns that)

---

## 2. Conceptual Model

### 2.1 Disconfirmation as Negative Evidence

A disconfirmation event records that one or more fragments have been investigated and found not relevant to a real failure. This is negative evidence: information that reduces the posterior probability that a pattern represents a genuine anomaly.

The mechanism has three effects:

1. **Immediate**: The disconfirmed fragment(s) receive accelerated decay via `apply_accelerated_decay()`.
2. **Propagated**: A disconfirmation pattern is recorded. Future fragments that are sufficiently similar to the disconfirmed pattern receive a snap score penalty during evaluation.
3. **Auditable**: The disconfirmation event, its provenance, and its effects are persisted for forensic review.

### 2.2 Two Ingestion Pathways

| Pathway | Trigger | Actor | Typical Use Case |
|---|---|---|---|
| Operator-driven | REST API call | Human operator via UI/CLI | Operator investigates alarm cluster, determines false positive |
| System-driven | Internal service call | Automated diagnostic pipeline | Automated test confirms alarms are from planned maintenance window |

Both pathways converge on the same `DisconfirmationService` and produce identical `DisconfirmationRecord` entries. The only difference is the `triggered_by` field in provenance.

### 2.3 What Gets Disconfirmed

A disconfirmation targets one or more specific fragment IDs. The caller must provide the fragment IDs explicitly. The system does not infer which fragments to disconfirm.

**Why explicit IDs, not pattern-based bulk disconfirmation?** Automatic pattern-based disconfirmation (e.g., "disconfirm everything similar to this fragment") is dangerous: it could suppress genuine anomalies that superficially resemble a false positive. The operator must make a deliberate judgment about each fragment or group of fragments. The propagation mechanism (Section 5) handles the "similar future fragments" case through score penalties, not through retroactive bulk disconfirmation.

---

## 3. API Specification

### 3.1 Operator-Driven Disconfirmation Endpoint

```
POST /api/v1/tenants/{tenant_id}/abeyance/disconfirm
```

**Request Body:**

```json
{
  "fragment_ids": ["uuid-1", "uuid-2"],
  "reason": "Investigated alarm cluster on GPON-OLT-07. Alarms caused by planned firmware upgrade window MW-2026-0342. Not indicative of failure.",
  "acceleration_factor": 6.0,
  "external_reference": "INC-2026-08471",
  "propagation_enabled": true
}
```

**Field Specification:**

| Field | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `fragment_ids` | `list[UUID]` | Yes | 1..50 items | Fragment IDs to disconfirm |
| `reason` | `string` | Yes | 1..500 chars | Human-readable explanation |
| `acceleration_factor` | `float` | No | `[2.0, 10.0]`, default `5.0` | Decay acceleration factor passed to T2.5 |
| `external_reference` | `string` | No | Max 256 chars | Ticket/incident ID for traceability |
| `propagation_enabled` | `bool` | No | Default `true` | Whether to create a propagation pattern from this disconfirmation |

**Batch size limit (50)**: Prevents accidental mass disconfirmation. An operator disconfirming more than 50 fragments at once likely needs a different workflow (e.g., maintenance window bulk suppression, which is a distinct feature).

**Default acceleration factor (5.0)**: Corresponds to "Moderate" strength in the T2.5 consumption contract (Section 9, Table). This is the expected common case: an operator has investigated and determined the fragment is not relevant.

**Response (200 OK):**

```json
{
  "disconfirmation_id": "uuid-disconf-1",
  "results": [
    {
      "fragment_id": "uuid-1",
      "old_score": 0.72,
      "new_score": 0.11,
      "old_status": "ACTIVE",
      "new_status": "STALE",
      "skipped": false
    },
    {
      "fragment_id": "uuid-2",
      "old_score": 0.45,
      "new_score": 0.02,
      "old_status": "ACTIVE",
      "new_status": "EXPIRED",
      "skipped": false
    }
  ],
  "propagation_pattern_id": "uuid-pattern-1",
  "fragments_accelerated": 2,
  "fragments_skipped": 0
}
```

**Error Responses:**

| Status | Condition |
|---|---|
| 400 | Empty `fragment_ids`, `acceleration_factor` out of range, `reason` empty or too long |
| 404 | `tenant_id` does not exist |
| 422 | All fragments in `fragment_ids` are in terminal states (EXPIRED/SNAPPED); nothing to disconfirm |

If some fragments are terminal and others are not, the request succeeds for the non-terminal ones and the terminal ones appear with `skipped: true` in the response.

### 3.2 System-Driven Disconfirmation (Internal API)

```python
async def apply_disconfirmation(
    self,
    session: AsyncSession,
    tenant_id: str,
    fragment_ids: list[UUID],
    reason: str,
    acceleration_factor: float,
    provenance: DisconfirmationProvenance,
    propagation_enabled: bool = True,
) -> DisconfirmationResult:
```

This is the internal method on `DisconfirmationService`. The REST endpoint (Section 3.1) is a thin wrapper that constructs an `OPERATOR:` provenance and delegates here.

System callers (e.g., a maintenance-window correlation pipeline) call this directly with `SYSTEM:` provenance.

---

## 4. Accelerated Decay Trigger

### 4.1 Per-Fragment Acceleration

For each `fragment_id` in the disconfirmation request, `DisconfirmationService` calls:

```python
result = await self._decay_engine.apply_accelerated_decay(
    session=session,
    fragment_id=fragment_id,
    tenant_id=tenant_id,
    acceleration_factor=acceleration_factor,
    reason=reason,
    provenance=AcceleratedDecayProvenance(
        triggered_by=provenance.triggered_by,
        subsystem="NegativeEvidence",
        trace_id=disconfirmation_id,
        external_reference=provenance.external_reference,
    ),
)
```

### 4.2 Acceleration Factor Selection Guidance

The API accepts an explicit `acceleration_factor` from the caller. For operator-driven disconfirmation, the UI should present these as named choices:

| Label | Factor | Use Case |
|---|---|---|
| Low confidence | 2.0 | "Probably not relevant, but not certain" |
| Investigated, not relevant | 5.0 | Standard disconfirmation after investigation |
| Definitively ruled out | 8.0 | Root cause identified and confirmed unrelated |
| Known false positive pattern | 10.0 | Recurring known-benign alarm (e.g., scheduled test) |

These labels are UI guidance, not enforced by the API. The API enforces only the `[2.0, 10.0]` bounds from T2.5.

### 4.3 Monotonicity Preservation (INV-2)

This mechanism cannot violate INV-2 because:

1. `apply_accelerated_decay()` enforces `new_score = min(new_score, frag.current_decay_score)` (T2.5, algorithm step 5).
2. `acceleration_factor >= 2.0` ensures `effective_age > actual_age`, so the computed score is strictly less than the natural score.
3. No path in this specification increases a decay score.

---

## 5. Propagation Mechanism

### 5.1 Concept

Propagation is the mechanism by which disconfirming one fragment affects the scoring of future fragments that match a similar pattern. It does NOT retroactively modify existing fragments. It applies a penalty to snap scores computed during future snap evaluations.

### 5.2 Disconfirmation Pattern

When `propagation_enabled=true`, the disconfirmation creates a **DisconfirmationPattern** -- a compressed representation of the disconfirmed fragment(s) used for future similarity matching.

**Pattern construction** (from the disconfirmed fragment set):

```python
@dataclass
class DisconfirmationPattern:
    pattern_id: UUID
    tenant_id: str
    disconfirmation_id: UUID          # Links back to the disconfirmation event

    # Centroid embeddings (mean of disconfirmed fragments, per dimension)
    centroid_semantic: Optional[np.ndarray]      # Vector(1536) or None
    centroid_topological: Optional[np.ndarray]   # Vector(1536) or None
    centroid_temporal: np.ndarray                 # Vector(256), always present
    centroid_operational: Optional[np.ndarray]    # Vector(1536) or None

    # Centroid masks (dimension is valid only if ALL disconfirmed fragments had it valid)
    mask_semantic: bool
    mask_topological: bool
    mask_operational: bool

    # Entity set (union of all entities from disconfirmed fragments)
    entity_fingerprint: set[str]

    # Metadata
    fragment_count: int                # Number of fragments in this pattern
    acceleration_factor: float         # Factor used for the original disconfirmation
    created_at: datetime               # UTC
    expires_at: datetime               # UTC, pattern expiration (see Section 5.6)
    failure_modes: list[str]           # Failure modes of the disconfirmed fragments
```

**Centroid computation**: For each embedding dimension, compute the element-wise mean of all disconfirmed fragments that have that dimension valid. If fewer than 1 fragment has a dimension valid, the centroid for that dimension is NULL and the mask is FALSE.

```
centroid_d = mean(emb_d_i for i in fragments where mask_d_i = TRUE)
mask_d = (count of fragments where mask_d_i = TRUE) >= 1
```

### 5.3 Propagation Radius

The propagation radius defines how similar a new fragment must be to a disconfirmation pattern for the penalty to apply. This is critical: too large a radius suppresses genuine anomalies; too small a radius makes propagation ineffective.

**Similarity computation**: The similarity between a new fragment `F` and a disconfirmation pattern `P` uses the same per-dimension cosine scoring as the snap engine (T1.4), with mask-aware weight redistribution. A uniform weight profile is used (not the failure-mode-specific profiles):

```python
PROPAGATION_WEIGHT_PROFILE = WeightProfile(
    failure_mode="PROPAGATION",
    w_sem=0.25, w_topo=0.15, w_temp=0.10, w_oper=0.20, w_ent=0.30,
)
```

**Rationale for uniform profile**: Disconfirmation patterns span multiple failure modes. Using a failure-mode-specific profile would bias the similarity toward one type of match. The propagation profile weights entity overlap highest because entity overlap is the strongest signal for "this is the same pattern" (same devices, same interfaces, same alarm types).

**Similarity function**:

```
sim(F, P) = compute_composite_score(F, P.centroid_*, P.mask_*, P.entity_fingerprint,
                                     PROPAGATION_WEIGHT_PROFILE, temporal_modifier=1.0)
```

Note: `temporal_modifier=1.0` (no temporal attenuation) because the propagation check is about pattern similarity, not recency.

**Propagation radius threshold**:

```python
PROPAGATION_SIMILARITY_THRESHOLD: float = 0.70
```

A new fragment `F` is considered within the propagation radius of pattern `P` if and only if:

```
sim(F, P) >= PROPAGATION_SIMILARITY_THRESHOLD
```

**Bound**: The threshold is fixed at 0.70. This is deliberately conservative (high threshold = narrow radius). At 0.70, only fragments that are strongly similar to the disconfirmed pattern receive a penalty. This prevents over-suppression.

**Rationale for 0.70**: In the snap scoring system, the snap threshold (before Sidak correction) for most profiles is in the range 0.55-0.70. A propagation threshold at 0.70 means only fragments that would almost certainly have snapped with the disconfirmed pattern are penalized. Fragments with moderate similarity (0.50-0.69) are not affected, preserving the system's ability to detect genuine anomalies that superficially resemble the disconfirmed pattern.

### 5.4 Penalty Function

When a new fragment `F` falls within the propagation radius of one or more disconfirmation patterns, its snap scores against all candidates are penalized.

**Penalty computation**:

```
penalty_factor(F) = product over matching patterns P_i of:
    (1.0 - PENALTY_STRENGTH * pattern_similarity(F, P_i) * age_decay(P_i))
```

Where:

```python
PENALTY_STRENGTH: float = 0.30
```

And `age_decay(P)` is an exponential decay on the pattern's age that reduces its influence over time:

```
age_decay(P) = exp(-(days_since_creation(P)) / PATTERN_DECAY_TAU)

PATTERN_DECAY_TAU: float = 90.0   # days
```

**Penalty application** to snap scores:

```
penalized_snap_score = raw_snap_score * penalty_factor(F)
```

**Bounds analysis**:

- `pattern_similarity` is in `[0.70, 1.0]` (below 0.70 it is not a match).
- `age_decay` is in `(0.0, 1.0]`.
- `PENALTY_STRENGTH` is 0.30.
- Per-pattern factor: `1.0 - 0.30 * sim * age_decay`. Worst case (sim=1.0, age_decay=1.0): `1.0 - 0.30 = 0.70`. So a single fresh, perfectly matching pattern reduces snap scores by at most 30%.
- Multiple patterns: factors multiply. Two perfectly matching fresh patterns: `0.70 * 0.70 = 0.49`. Three: `0.70^3 = 0.343`.

**Floor**: The penalty factor is clamped to a minimum of `0.30`:

```python
PENALTY_FLOOR: float = 0.30
```

```
penalty_factor(F) = max(PENALTY_FLOOR, raw_penalty_factor(F))
```

This ensures that no combination of disconfirmation patterns can suppress snap scores by more than 70%. A fragment with genuinely strong evidence can still snap even if it resembles multiple disconfirmed patterns.

**INV-2 compatibility**: The penalty reduces snap scores, not decay scores. Snap scores are transient (computed per evaluation, not stored on the fragment). The penalty does not modify the fragment's `current_decay_score`. Monotonic decay is unaffected.

### 5.5 Penalty Application Point

The penalty is applied **after** the composite score computation (T1.4, Section 7.1) and **after** the temporal modifier, but **before** the snap threshold comparison:

```
raw_composite = compute_composite_score(A, B, P)      # T1.4
modulated     = raw_composite * temporal_modifier       # T1.4, Section 7.2
penalized     = modulated * penalty_factor(A)           # T3.3 (this spec)
decision      = compare(penalized, sidak_threshold)     # Snap/Near-miss/None
```

The penalty is on fragment `A` (the new fragment being evaluated), not on fragment `B` (the candidate). This is because the disconfirmation pattern describes properties of the new fragment, not properties of the candidate it is being compared against.

The `SnapDecisionRecord` (T1.4, Section 8) is extended with:

```python
# Negative evidence penalty fields (added by T3.3)
negative_evidence_penalty: float        # [0.30, 1.0], 1.0 = no penalty
matching_disconfirmation_patterns: list[UUID]   # Pattern IDs that contributed
penalized_score: float                  # final_score * negative_evidence_penalty
```

### 5.6 Pattern Expiration

Disconfirmation patterns expire after a configurable TTL:

```python
PATTERN_TTL_DAYS: int = 180
```

`expires_at = created_at + timedelta(days=PATTERN_TTL_DAYS)`

Expired patterns are excluded from propagation checks. A maintenance job (running alongside the existing decay maintenance) deletes expired patterns.

**Rationale for 180 days**: Long enough to cover recurring patterns (e.g., monthly maintenance windows produce similar alarm patterns 6 times). Short enough that stale disconfirmation patterns do not accumulate indefinitely and suppress potentially valid future anomalies.

The `age_decay` function (Section 5.4) ensures that even within the 180-day TTL, the pattern's influence diminishes exponentially with a 90-day time constant. At 180 days, `age_decay = exp(-180/90) = exp(-2) = 0.135`, so the pattern's effective penalty strength is `0.30 * 0.135 = 0.041` (4.1%) -- negligible.

### 5.7 Pattern Retrieval Efficiency

During snap evaluation of a new fragment `F`, the system must check `F` against all active (non-expired) disconfirmation patterns for the tenant. To avoid O(N) full similarity computation against every pattern:

1. **Entity pre-filter**: Only check patterns whose `entity_fingerprint` has Jaccard overlap >= 0.20 with `F`'s entity set. This is a cheap set operation. Patterns with zero entity overlap cannot reach 0.70 composite similarity (entity overlap weight is 0.30, so zero entity overlap contributes 0.0 to that dimension, requiring the remaining dimensions to compensate to reach 0.70 -- unlikely in practice).

2. **Index**: The `disconfirmation_patterns` table has a GIN index on the `entity_fingerprint` array column for efficient overlap queries.

3. **Cardinality expectation**: For a typical telecom tenant, the number of active disconfirmation patterns is expected to be O(100s), not O(10000s). The pre-filter reduces candidates to O(10s) per fragment.

---

## 6. Storage Schema

### 6.1 `disconfirmation_events` Table

```sql
CREATE TABLE disconfirmation_events (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           TEXT NOT NULL,
    triggered_by        TEXT NOT NULL,          -- "OPERATOR:<user_id>" | "SYSTEM:<subsystem>"
    subsystem           TEXT NOT NULL,          -- "NegativeEvidence"
    reason              TEXT NOT NULL,          -- Max 500 chars
    acceleration_factor FLOAT NOT NULL,         -- [2.0, 10.0]
    external_reference  TEXT,                   -- Ticket/incident ID
    trace_id            TEXT,                   -- Correlation ID
    propagation_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    fragment_count      INTEGER NOT NULL,       -- Number of fragments targeted
    fragments_accelerated INTEGER NOT NULL,     -- Number successfully accelerated
    fragments_skipped   INTEGER NOT NULL,       -- Number skipped (terminal state)
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT chk_acceleration_factor CHECK (acceleration_factor >= 2.0 AND acceleration_factor <= 10.0),
    CONSTRAINT chk_reason_length CHECK (char_length(reason) BETWEEN 1 AND 500),
    CONSTRAINT chk_triggered_by_format CHECK (triggered_by ~ '^(OPERATOR|SYSTEM):[a-zA-Z0-9_\-]{1,128}$')
);

CREATE INDEX idx_disconf_events_tenant ON disconfirmation_events (tenant_id, created_at DESC);
```

### 6.2 `disconfirmation_fragments` Table (Junction)

```sql
CREATE TABLE disconfirmation_fragments (
    disconfirmation_id  UUID NOT NULL REFERENCES disconfirmation_events(id),
    fragment_id         UUID NOT NULL,
    tenant_id           TEXT NOT NULL,
    old_score           FLOAT NOT NULL,
    new_score           FLOAT NOT NULL,
    old_status          TEXT NOT NULL,
    new_status          TEXT NOT NULL,
    skipped             BOOLEAN NOT NULL DEFAULT FALSE,
    skip_reason         TEXT,

    PRIMARY KEY (disconfirmation_id, fragment_id)
);

CREATE INDEX idx_disconf_frags_fragment ON disconfirmation_fragments (fragment_id);
```

### 6.3 `disconfirmation_patterns` Table

```sql
CREATE TABLE disconfirmation_patterns (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id               TEXT NOT NULL,
    disconfirmation_id      UUID NOT NULL REFERENCES disconfirmation_events(id),

    -- Centroid embeddings (NULL if dimension unavailable across all source fragments)
    centroid_semantic        vector(1536),
    centroid_topological     vector(1536),
    centroid_temporal        vector(256) NOT NULL,
    centroid_operational     vector(1536),

    -- Dimension validity masks
    mask_semantic            BOOLEAN NOT NULL DEFAULT FALSE,
    mask_topological         BOOLEAN NOT NULL DEFAULT FALSE,
    mask_operational         BOOLEAN NOT NULL DEFAULT FALSE,

    -- Entity fingerprint for pre-filtering
    entity_fingerprint       TEXT[] NOT NULL DEFAULT '{}',

    -- Metadata
    fragment_count           INTEGER NOT NULL,
    acceleration_factor      FLOAT NOT NULL,
    failure_modes            TEXT[] NOT NULL DEFAULT '{}',
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at               TIMESTAMPTZ NOT NULL,

    CONSTRAINT chk_pattern_expiry CHECK (expires_at > created_at)
);

CREATE INDEX idx_disconf_patterns_tenant_active
    ON disconfirmation_patterns (tenant_id, expires_at)
    WHERE expires_at > now();

CREATE INDEX idx_disconf_patterns_entities
    ON disconfirmation_patterns USING GIN (entity_fingerprint);
```

### 6.4 Provenance Dataclass

```python
@dataclass
class DisconfirmationProvenance:
    triggered_by: str          # "OPERATOR:<user_id>" | "SYSTEM:<subsystem_name>"
    subsystem: str             # Always "NegativeEvidence" for this mechanism
    trace_id: Optional[str]    # Correlation ID
    external_reference: Optional[str]  # Ticket/incident ID
```

Field validation rules are identical to `AcceleratedDecayProvenance` (T2.5, Section 3.3).

---

## 7. Algorithm: Disconfirmation Processing

```
FUNCTION process_disconfirmation(session, tenant_id, fragment_ids,
                                  reason, acceleration_factor, provenance,
                                  propagation_enabled):

  1. VALIDATE inputs
     a. fragment_ids non-empty, len <= 50
     b. acceleration_factor in [2.0, 10.0] (T2.5 bounds)
     c. reason non-empty, len <= 500
     d. provenance fields valid (same rules as T2.5)

  2. GENERATE disconfirmation_id (UUID)

  3. FOR EACH fragment_id in fragment_ids:
     a. CALL decay_engine.apply_accelerated_decay(
            session, fragment_id, tenant_id,
            acceleration_factor, reason,
            AcceleratedDecayProvenance(
                triggered_by=provenance.triggered_by,
                subsystem="NegativeEvidence",
                trace_id=str(disconfirmation_id),
                external_reference=provenance.external_reference,
            ))
     b. COLLECT result into results list

  4. PERSIST disconfirmation_events record
     tenant_id, triggered_by, reason, acceleration_factor, external_reference,
     fragment_count=len(fragment_ids),
     fragments_accelerated=count(r for r in results if not r.skipped),
     fragments_skipped=count(r for r in results if r.skipped)

  5. PERSIST disconfirmation_fragments records (one per fragment)

  6. IF propagation_enabled AND at least one fragment was accelerated (not skipped):
     a. FETCH full fragment records for non-skipped fragment_ids
     b. COMPUTE centroid embeddings (per Section 5.2)
     c. COMPUTE entity_fingerprint (union of all entity sets)
     d. COMPUTE expires_at = now + PATTERN_TTL_DAYS
     e. COLLECT failure_modes from fragment records (deduplicated)
     f. PERSIST disconfirmation_patterns record

  7. FLUSH session (caller owns transaction)

  8. RETURN DisconfirmationResult(
         disconfirmation_id,
         per-fragment results,
         propagation_pattern_id (or None if propagation disabled),
         fragments_accelerated count,
         fragments_skipped count)
```

---

## 8. Algorithm: Propagation Penalty Evaluation

This runs during snap evaluation (inside `score_pair_v3` or its caller):

```
FUNCTION compute_propagation_penalty(session, tenant_id, new_fragment):

  1. FETCH active disconfirmation patterns for tenant
     SELECT * FROM disconfirmation_patterns
     WHERE tenant_id = :tenant_id AND expires_at > now()

  2. ENTITY PRE-FILTER
     candidate_patterns = [P for P in patterns
                           if jaccard(new_fragment.entities, P.entity_fingerprint) >= 0.20]

  3. IF no candidate_patterns:
     RETURN penalty_factor=1.0, matching_patterns=[]

  4. FOR EACH candidate pattern P:
     a. COMPUTE sim = composite_similarity(new_fragment, P,
                         PROPAGATION_WEIGHT_PROFILE, temporal_modifier=1.0)
     b. IF sim >= PROPAGATION_SIMILARITY_THRESHOLD:
        age_days = (now() - P.created_at).total_seconds() / 86400.0
        age_factor = exp(-age_days / PATTERN_DECAY_TAU)
        per_pattern_factor = 1.0 - PENALTY_STRENGTH * sim * age_factor
        ADD (P.id, per_pattern_factor) to matching list

  5. IF no matches:
     RETURN penalty_factor=1.0, matching_patterns=[]

  6. raw_penalty = PRODUCT(factor for _, factor in matching list)
     penalty_factor = max(PENALTY_FLOOR, raw_penalty)

  7. RETURN penalty_factor, [P.id for P, _ in matching list]
```

**Caching**: The active disconfirmation patterns for a tenant change infrequently (new disconfirmations are rare events relative to snap evaluations). The pattern set is cached in memory with a TTL of 60 seconds. Cache invalidation occurs when a new disconfirmation is processed for the tenant.

---

## 9. Constants Summary

| Constant | Value | Unit | Rationale |
|---|---|---|---|
| `DEFAULT_ACCELERATION_FACTOR` | 5.0 | -- | Moderate disconfirmation strength |
| `MAX_DISCONFIRMATION_BATCH` | 50 | fragments | Prevents accidental mass disconfirmation |
| `PROPAGATION_SIMILARITY_THRESHOLD` | 0.70 | -- | Conservative; only strong matches penalized |
| `PENALTY_STRENGTH` | 0.30 | -- | Max 30% penalty per matching pattern |
| `PENALTY_FLOOR` | 0.30 | -- | Max 70% total penalty regardless of pattern count |
| `PATTERN_DECAY_TAU` | 90.0 | days | Exponential decay of pattern influence |
| `PATTERN_TTL_DAYS` | 180 | days | Hard expiration for patterns |
| `PATTERN_CACHE_TTL` | 60 | seconds | In-memory cache refresh interval |
| `ENTITY_PREFILTER_THRESHOLD` | 0.20 | Jaccard | Cheap pre-filter before full similarity |

---

## 10. Telecom Example: False Alarm Pattern Suppression

### 10.1 Scenario

A telecom NOC operates a fiber-to-the-home (FTTH) network. Every Tuesday at 02:00 UTC, automated optical power level tests run on all GPON-OLT shelves. These tests generate transient `LOS` (Loss of Signal) and `LOSi` (Loss of Signal for ONT-i) alarms as the OLT momentarily cycles its optical transceivers.

The Abeyance Memory system ingests these alarms as fragments. They are type `ALARM`, associated with entities like `GPON-OLT-07`, `GPON-OLT-12`, `PON-PORT-3/1/0`. They have high entity overlap with each other and moderate semantic similarity ("Loss of Signal" / "Loss of Signal for ONT-i" descriptions).

### 10.2 Initial False Positive Cycle (Before Negative Evidence)

1. Week 1: 120 LOS/LOSi alarm fragments ingested during Tuesday 02:00-02:15 window.
2. The snap engine evaluates these against existing ACTIVE fragments. Their mutual similarity is high (same entities, similar semantics, same temporal window). They snap together into accumulation graph clusters, creating edges.
3. An operator investigates the cluster, determines it is routine testing. But there is no mechanism to record this finding.
4. The fragments remain ACTIVE with high decay scores for months (ALARM tau = 180 days).
5. Week 2: Another 120 fragments arrive. They snap with both Week 1 and Week 2 fragments. The accumulation graph grows with false edges.
6. Repeat weekly. After 2 months, hundreds of false positive edges pollute the graph.

### 10.3 With Negative Evidence Mechanism

1. Week 1: 120 LOS/LOSi alarm fragments ingested. Same snap behavior as before.
2. Operator investigates, determines routine testing. Calls the disconfirmation API:

```json
POST /api/v1/tenants/telco2/abeyance/disconfirm
{
  "fragment_ids": ["frag-001", "frag-002", "...", "frag-048"],
  "reason": "Weekly GPON optical power test. Scheduled maintenance MW-WEEKLY-OPT. Alarms are expected transient LOS/LOSi during test window.",
  "acceleration_factor": 8.0,
  "external_reference": "MW-WEEKLY-OPT",
  "propagation_enabled": true
}
```

(Operator selects the 48 most representative fragments from the cluster.)

3. **Immediate effect**: All 48 fragments receive accelerated decay with factor 8.0. A fragment that was 7 days old with score 0.72 is now scored as if 56 days old, dropping to approximately 0.10. Most transition to STALE; some to EXPIRED.

4. **Propagation pattern created**: A `DisconfirmationPattern` is computed:
   - `centroid_semantic`: mean of 48 LOS/LOSi alarm embeddings (all have semantic mask TRUE)
   - `centroid_topological`: mean of topological embeddings for GPON-OLT-07, OLT-12 neighborhoods
   - `centroid_temporal`: mean of temporal embeddings (all encode Tuesday ~02:00 UTC)
   - `entity_fingerprint`: `{"GPON-OLT-07", "GPON-OLT-12", "PON-PORT-3/1/0", "PON-PORT-3/1/1", ...}`

5. **Week 2**: 120 new LOS/LOSi alarm fragments arrive during Tuesday 02:00 test window.
   - During snap evaluation, each new fragment is checked against active disconfirmation patterns.
   - Entity pre-filter: new fragments share entities with the pattern (`GPON-OLT-07`, etc.). Jaccard overlap ~0.60. Passes the 0.20 threshold.
   - Full similarity: semantic (similar LOS descriptions) ~0.85, topological (same OLT neighborhoods) ~0.80, temporal (same Tuesday 02:00 pattern) ~0.90, entity overlap ~0.60. Composite similarity ~0.78. Exceeds 0.70 threshold.
   - Penalty: `1.0 - 0.30 * 0.78 * exp(-7/90) = 1.0 - 0.30 * 0.78 * 0.925 = 1.0 - 0.216 = 0.784`
   - Each new fragment's snap scores are multiplied by 0.784. Scores that were previously above the snap threshold (say 0.62 vs threshold 0.58) now drop to 0.486, below the threshold. These fragments no longer snap with each other.
   - Result: Week 2 alarm fragments still exist as ACTIVE fragments (they decay naturally), but they do not form false positive snap edges.

6. **Week 8**: Pattern is 49 days old. `age_decay = exp(-49/90) = 0.58`. Penalty per matching fragment: `1.0 - 0.30 * 0.78 * 0.58 = 1.0 - 0.136 = 0.864`. The penalty has weakened. If a genuine anomaly occurs during the test window (e.g., a real fiber cut coincides with the test), the penalty is small enough (13.6%) that a genuine high-similarity event can still exceed the snap threshold.

7. **Day 180**: Pattern expires and is deleted. If the weekly test pattern is still occurring, the operator (or an automated pipeline) would have re-disconfirmed more recent instances, creating a fresh pattern.

### 10.4 Key Properties Demonstrated

- **False positive suppression**: Recurring benign alarm patterns no longer generate false snap edges after initial disconfirmation.
- **Bounded suppression**: The 30% per-pattern cap and 0.30 floor ensure genuine anomalies are not completely hidden.
- **Temporal decay of influence**: The pattern's penalty weakens over time (90-day tau), preventing stale disconfirmation knowledge from suppressing novel anomalies indefinitely.
- **Auditability**: Every disconfirmation event, the fragments it targeted, and the propagation pattern are persisted with full provenance.

---

## 11. Invariant Analysis

| Invariant | Impact | Analysis |
|---|---|---|
| INV-2 (Monotonic Decay) | **Preserved** | Disconfirmation calls `apply_accelerated_decay()` which enforces `new_score <= old_score`. Propagation penalties apply to transient snap scores, not to stored decay scores. No stored score is ever increased. |
| INV-3 / INV-8 (Bounded Scores) | **Preserved** | Penalty factor is clamped to `[PENALTY_FLOOR, 1.0] = [0.30, 1.0]`. Penalized snap scores remain in `[0.0, 1.0]` because they are the product of a `[0.0, 1.0]` score and a `[0.30, 1.0]` factor. |
| INV-7 (Tenant Isolation) | **Preserved** | All queries include `tenant_id` filter. Disconfirmation patterns are tenant-scoped. Cross-tenant pattern matching is impossible by query construction. |
| INV-10 (Provenance) | **Preserved and Extended** | Disconfirmation events are persisted with full provenance. The `ACCELERATED_DECAY` provenance entries in `FragmentHistoryORM` link back to the disconfirmation via `trace_id`. The `SnapDecisionRecord` extension records matching pattern IDs. |
| INV-11 (Mask Enforcement) | **Preserved** | Propagation similarity uses the same mask-aware scoring as T1.4. NULL centroids are excluded from similarity computation. |
| INV-NEW-1 (Available weight sum > 0) | **Preserved** | Propagation scoring uses the same weight redistribution formula. Temporal and entity overlap are always available. |

---

## 12. Failure Modes

| Failure | Detection | Handling | Observable Signal |
|---|---|---|---|
| All fragments in batch are terminal | Step 3 results all skipped | Return 422 with explanation | HTTP 422 response |
| Some fragments terminal, some not | Step 3 partial skip | Process non-terminal; report skipped in response | `fragments_skipped > 0` in response |
| `apply_accelerated_decay` raises exception for one fragment | Step 3 exception | Abort entire disconfirmation (transaction rollback) | HTTP 500; no partial state |
| Pattern centroid computation fails (all embeddings NULL) | Step 6b | Create pattern with only temporal centroid and entity fingerprint; remaining centroids NULL | Pattern created with reduced dimensions |
| Pattern cache stale (new pattern not visible) | Cache TTL (60s) | New pattern visible within 60 seconds | Brief window where propagation does not apply |
| Database constraint violation | PERSIST steps | Transaction rollback; return 500 | HTTP 500 with error detail |

**Atomicity**: The entire disconfirmation (all accelerated decay applications + event record + pattern creation) is executed within a single database transaction. Either all persist or none persist. This prevents partial disconfirmation states.

---

## 13. Implementation Checklist

- [ ] Define `DisconfirmationProvenance` dataclass
- [ ] Define `DisconfirmationResult` dataclass
- [ ] Define `DisconfirmationPattern` dataclass
- [ ] Implement `DisconfirmationService.apply_disconfirmation()` per algorithm in Section 7
- [ ] Implement `DisconfirmationService.compute_propagation_penalty()` per algorithm in Section 8
- [ ] Implement pattern centroid computation (mean of valid embeddings per dimension)
- [ ] Implement entity pre-filter for pattern matching
- [ ] Implement in-memory pattern cache with 60-second TTL and invalidation on new disconfirmation
- [ ] Create REST endpoint `POST /api/v1/tenants/{tenant_id}/abeyance/disconfirm`
- [ ] Create database migration for `disconfirmation_events` table
- [ ] Create database migration for `disconfirmation_fragments` table
- [ ] Create database migration for `disconfirmation_patterns` table
- [ ] Add `negative_evidence_penalty`, `matching_disconfirmation_patterns`, `penalized_score` fields to `SnapDecisionRecord`
- [ ] Integrate `compute_propagation_penalty()` into snap evaluation pipeline (after composite score, before threshold comparison)
- [ ] Add pattern expiration cleanup to maintenance job
- [ ] Unit tests:
  - [ ] Disconfirm single fragment: score decreases, provenance logged
  - [ ] Disconfirm batch: all non-terminal fragments accelerated
  - [ ] Terminal fragment in batch: skipped, others processed
  - [ ] All terminal: 422 response
  - [ ] Propagation pattern created with correct centroid
  - [ ] Propagation penalty computed for similar fragment (sim >= 0.70)
  - [ ] No penalty for dissimilar fragment (sim < 0.70)
  - [ ] Penalty floor enforced (multiple patterns do not suppress below 0.30)
  - [ ] Pattern age decay reduces penalty over time
  - [ ] Expired pattern excluded from propagation
  - [ ] Entity pre-filter correctly excludes non-overlapping patterns
  - [ ] Tenant isolation: cross-tenant disconfirmation returns 404
  - [ ] Monotonicity: no stored decay score increases
  - [ ] Transaction atomicity: partial failure rolls back entire disconfirmation
