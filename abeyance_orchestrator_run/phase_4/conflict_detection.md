# Pattern Conflict Detection — Discovery Mechanism #6
## Abeyance Memory v3.0

**Task**: D2.1 — Pattern Conflict Detection Algorithm Design
**Version**: 3.0
**Date**: 2026-03-16
**Status**: Specification
**Discovery Tier**: TIER 2 — Feedback Loop (no LLM dependency)
**Reads**: `snap_scoring.md` (T1.4), `orm_schema.md` (T1.2)
**Writes to**: `conflict_record` table (new), `conflict_detection_log` table (new)

---

## 1. Problem Statement

The snap engine evaluates fragment *affinity* — it asks whether two fragments are evidence of the same underlying phenomenon. It is blind to the opposite question: are two fragments evidence of *contradictory* states for the same entity?

A telecom network can produce fragments that are structurally similar (same entities, same topology, same time window) but operationally opposite. A link_down alarm and a link_up alarm for the same interface, arriving within minutes of each other, share high entity overlap and high topological similarity but describe mutually exclusive interface states. The snap engine scores them as highly similar candidates. It does not detect that their operational content is contradictory. This is the gap.

**Pattern conflict detection** closes this gap. It operates as a Tier 2 feedback loop: it reads `snap_decision_record` rows (produced by Tier 1 snap scoring), identifies pairs where high entity overlap coexists with opposite operational polarity within a bounded time window, and persists a conflict record without attempting resolution.

**Scope limit**: This mechanism surfaces conflicts. It does not resolve them, does not invoke an LLM, and does not modify any fragment's `snap_status` or scores.

---

## 2. Definitions

### 2.1 Operational Polarity

**Polarity** is the operational state direction asserted by a fragment. For telecom fragments, polarity is derived from `failure_mode_tags` and structured fields in `operational_fingerprint`.

Polarity takes one of three values:

| Value | Meaning |
|---|---|
| `UP` | Fragment asserts a resource is operational, restored, or cleared |
| `DOWN` | Fragment asserts a resource is failed, degraded, or alarmed |
| `NEUTRAL` | Fragment does not assert a directional state (metric trend, configuration audit) |

**Opposite polarity** is defined as: one fragment has polarity `UP` and the other has polarity `DOWN`. Two `NEUTRAL` fragments are not in conflict. A `NEUTRAL` fragment paired with an `UP` or `DOWN` fragment is not in conflict.

### 2.2 Polarity Extraction Rules

Polarity is extracted from `failure_mode_tags` JSONB and `operational_fingerprint` JSONB. The extraction is a pure classification step — no embedding or LLM call.

**Rule priority**: Rules are evaluated top-to-bottom; first match wins.

```
POLARITY EXTRACTION FUNCTION extract_polarity(fragment):

    tags = fragment.failure_mode_tags   # JSONB array of tag strings
    op   = fragment.operational_fingerprint   # JSONB object

    # Rule 1: Explicit clear/restore tags → UP
    IF any tag in tags matches:
        { "link_up", "interface_up", "port_up", "bgp_established",
          "ospf_full", "lsp_up", "tunnel_up", "path_restored",
          "alarm_clear", "fault_cleared", "service_restored",
          "up", "restored", "cleared", "online", "active" }
    → RETURN UP

    # Rule 2: Explicit failure/degradation tags → DOWN
    IF any tag in tags matches:
        { "link_down", "interface_down", "port_down", "bgp_idle",
          "bgp_active", "ospf_down", "lsp_down", "tunnel_down",
          "path_failed", "alarm_raise", "fault_raised", "service_degraded",
          "service_down", "down", "failed", "degraded", "offline",
          "unreachable", "flapping", "packet_loss", "high_error_rate" }
    → RETURN DOWN

    # Rule 3: Operational fingerprint severity field → DOWN
    IF op contains key "severity" AND op["severity"] in
        { "CRITICAL", "MAJOR", "MINOR" }
    → RETURN DOWN

    # Rule 4: Operational fingerprint resolution field → UP
    IF op contains key "event_type" AND op["event_type"] in
        { "CLEAR", "RESTORE", "RESOLVE" }
    → RETURN UP

    # Rule 5: No determinable polarity
    → RETURN NEUTRAL
```

**Polarity is cached on the fragment**: To avoid re-evaluating rules on every conflict scan, the extracted polarity is stored as a computed column (see Section 5.1). It is recomputed only when `failure_mode_tags` or `operational_fingerprint` changes (i.e., during enrichment or manual update).

### 2.3 Entity Overlap Threshold for Conflict Candidacy

Two fragments are **conflict candidates** when their entity overlap meets or exceeds the conflict candidacy threshold:

```
CONFLICT_ENTITY_OVERLAP_THRESHOLD = 0.40
```

This threshold uses the same Jaccard score already computed and stored in `snap_decision_record.score_entity_overlap`. No recomputation is needed.

**Rationale for 0.40**: Entity overlap of 0.40 means the intersection is at least 40% of the union of both entity sets. For telecom fragments, this reliably selects pairs that involve the same network elements. A threshold below 0.30 admits fragment pairs that are tangentially related (e.g., two fragments on the same node but different interfaces). A threshold above 0.60 risks missing flapping scenarios where alarm text variation reduces entity extraction overlap slightly.

### 2.4 Time Window for Conflict Relevance

Two fragments are within the **conflict time window** when their event timestamps satisfy:

```
CONFLICT_TIME_WINDOW_SECONDS = 3600   # 1 hour
```

```
|fragment_a.event_timestamp - fragment_b.event_timestamp| <= CONFLICT_TIME_WINDOW_SECONDS
```

**If `event_timestamp` is NULL for either fragment**, fall back to `ingestion_timestamp`.

**Rationale for 1 hour**: Telecom state transitions (link flapping, BGP session instability, path failover/restore) typically complete within minutes. A 1-hour window is wide enough to capture oscillation patterns (up/down/up within the same incident window) while tight enough to exclude unrelated events on the same equipment during different maintenance windows or different incident periods. Conflicts detected outside this window are not false — they may represent distinct incidents on the same entity — which is why this is a *relevance* window, not an existence window.

---

## 3. Detection Algorithm

### 3.1 Trigger

Conflict detection runs in two modes:

**Triggered mode** (primary path): Invoked after any new `snap_decision_record` is written where `score_entity_overlap >= CONFLICT_ENTITY_OVERLAP_THRESHOLD`. The new record identifies a candidate pair. The trigger avoids full-table scans on the hot path.

**Sweep mode** (background path): A scheduled sweep runs every 15 minutes. It queries `snap_decision_record` for all records within the last `CONFLICT_TIME_WINDOW_SECONDS * 2` where `score_entity_overlap >= CONFLICT_ENTITY_OVERLAP_THRESHOLD` and `decision IN ('SNAP', 'NEAR_MISS', 'AFFINITY')`. This catches any pairs missed by the triggered path (e.g., due to process restart or triggered-mode skips).

### 3.2 Algorithm

```
FUNCTION detect_conflict(tenant_id, fragment_a_id, fragment_b_id):

    # --- Step 1: Load fragments ---
    frag_a = load_fragment(tenant_id, fragment_a_id)
    frag_b = load_fragment(tenant_id, fragment_b_id)

    IF frag_a is NULL OR frag_b is NULL:
        LOG conflict_detection_log(
            tenant_id, fragment_a_id, fragment_b_id,
            result="SKIPPED", reason="FRAGMENT_NOT_FOUND"
        )
        RETURN

    # --- Step 2: Check snap_status eligibility ---
    # Only consider fragments that have not yet reached terminal states
    ELIGIBLE_STATUSES = { 'INGESTED', 'ACTIVE', 'NEAR_MISS' }
    IF frag_a.snap_status NOT IN ELIGIBLE_STATUSES
    OR frag_b.snap_status NOT IN ELIGIBLE_STATUSES:
        LOG conflict_detection_log(
            ..., result="SKIPPED", reason="INELIGIBLE_STATUS"
        )
        RETURN

    # --- Step 3: Extract polarity ---
    polarity_a = extract_polarity(frag_a)
    polarity_b = extract_polarity(frag_b)

    # --- Step 4: Check for opposite polarity ---
    IF NOT (
        (polarity_a == UP AND polarity_b == DOWN) OR
        (polarity_a == DOWN AND polarity_b == UP)
    ):
        LOG conflict_detection_log(
            ..., result="NO_CONFLICT", reason="POLARITY_NOT_OPPOSITE",
            polarity_a=polarity_a, polarity_b=polarity_b
        )
        RETURN

    # --- Step 5: Verify entity overlap threshold ---
    # Prefer the score already stored in snap_decision_record
    sdr = load_snap_decision_record(tenant_id, fragment_a_id, fragment_b_id)
    IF sdr is NOT NULL:
        entity_overlap_score = sdr.score_entity_overlap
    ELSE:
        # Fallback: compute Jaccard directly (should be rare in triggered mode)
        entity_overlap_score = jaccard(
            entities(frag_a), entities(frag_b)
        )

    IF entity_overlap_score < CONFLICT_ENTITY_OVERLAP_THRESHOLD:
        LOG conflict_detection_log(
            ..., result="NO_CONFLICT", reason="ENTITY_OVERLAP_BELOW_THRESHOLD",
            entity_overlap_score=entity_overlap_score
        )
        RETURN

    # --- Step 6: Verify time window ---
    ts_a = frag_a.event_timestamp ?? frag_a.ingestion_timestamp
    ts_b = frag_b.event_timestamp ?? frag_b.ingestion_timestamp
    time_delta_seconds = abs(ts_a - ts_b).total_seconds()

    IF time_delta_seconds > CONFLICT_TIME_WINDOW_SECONDS:
        LOG conflict_detection_log(
            ..., result="NO_CONFLICT", reason="OUTSIDE_TIME_WINDOW",
            time_delta_seconds=time_delta_seconds
        )
        RETURN

    # --- Step 7: Deduplication check ---
    existing = load_conflict_record(
        tenant_id,
        fragment_a_id=min(fragment_a_id, fragment_b_id),
        fragment_b_id=max(fragment_a_id, fragment_b_id)
    )
    IF existing is NOT NULL:
        LOG conflict_detection_log(
            ..., result="DUPLICATE", reason="CONFLICT_ALREADY_RECORDED",
            existing_conflict_id=existing.id
        )
        RETURN

    # --- Step 8: Extract conflicting entities (intersection) ---
    conflicting_entities = entities(frag_a) INTERSECT entities(frag_b)

    # --- Step 9: Compute polarity description ---
    polarity_description = build_polarity_description(
        frag_a, polarity_a, frag_b, polarity_b
    )
    # Returns a structured string, e.g.:
    # "FRAGMENT_A asserts DOWN (tags: link_down, fault_raised) for
    #  entities [ge-0/0/1.0, Router-CORE-01]; FRAGMENT_B asserts UP
    #  (tags: link_up, alarm_clear) for same entities"

    # --- Step 10: Persist conflict record ---
    conflict = ConflictRecord(
        tenant_id            = tenant_id,
        fragment_a_id        = min(fragment_a_id, fragment_b_id),
        fragment_b_id        = max(fragment_a_id, fragment_b_id),
        entity_overlap_score = entity_overlap_score,
        conflicting_entities = conflicting_entities,
        polarity_a           = polarity_a,
        polarity_b           = polarity_b,
        polarity_description = polarity_description,
        time_delta_seconds   = time_delta_seconds,
        detection_mode       = "TRIGGERED" | "SWEEP",
        detected_at          = now()
    )
    PERSIST conflict

    LOG conflict_detection_log(
        ..., result="CONFLICT_RECORDED",
        conflict_id=conflict.id
    )
```

### 3.3 `build_polarity_description` Function

```
FUNCTION build_polarity_description(frag_a, polarity_a, frag_b, polarity_b):

    down_frag = frag_a IF polarity_a == DOWN ELSE frag_b
    up_frag   = frag_a IF polarity_a == UP   ELSE frag_b

    down_tags = [t for t in down_frag.failure_mode_tags
                 if t matches DOWN rule patterns]
    up_tags   = [t for t in up_frag.failure_mode_tags
                 if t matches UP rule patterns]

    shared_entities = entities(frag_a) INTERSECT entities(frag_b)

    RETURN (
        f"DOWN fragment {down_frag.id} asserts failure state "
        f"(tags: {down_tags[:3]}) "
        f"UP fragment {up_frag.id} asserts restored/operational state "
        f"(tags: {up_tags[:3]}) "
        f"Conflicting entities: {sorted(shared_entities)[:10]}"
    )
```

The polarity description is a human-readable summary stored for operator inspection. It is NOT used in any downstream computation.

---

## 4. Storage: Conflict Record Schema

### 4.1 `conflict_record` Table

```sql
CREATE TABLE conflict_record (
    -- Identity
    id                   UUID         NOT NULL DEFAULT gen_random_uuid()  PRIMARY KEY,
    tenant_id            VARCHAR(100) NOT NULL,

    -- Fragment pair (canonical ordering: smaller UUID first)
    fragment_a_id        UUID         NOT NULL,
    fragment_b_id        UUID         NOT NULL,

    -- Entity overlap evidence
    entity_overlap_score FLOAT        NOT NULL,
    -- Jaccard score from snap_decision_record or freshly computed.
    -- Range: [CONFLICT_ENTITY_OVERLAP_THRESHOLD, 1.0]

    conflicting_entities JSONB        NOT NULL DEFAULT '[]'::jsonb,
    -- Intersection of extracted_entities from both fragments.
    -- Array of entity identifier strings.
    -- Example: ["ge-0/0/1.0", "Router-CORE-01", "AS65001"]

    -- Polarity
    polarity_a           VARCHAR(10)  NOT NULL,
    -- 'UP' | 'DOWN' (NEUTRAL fragments never reach this table)
    polarity_b           VARCHAR(10)  NOT NULL,
    -- 'UP' | 'DOWN' (always opposite to polarity_a)

    polarity_description TEXT         NOT NULL,
    -- Human-readable summary of the conflict (see Section 3.3).
    -- Not used in computation. For operator inspection only.

    -- Time delta
    time_delta_seconds   FLOAT        NOT NULL,
    -- Absolute time between fragment event timestamps.
    -- Range: [0, CONFLICT_TIME_WINDOW_SECONDS]

    -- Detection metadata
    detection_mode       VARCHAR(20)  NOT NULL,
    -- 'TRIGGERED' | 'SWEEP'

    detected_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),

    -- Resolution state (managed externally, not by this mechanism)
    resolution_status    VARCHAR(20)  NOT NULL DEFAULT 'OPEN',
    -- 'OPEN' | 'ACKNOWLEDGED' | 'RESOLVED_EXTERNALLY'
    -- Set by operator or future resolution mechanism. NEVER set by this mechanism.

    resolved_at          TIMESTAMP WITH TIME ZONE,
    -- NULL until resolution_status changes from 'OPEN'

    -- Constraints
    CONSTRAINT uq_conflict_pair
        UNIQUE (tenant_id, fragment_a_id, fragment_b_id),
    CONSTRAINT chk_polarity_opposite
        CHECK (polarity_a != polarity_b),
    CONSTRAINT chk_polarity_values
        CHECK (polarity_a IN ('UP', 'DOWN') AND polarity_b IN ('UP', 'DOWN')),
    CONSTRAINT chk_entity_overlap_range
        CHECK (entity_overlap_score >= 0.0 AND entity_overlap_score <= 1.0),
    CONSTRAINT chk_time_delta_nonneg
        CHECK (time_delta_seconds >= 0.0),
    CONSTRAINT chk_fragment_order
        CHECK (fragment_a_id < fragment_b_id)
    -- Canonical ordering enforced at application layer and by this constraint.
);

-- Indexes
CREATE INDEX ix_conflict_record_tenant_detected
    ON conflict_record (tenant_id, detected_at DESC);

CREATE INDEX ix_conflict_record_tenant_status
    ON conflict_record (tenant_id, resolution_status)
    WHERE resolution_status = 'OPEN';

CREATE INDEX ix_conflict_record_fragment_a
    ON conflict_record (tenant_id, fragment_a_id);

CREATE INDEX ix_conflict_record_fragment_b
    ON conflict_record (tenant_id, fragment_b_id);

CREATE INDEX ix_conflict_record_entities
    ON conflict_record USING GIN (conflicting_entities jsonb_path_ops);
```

### 4.2 ORM Model

```python
class ConflictRecordORM(Base):
    __tablename__ = "conflict_record"

    id                   = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id            = Column(String(100), nullable=False)
    fragment_a_id        = Column(UUID(as_uuid=True), nullable=False)
    fragment_b_id        = Column(UUID(as_uuid=True), nullable=False)
    entity_overlap_score = Column(Float, nullable=False)
    conflicting_entities = Column(JSONB, nullable=False, default=list)
    polarity_a           = Column(String(10), nullable=False)
    polarity_b           = Column(String(10), nullable=False)
    polarity_description = Column(Text, nullable=False)
    time_delta_seconds   = Column(Float, nullable=False)
    detection_mode       = Column(String(20), nullable=False)
    detected_at          = Column(DateTime(timezone=True), nullable=False,
                                  server_default=func.now())
    resolution_status    = Column(String(20), nullable=False, default="OPEN")
    resolved_at          = Column(DateTime(timezone=True), nullable=True)
```

---

## 5. Polarity Column (Cached Extraction)

To avoid re-running polarity extraction on every conflict scan, polarity is cached as a computed column on `abeyance_fragment`.

### 5.1 Schema Addition to `abeyance_fragment`

```sql
ALTER TABLE abeyance_fragment
    ADD COLUMN polarity VARCHAR(10) NOT NULL DEFAULT 'NEUTRAL';

-- Values: 'UP' | 'DOWN' | 'NEUTRAL'
-- Set by enrichment pipeline after failure_mode_tags is populated.
-- Re-evaluated whenever failure_mode_tags or operational_fingerprint changes.

CREATE INDEX ix_abeyance_fragment_polarity
    ON abeyance_fragment (tenant_id, polarity)
    WHERE snap_status IN ('INGESTED', 'ACTIVE', 'NEAR_MISS');
```

### 5.2 Population Responsibility

The enrichment chain (T1.3 `enrichment_chain.md`) is responsible for calling `extract_polarity()` and writing the result to `abeyance_fragment.polarity` after tag extraction completes. The conflict detection algorithm reads this column; it does not run the extraction function itself except as a fallback when `polarity` is `NEUTRAL` and the tag content has changed since last enrichment (detected via `updated_at` timestamp comparison against last enrichment timestamp).

---

## 6. Provenance: Conflict Detection Log

Every invocation of `detect_conflict()` — whether or not it produces a conflict record — is logged to `conflict_detection_log`. This log is append-only and provides a complete audit trail.

### 6.1 `conflict_detection_log` Table

```sql
CREATE TABLE conflict_detection_log (
    -- Identity
    id               UUID         NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    tenant_id        VARCHAR(100) NOT NULL,

    -- Pair evaluated
    fragment_a_id    UUID         NOT NULL,
    fragment_b_id    UUID         NOT NULL,

    -- Outcome
    result           VARCHAR(30)  NOT NULL,
    -- 'CONFLICT_RECORDED' | 'NO_CONFLICT' | 'DUPLICATE' | 'SKIPPED' | 'ERROR'

    reason           VARCHAR(80),
    -- Populated when result != 'CONFLICT_RECORDED'.
    -- Values:
    --   FRAGMENT_NOT_FOUND        (Step 2: fragment missing)
    --   INELIGIBLE_STATUS         (Step 2: terminal snap_status)
    --   POLARITY_NOT_OPPOSITE     (Step 4: same polarity or NEUTRAL)
    --   ENTITY_OVERLAP_BELOW_THRESHOLD (Step 5: Jaccard too low)
    --   OUTSIDE_TIME_WINDOW       (Step 6: time delta exceeded)
    --   CONFLICT_ALREADY_RECORDED (Step 7: dedup hit)
    --   INTERNAL_ERROR            (exception during detection)

    conflict_id      UUID,
    -- Foreign key to conflict_record.id when result = 'CONFLICT_RECORDED'.
    -- NULL otherwise.

    -- Supporting values (for diagnostics)
    polarity_a       VARCHAR(10),
    polarity_b       VARCHAR(10),
    entity_overlap_score FLOAT,
    time_delta_seconds   FLOAT,

    -- Timing
    detection_mode   VARCHAR(20)  NOT NULL,
    -- 'TRIGGERED' | 'SWEEP'

    logged_at        TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

-- Indexes
CREATE INDEX ix_conflict_log_tenant_logged
    ON conflict_detection_log (tenant_id, logged_at DESC);

CREATE INDEX ix_conflict_log_fragment_a
    ON conflict_detection_log (tenant_id, fragment_a_id);

CREATE INDEX ix_conflict_log_result
    ON conflict_detection_log (tenant_id, result, logged_at DESC);
```

### 6.2 Log Retention Policy

The `conflict_detection_log` retains rows for 90 days. Rows older than 90 days are moved to cold archive or deleted on a nightly sweep. `conflict_record` rows are retained indefinitely until explicitly resolved and archived.

---

## 7. Explicit Scope Limit

**This mechanism surfaces conflicts. It does not resolve them.**

Specifically:

- `conflict_record.resolution_status` is set to `'OPEN'` on creation and is NEVER modified by the conflict detection algorithm.
- The conflict detection algorithm does NOT modify `abeyance_fragment.snap_status`.
- The conflict detection algorithm does NOT modify `snap_decision_record` rows.
- The conflict detection algorithm does NOT create accumulation graph edges or cluster assignments.
- The conflict detection algorithm does NOT invoke an LLM, call an external service, or produce hypotheses.
- Hidden variable search (why the conflict exists) is explicitly out of scope for this mechanism.
- Automated resolution (choosing which fragment represents truth) is explicitly out of scope for this mechanism.

The downstream consumer of `conflict_record` is the human operator and/or a future Tier 3 (LLM-assisted) resolution mechanism. That mechanism is not designed here.

---

## 8. Concrete Telecom Example

### 8.1 Scenario

**Network context**: A BGP peering session between `Router-CORE-01` (AS65001) and `Router-EDGE-07` (AS65002) over interface `ge-0/0/1.0` experiences a session flap at 14:32 UTC on 2026-03-16.

**Timeline**:
- `14:32:04` — BGP session drops. SNMP trap generated. Alarm raised in OSS.
- `14:32:47` — BGP session re-establishes. SNMP clear trap generated. Alarm cleared in OSS.
- Both fragments ingested by Abeyance Memory within seconds of their events.

### 8.2 Fragments Produced

**Fragment A** (`id: frag-9a3c...`):
```json
{
  "source_type": "ALARM",
  "event_timestamp": "2026-03-16T14:32:04Z",
  "failure_mode_tags": ["bgp_idle", "link_down", "alarm_raise"],
  "extracted_entities": {
    "devices": ["Router-CORE-01", "Router-EDGE-07"],
    "interfaces": ["ge-0/0/1.0"],
    "as_numbers": ["AS65001", "AS65002"],
    "protocols": ["BGP"]
  },
  "operational_fingerprint": {
    "severity": "CRITICAL",
    "event_type": "RAISE",
    "protocol": "BGP",
    "session_state": "IDLE"
  }
}
```

Extracted polarity: **DOWN** (rule 2 match: `bgp_idle`, `link_down`, `alarm_raise`)

**Fragment B** (`id: frag-c71e...`):
```json
{
  "source_type": "ALARM",
  "event_timestamp": "2026-03-16T14:32:47Z",
  "failure_mode_tags": ["bgp_established", "link_up", "alarm_clear"],
  "extracted_entities": {
    "devices": ["Router-CORE-01", "Router-EDGE-07"],
    "interfaces": ["ge-0/0/1.0"],
    "as_numbers": ["AS65001", "AS65002"],
    "protocols": ["BGP"]
  },
  "operational_fingerprint": {
    "severity": "CLEAR",
    "event_type": "CLEAR",
    "protocol": "BGP",
    "session_state": "ESTABLISHED"
  }
}
```

Extracted polarity: **UP** (rule 1 match: `bgp_established`, `link_up`, `alarm_clear`)

### 8.3 Conflict Detection Execution

**Step 3**: `polarity_a = DOWN`, `polarity_b = UP` → opposite polarity confirmed.

**Step 5**: Entity union = {`Router-CORE-01`, `Router-EDGE-07`, `ge-0/0/1.0`, `AS65001`, `AS65002`, `BGP`} = 6 elements. Entity intersection = same 6 elements. Jaccard = 6/6 = **1.0**. Threshold 0.40 satisfied.

**Step 6**: `|14:32:04 - 14:32:47|` = **43 seconds**. Time window 3600 seconds satisfied.

**Step 9**: Polarity description:
```
DOWN fragment frag-9a3c asserts failure state (tags: bgp_idle, link_down, alarm_raise)
UP fragment frag-c71e asserts restored/operational state (tags: bgp_established, link_up, alarm_clear)
Conflicting entities: [AS65001, AS65002, BGP, Router-CORE-01, Router-EDGE-07, ge-0/0/1.0]
```

**Step 10**: `ConflictRecord` persisted:

```json
{
  "tenant_id": "telco2",
  "fragment_a_id": "frag-9a3c...",
  "fragment_b_id": "frag-c71e...",
  "entity_overlap_score": 1.0,
  "conflicting_entities": [
    "AS65001", "AS65002", "BGP",
    "Router-CORE-01", "Router-EDGE-07", "ge-0/0/1.0"
  ],
  "polarity_a": "DOWN",
  "polarity_b": "UP",
  "polarity_description": "DOWN fragment frag-9a3c asserts failure state (tags: bgp_idle, link_down, alarm_raise) UP fragment frag-c71e asserts restored/operational state (tags: bgp_established, link_up, alarm_clear) Conflicting entities: [AS65001, AS65002, BGP, Router-CORE-01, Router-EDGE-07, ge-0/0/1.0]",
  "time_delta_seconds": 43.0,
  "detection_mode": "TRIGGERED",
  "resolution_status": "OPEN"
}
```

### 8.4 What the Conflict Record Enables

The operator or a downstream mechanism can observe: the same BGP session asserted both DOWN and UP within 43 seconds, with complete entity agreement. This is the signature of a BGP session flap. Without conflict detection, the snap engine would have grouped these two fragments as high-affinity candidates (they share all entities, same topology, similar temporal context), potentially snapping them to the same hypothesis as corroborating evidence — which is incorrect. They are not corroborating evidence; they are contradictory observations of a transient state transition.

The conflict record surfaces this contradiction as a first-class signal. What happens next (hypothesis refinement, flap detection, operator acknowledgment) is outside this mechanism's scope.

---

## 9. Algorithm Invariants

| ID | Statement | Enforcement |
|---|---|---|
| CONF-INV-1 | Conflict records are never created for NEUTRAL-polarity fragments | Step 4 of algorithm: NEUTRAL fragments exit before persistence |
| CONF-INV-2 | Fragment pair is stored in canonical order (smaller UUID first) | `chk_fragment_order` CHECK constraint + application-layer enforcement |
| CONF-INV-3 | Each unique pair has at most one open conflict record | `uq_conflict_pair` UNIQUE constraint |
| CONF-INV-4 | `polarity_a` and `polarity_b` are always opposite | `chk_polarity_opposite` CHECK constraint |
| CONF-INV-5 | `entity_overlap_score` is within `[0.0, 1.0]` | `chk_entity_overlap_range` CHECK constraint |
| CONF-INV-6 | `resolution_status` is never modified by this mechanism | Enforced by architecture: only operator-facing APIs or future Tier 3 mechanisms write to `resolution_status` |
| CONF-INV-7 | Every invocation of `detect_conflict()` is logged | `conflict_detection_log` write occurs before early returns and before persistence |
| CONF-INV-8 | Polarity extraction uses no external dependency | `extract_polarity()` is a pure tag-matching function; no LLM, no network call |

---

## 10. Configuration Constants Summary

| Constant | Value | Tunable | Notes |
|---|---|---|---|
| `CONFLICT_ENTITY_OVERLAP_THRESHOLD` | 0.40 | Yes | Lower bound to admit more candidates; raise to reduce false positives |
| `CONFLICT_TIME_WINDOW_SECONDS` | 3600 | Yes | 1 hour; reduce for stricter flap detection, raise for slow oscillations |
| `CONFLICT_LOG_RETENTION_DAYS` | 90 | Yes | Detection log only; conflict records retained indefinitely |

All constants are read from the application configuration at startup. No hardcoded values in algorithm code.

---

## 11. Interaction with Existing Subsystems

### 11.1 Snap Decision Record (read-only dependency)

Conflict detection reads `snap_decision_record.score_entity_overlap` to avoid recomputing Jaccard on the triggered path. This is the primary efficiency gain of the triggered mode. The conflict detection mechanism never writes to `snap_decision_record`.

### 11.2 Abeyance Fragment (adds `polarity` column)

A new `polarity` column is added to `abeyance_fragment` (Section 5.1). This is the only schema modification to existing tables. The enrichment chain populates it. Conflict detection reads it.

### 11.3 Accumulation Graph (no interaction)

Conflict detection does not read or write to `accumulation_edge` or any cluster detection structure. Conflict is a pairwise relationship, not a cluster-level property.

### 11.4 Surprise Engine (no interaction)

The surprise engine (Discovery Mechanism #1) operates on the distribution of snap scores. Conflict detection operates on the polarity of fragment content. They are independent feedback loops. A conflicting pair may or may not be surprising in the snap scoring sense.

### 11.5 Bridge Detection (no interaction)

Bridge detection (Discovery Mechanism #4) operates on graph topology. Conflict detection operates on pairwise content semantics. They address orthogonal discovery questions.

---

Generated: 2026-03-16 | Task D2.1 | Abeyance Memory v3.0
