# Temporal Sequence Modelling -- Discovery Mechanism #7

**Task**: D2.1 -- Temporal Sequence Infrastructure
**Version**: 3.0
**Date**: 2026-03-16
**Status**: Specification
**Tier**: 2 (Feedback Loop -- no LLM dependency; counting-based estimation only)
**Depends on**: Tier 1 mechanisms (Surprise, Ignorance, Negative Evidence, Bridge Detection)
**Enables**: Tier 3 mechanisms (Hypothesis Generation, Expectation Violation Detection T5.2, Causal Direction Testing)

---

## 1. Problem Statement

Abeyance Memory ingests fragments about network entities over time -- alarms, telemetry events, CLI outputs, change records. Each fragment carries an `event_timestamp` and references one or more entities via `fragment_entity_ref`. The current system treats each fragment independently: the snap engine scores pairwise similarity, the accumulation graph groups fragments by affinity, but **no subsystem models the temporal ordering of states for a given entity**.

This is a structural blind spot. Without temporal sequence modelling:

1. **Expectation Violation Detection (T5.2) has no baseline**: It cannot determine "this eNB went from normal to alarm without the expected degraded phase" because no record of the expected transition sequence exists.
2. **Causal Direction Testing has no arrow of time**: It cannot distinguish "A precedes B reliably" from "A and B co-occur" because there is no per-entity event log with ordering guarantees.
3. **Operators cannot see entity trajectories**: An entity's journey through states is implicit in the fragment table, scattered across rows with no direct path from "show me the last 30 state transitions for ENB-4412".

This specification defines two artefacts:

- **Entity Sequence Log**: Per-entity, tenant-isolated, time-ordered record of fragment observations.
- **Transition Probability Matrix**: Per-entity-type counting-based estimation of P(state_j | state_i), updated incrementally as new fragments arrive.

**What this is**: Cheap infrastructure that organises existing fragment data into temporal sequences and computes frequency-based transition statistics. Pure counting. No LLM. No embeddings.

**What this is NOT**: This does NOT detect expectation violations (T5.2 consumes these matrices to do that). This does NOT infer causality (Tier 3 does that). This does NOT generate hypotheses.

---

## 2. Definitions

### 2.1 Entity State

An entity's **state at time t** is derived from the fragment that references it at time t. The state is a composite key:

```
state = (fragment_type, source_type, severity_bucket)
```

Where:
- `fragment_type`: Derived from the fragment's `failure_mode_tags`. If multiple failure modes are present, the highest-severity tag is selected. If no failure mode tags exist, the fragment_type is `NOMINAL`.
- `source_type`: The fragment's `source_type` column (ALARM, LOG, METRIC, MANUAL, SYNTHETIC, TICKET_TEXT, TELEMETRY_EVENT, CLI_OUTPUT, CHANGE_RECORD, CMDB_DELTA).
- `severity_bucket`: Derived from `operational_fingerprint` severity fields. One of: `CRITICAL`, `MAJOR`, `MINOR`, `WARNING`, `CLEAR`, `INFO`, `UNKNOWN`.

**Canonical state string**: These three components are concatenated as `{fragment_type}:{source_type}:{severity_bucket}`, e.g., `DARK_NODE:ALARM:CRITICAL` or `NOMINAL:TELEMETRY_EVENT:INFO`.

### 2.2 State Vocabulary

The set of distinct states observed for a given `(tenant_id, entity_domain)` pair forms the state vocabulary. The vocabulary grows dynamically as new state combinations are observed. No pre-enumeration is required.

### 2.3 Transition

A **transition** is an ordered pair `(state_i, state_j)` observed for a single entity where `state_j` immediately follows `state_i` in the entity's time-ordered sequence log. "Immediately follows" means there is no intervening fragment referencing the same entity with an event_timestamp between the two.

### 2.4 Self-Transitions

A transition where `state_i == state_j` is a **self-transition**. These are valid and counted. An entity remaining in `NOMINAL:TELEMETRY_EVENT:INFO` across 50 consecutive observations produces 49 self-transitions. Self-transitions are the dominant signal for stable states and their frequency is meaningful.

---

## 3. Storage Schema

### 3.1 Table: `entity_sequence_log`

Per-entity, tenant-isolated, time-ordered record of fragment observations.

| Column Name | Type | Nullable | Default | Constraints | Notes |
|---|---|---|---|---|---|
| id | BIGSERIAL | NO | auto | PRIMARY KEY | Monotonic surrogate for ordering within ties |
| tenant_id | VARCHAR(100) | NO | - | NOT NULL | Tenant isolation (INV-7) |
| entity_id | UUID | NO | - | NOT NULL, FK -> shadow_entity.id | Entity being tracked |
| entity_identifier | VARCHAR(500) | NO | - | NOT NULL | Denormalized for query convenience |
| entity_domain | VARCHAR(50) | YES | NULL | - | Denormalized from shadow_entity |
| fragment_id | UUID | NO | - | NOT NULL, FK -> abeyance_fragment.id | Source fragment |
| event_timestamp | TIMESTAMP WITH TIME ZONE | NO | - | NOT NULL | From fragment.event_timestamp |
| state_key | VARCHAR(200) | NO | - | NOT NULL | Canonical state string (Section 2.1) |
| fragment_type | VARCHAR(50) | NO | 'NOMINAL' | NOT NULL | Component of state_key |
| source_type | VARCHAR(50) | NO | - | NOT NULL | Component of state_key |
| severity_bucket | VARCHAR(20) | NO | 'UNKNOWN' | NOT NULL | Component of state_key |
| created_at | TIMESTAMP WITH TIME ZONE | NO | now() | NOT NULL, server_default | Row creation time |

**Design decisions**:
- `BIGSERIAL` id instead of UUID: Sequence logs are append-only, high-volume, and need cheap ordering. BIGSERIAL provides monotonic ordering for free, which resolves ties in event_timestamp (two fragments for the same entity at the same second are ordered by insertion sequence).
- `entity_identifier` and `entity_domain` are denormalized from `shadow_entity` to avoid joins on read-heavy sequence queries.
- `state_key` is stored materialized (not computed on read) because it is the primary lookup key for transition counting.

#### 3.1.1 Indexes

| Index Name | Columns | Type | Notes |
|---|---|---|---|
| ix_esl_entity_time | (tenant_id, entity_id, event_timestamp, id) | BTREE | Primary query path: "get ordered sequence for entity". The `id` column breaks timestamp ties. |
| ix_esl_tenant_time | (tenant_id, event_timestamp) | BTREE | Background maintenance: "scan all events in time window for tenant". |
| ix_esl_fragment | (fragment_id) | BTREE | Reverse lookup: "which sequence entries came from this fragment". |
| ix_esl_state_key | (tenant_id, entity_domain, state_key) | BTREE | State vocabulary queries and transition matrix population. |

#### 3.1.2 Partitioning

For tenants with high fragment volume (>1M sequence entries), partition `entity_sequence_log` by `(tenant_id, event_timestamp)` using PostgreSQL declarative range partitioning on monthly boundaries. Partitioning is optional -- the indexes above are sufficient for moderate volumes. The application layer creates partitions lazily when a tenant crosses the 1M row threshold.

#### 3.1.3 Retention

Sequence log entries follow the same retention policy as the source fragments:
- When a fragment transitions to COLD or is deleted, the corresponding sequence log entries are NOT deleted (they are needed for historical transition statistics).
- Sequence log entries older than `max_sequence_retention_days` (default: 1095, i.e., 3 years) are purged by the maintenance sweep.
- The retention period is deliberately longer than fragment `max_lifetime_days` (730) because transition statistics benefit from longer historical context.

---

### 3.2 Table: `transition_matrix`

Stores the counting-based transition probability matrix per `(tenant_id, entity_domain)`.

| Column Name | Type | Nullable | Default | Constraints | Notes |
|---|---|---|---|---|---|
| id | UUID | NO | uuid4() | PRIMARY KEY | Matrix record ID |
| tenant_id | VARCHAR(100) | NO | - | NOT NULL | Tenant isolation (INV-7) |
| entity_domain | VARCHAR(50) | NO | - | NOT NULL | Domain partition (RAN, TRANSPORT, IP, CORE, VNF, etc.) |
| from_state | VARCHAR(200) | NO | - | NOT NULL | Source state (state_key) |
| to_state | VARCHAR(200) | NO | - | NOT NULL | Target state (state_key) |
| transition_count | INTEGER | NO | 0 | NOT NULL, DEFAULT | Raw count of observed transitions |
| total_from_count | INTEGER | NO | 0 | NOT NULL, DEFAULT | Total transitions FROM from_state (denominator for P(to|from)) |
| probability | FLOAT | NO | 0.0 | NOT NULL, DEFAULT | transition_count / total_from_count. Recomputed on update. |
| first_observed | TIMESTAMP WITH TIME ZONE | NO | now() | NOT NULL, server_default | First time this transition was seen |
| last_observed | TIMESTAMP WITH TIME ZONE | NO | now() | NOT NULL, server_default | Most recent observation of this transition |
| observation_window_start | TIMESTAMP WITH TIME ZONE | NO | - | NOT NULL | Left edge of the counting window |
| matrix_version | INTEGER | NO | 1 | NOT NULL, DEFAULT | Incremented on every update batch |
| updated_at | TIMESTAMP WITH TIME ZONE | NO | now() | NOT NULL, server_default | Last recomputation time |

**Design decisions**:
- One row per `(tenant_id, entity_domain, from_state, to_state)` tuple. This is a sparse representation -- only observed transitions have rows. A dense NxN matrix would waste storage on zero-count cells.
- `total_from_count` is denormalized: it equals `SUM(transition_count) WHERE from_state = X` for that partition. Stored per-row so that `probability` can be read without aggregation. Updated atomically with `transition_count`.
- `probability` is stored materialized for read performance. Recomputed whenever `transition_count` or `total_from_count` changes.
- Partitioned by `entity_domain` because different domains have fundamentally different state vocabularies (RAN states look nothing like IP states).

#### 3.2.1 Indexes

| Index Name | Columns | Type | Notes |
|---|---|---|---|
| uq_tm_transition | (tenant_id, entity_domain, from_state, to_state) | UNIQUE | Ensures one row per transition pair per partition. Upsert target. |
| ix_tm_from_state | (tenant_id, entity_domain, from_state) | BTREE | "Given state X, what are the probable next states?" -- the primary consumer query for T5.2 Expectation Violation. |
| ix_tm_probability | (tenant_id, entity_domain, probability) | BTREE | "Which transitions are rare?" -- used by T5.2 to find unexpected transitions. |
| ix_tm_version | (tenant_id, entity_domain, matrix_version) | BTREE | Version-based cache invalidation. |

#### 3.2.2 CHECK Constraints

```sql
ALTER TABLE transition_matrix
  ADD CONSTRAINT chk_tm_count_positive
    CHECK (transition_count >= 0);

ALTER TABLE transition_matrix
  ADD CONSTRAINT chk_tm_total_positive
    CHECK (total_from_count >= 0);

ALTER TABLE transition_matrix
  ADD CONSTRAINT chk_tm_probability_range
    CHECK (probability >= 0.0 AND probability <= 1.0);

ALTER TABLE transition_matrix
  ADD CONSTRAINT chk_tm_count_lte_total
    CHECK (transition_count <= total_from_count);
```

---

### 3.3 Table: `transition_matrix_version`

Provenance record tracking each matrix recomputation.

| Column Name | Type | Nullable | Default | Constraints | Notes |
|---|---|---|---|---|---|
| id | UUID | NO | uuid4() | PRIMARY KEY | Version record ID |
| tenant_id | VARCHAR(100) | NO | - | NOT NULL | Tenant isolation (INV-7) |
| entity_domain | VARCHAR(50) | NO | - | NOT NULL | Domain partition |
| matrix_version | INTEGER | NO | - | NOT NULL | Version number (matches transition_matrix.matrix_version) |
| computed_at | TIMESTAMP WITH TIME ZONE | NO | now() | NOT NULL, server_default | When this version was computed |
| window_start | TIMESTAMP WITH TIME ZONE | NO | - | NOT NULL | Left edge of observation window |
| window_end | TIMESTAMP WITH TIME ZONE | NO | - | NOT NULL | Right edge of observation window |
| total_transitions_counted | INTEGER | NO | - | NOT NULL | Total transitions in this computation |
| distinct_states | INTEGER | NO | - | NOT NULL | Size of state vocabulary at this version |
| distinct_transitions | INTEGER | NO | - | NOT NULL | Number of distinct (from, to) pairs |
| trigger | VARCHAR(50) | NO | - | NOT NULL | What triggered recomputation: INCREMENTAL, FULL_RECOMPUTE, WINDOW_SLIDE, MANUAL |
| computation_duration_ms | INTEGER | YES | NULL | - | Wall-clock time for the computation |

#### 3.3.1 Indexes

| Index Name | Columns | Type | Notes |
|---|---|---|---|
| ix_tmv_tenant_domain_version | (tenant_id, entity_domain, matrix_version) | BTREE, UNIQUE | Lookup by version |
| ix_tmv_tenant_computed | (tenant_id, computed_at) | BTREE | "When was the last recomputation?" |

---

## 4. Sequence Log Population

### 4.1 Write Path: Inline with Enrichment Chain

When `enrichment_chain.enrich()` creates a new `AbeyanceFragmentORM` and its `FragmentEntityRefORM` entries, the temporal sequence service appends entries to `entity_sequence_log` for each referenced entity.

```
enrichment_chain.enrich()
  -> creates AbeyanceFragmentORM (fragment F)
  -> creates FragmentEntityRefORM entries (entity refs E1, E2, ...)
  -> calls temporal_sequence.record_observation(session, tenant_id, fragment F, entity_refs [E1, E2, ...])
```

### 4.2 State Derivation Logic

```python
def derive_state_key(fragment: AbeyanceFragmentORM) -> tuple[str, str, str]:
    """Derive the canonical state triple from a fragment."""

    # 1. fragment_type: highest-severity failure mode, or NOMINAL
    failure_modes = fragment.failure_mode_tags or []
    if failure_modes:
        # failure_mode_tags is a list of dicts: [{"mode": "DARK_NODE", "severity": ...}, ...]
        fragment_type = failure_modes[0].get("mode", "NOMINAL")
    else:
        fragment_type = "NOMINAL"

    # 2. source_type: direct from fragment
    source_type = fragment.source_type

    # 3. severity_bucket: from operational_fingerprint
    fingerprint = fragment.operational_fingerprint or {}
    severity = fingerprint.get("severity", "UNKNOWN")
    severity_bucket = _normalize_severity(severity)

    state_key = f"{fragment_type}:{source_type}:{severity_bucket}"
    return fragment_type, source_type, severity_bucket, state_key


SEVERITY_MAP = {
    "CRITICAL": "CRITICAL",
    "MAJOR": "MAJOR",
    "MINOR": "MINOR",
    "WARNING": "WARNING",
    "CLEAR": "CLEAR",
    "INFO": "INFO",
    "CLEARED": "CLEAR",
    "INDETERMINATE": "UNKNOWN",
}

def _normalize_severity(raw: str) -> str:
    return SEVERITY_MAP.get(raw.upper(), "UNKNOWN") if raw else "UNKNOWN"
```

### 4.3 Recording Logic

```python
async def record_observation(
    session: AsyncSession,
    tenant_id: str,
    fragment: AbeyanceFragmentORM,
    entity_refs: list[FragmentEntityRefORM],
) -> int:
    """
    Append sequence log entries for all entities referenced by this fragment.
    Returns the number of entries appended.
    """
    if fragment.event_timestamp is None:
        # Fragments without event_timestamp cannot be sequenced.
        # Log a warning and skip. Do not infer timestamp from ingestion_timestamp
        # because ingestion order != event order.
        return 0

    fragment_type, source_type, severity_bucket, state_key = derive_state_key(fragment)

    entries = []
    for ref in entity_refs:
        if ref.entity_id is None:
            continue  # Unresolved entity refs cannot be sequenced

        entry = EntitySequenceLogORM(
            tenant_id=tenant_id,
            entity_id=ref.entity_id,
            entity_identifier=ref.entity_identifier,
            entity_domain=ref.entity_domain,
            fragment_id=fragment.id,
            event_timestamp=fragment.event_timestamp,
            state_key=state_key,
            fragment_type=fragment_type,
            source_type=source_type,
            severity_bucket=severity_bucket,
        )
        entries.append(entry)

    if entries:
        session.add_all(entries)

    return len(entries)
```

### 4.4 Backfill Procedure

For existing fragments that predate the temporal sequence infrastructure, a one-time backfill job scans `abeyance_fragment` joined with `fragment_entity_ref`, derives state keys, and inserts sequence log entries in chronological order.

```sql
-- Backfill query (executed in batches of 5000)
INSERT INTO entity_sequence_log
  (tenant_id, entity_id, entity_identifier, entity_domain, fragment_id,
   event_timestamp, state_key, fragment_type, source_type, severity_bucket)
SELECT
  f.tenant_id,
  fer.entity_id,
  fer.entity_identifier,
  fer.entity_domain,
  f.id,
  f.event_timestamp,
  -- state_key computed by application layer, not SQL
  %(state_key)s,
  %(fragment_type)s,
  %(source_type)s,
  %(severity_bucket)s
FROM abeyance_fragment f
JOIN fragment_entity_ref fer ON f.id = fer.fragment_id AND f.tenant_id = fer.tenant_id
WHERE f.event_timestamp IS NOT NULL
  AND fer.entity_id IS NOT NULL
  AND NOT EXISTS (
    SELECT 1 FROM entity_sequence_log esl
    WHERE esl.fragment_id = f.id AND esl.entity_id = fer.entity_id
  )
ORDER BY f.event_timestamp, f.id;
```

The backfill is idempotent (the NOT EXISTS guard prevents duplicates) and can be restarted safely.

---

## 5. Transition Matrix Computation

### 5.1 Counting Method

The transition matrix is computed by scanning entity sequence logs within the observation window and counting consecutive state pairs.

```python
async def compute_transitions(
    session: AsyncSession,
    tenant_id: str,
    entity_domain: str,
    window_start: datetime,
    window_end: datetime,
) -> dict[tuple[str, str], int]:
    """
    Count all (from_state, to_state) transitions within the window
    for the given tenant and entity domain.

    Returns: dict mapping (from_state, to_state) -> count
    """
    # Step 1: Get all entities in this domain with observations in the window
    entity_ids = await _get_active_entities(
        session, tenant_id, entity_domain, window_start, window_end
    )

    transition_counts: dict[tuple[str, str], int] = defaultdict(int)

    # Step 2: For each entity, get ordered sequence and count transitions
    for entity_id in entity_ids:
        sequence = await _get_entity_sequence(
            session, tenant_id, entity_id, window_start, window_end
        )

        # sequence is ordered by (event_timestamp, id)
        for i in range(len(sequence) - 1):
            from_state = sequence[i].state_key
            to_state = sequence[i + 1].state_key
            transition_counts[(from_state, to_state)] += 1

    return transition_counts
```

### 5.2 Entity Batching

To avoid loading entire entity populations into memory, entity processing is batched:

```python
ENTITY_BATCH_SIZE = 500  # Entities processed per DB round-trip

async def _get_entity_sequence(
    session: AsyncSession,
    tenant_id: str,
    entity_id: UUID,
    window_start: datetime,
    window_end: datetime,
) -> list[EntitySequenceLogORM]:
    """Get time-ordered sequence for a single entity within window."""
    result = await session.execute(
        select(EntitySequenceLogORM)
        .where(
            EntitySequenceLogORM.tenant_id == tenant_id,
            EntitySequenceLogORM.entity_id == entity_id,
            EntitySequenceLogORM.event_timestamp >= window_start,
            EntitySequenceLogORM.event_timestamp <= window_end,
        )
        .order_by(
            EntitySequenceLogORM.event_timestamp,
            EntitySequenceLogORM.id,  # Break ties
        )
    )
    return result.scalars().all()
```

### 5.3 Matrix Update Rule

The transition matrix supports two update modes:

#### 5.3.1 Incremental Update (Hot Path)

When a new fragment arrives and `record_observation()` appends entries to the sequence log, the matrix is updated incrementally for each affected entity:

```python
async def incremental_update(
    session: AsyncSession,
    tenant_id: str,
    entity_id: UUID,
    entity_domain: str,
    new_state_key: str,
    new_event_timestamp: datetime,
) -> None:
    """
    Update transition matrix based on a single new observation.
    Finds the previous state for this entity and increments the
    (prev_state -> new_state) transition count.
    """
    # Get the most recent prior observation for this entity
    prev_entry = await session.execute(
        select(EntitySequenceLogORM)
        .where(
            EntitySequenceLogORM.tenant_id == tenant_id,
            EntitySequenceLogORM.entity_id == entity_id,
            EntitySequenceLogORM.event_timestamp < new_event_timestamp,
        )
        .order_by(
            EntitySequenceLogORM.event_timestamp.desc(),
            EntitySequenceLogORM.id.desc(),
        )
        .limit(1)
    )
    prev = prev_entry.scalar_one_or_none()

    if prev is None:
        # First observation for this entity -- no transition to record
        return

    from_state = prev.state_key
    to_state = new_state_key

    # Upsert the transition count
    await _upsert_transition(
        session, tenant_id, entity_domain, from_state, to_state
    )


async def _upsert_transition(
    session: AsyncSession,
    tenant_id: str,
    entity_domain: str,
    from_state: str,
    to_state: str,
) -> None:
    """
    Atomically increment transition count and recompute probability.
    Uses INSERT ... ON CONFLICT ... DO UPDATE (PostgreSQL upsert).
    """
    # Step 1: Upsert the specific transition row
    await session.execute(text("""
        INSERT INTO transition_matrix
            (id, tenant_id, entity_domain, from_state, to_state,
             transition_count, total_from_count, probability,
             first_observed, last_observed, observation_window_start,
             matrix_version, updated_at)
        VALUES
            (gen_random_uuid(), :tenant_id, :entity_domain, :from_state, :to_state,
             1, 1, 1.0,
             now(), now(), :window_start,
             1, now())
        ON CONFLICT (tenant_id, entity_domain, from_state, to_state)
        DO UPDATE SET
            transition_count = transition_matrix.transition_count + 1,
            last_observed = now(),
            updated_at = now()
    """), {
        "tenant_id": tenant_id,
        "entity_domain": entity_domain,
        "from_state": from_state,
        "to_state": to_state,
        "window_start": _get_window_start(entity_domain),
    })

    # Step 2: Recompute total_from_count and probability for all transitions
    # from the same from_state
    await session.execute(text("""
        WITH from_total AS (
            SELECT SUM(transition_count) AS total
            FROM transition_matrix
            WHERE tenant_id = :tenant_id
              AND entity_domain = :entity_domain
              AND from_state = :from_state
        )
        UPDATE transition_matrix
        SET total_from_count = from_total.total,
            probability = transition_count::float / GREATEST(from_total.total, 1),
            matrix_version = matrix_version + 1,
            updated_at = now()
        FROM from_total
        WHERE tenant_id = :tenant_id
          AND entity_domain = :entity_domain
          AND from_state = :from_state
    """), {
        "tenant_id": tenant_id,
        "entity_domain": entity_domain,
        "from_state": from_state,
    })
```

#### 5.3.2 Full Recompute (Cold Path)

Scheduled maintenance job that recomputes the entire matrix from the sequence log within the observation window. This corrects any drift from incremental updates and handles window sliding.

```python
async def full_recompute(
    session: AsyncSession,
    tenant_id: str,
    entity_domain: str,
) -> int:
    """
    Full recompute of transition matrix from sequence log.
    Returns the new matrix version number.
    """
    window_start, window_end = _get_observation_window(entity_domain)

    # Count all transitions
    transition_counts = await compute_transitions(
        session, tenant_id, entity_domain, window_start, window_end
    )

    # Compute from_state totals
    from_totals: dict[str, int] = defaultdict(int)
    for (from_s, to_s), count in transition_counts.items():
        from_totals[from_s] += count

    # Get current max version
    current_version = await _get_current_version(session, tenant_id, entity_domain)
    new_version = current_version + 1

    # Delete existing rows for this partition (atomic within transaction)
    await session.execute(text("""
        DELETE FROM transition_matrix
        WHERE tenant_id = :tenant_id AND entity_domain = :entity_domain
    """), {"tenant_id": tenant_id, "entity_domain": entity_domain})

    # Insert new rows
    for (from_s, to_s), count in transition_counts.items():
        total = from_totals[from_s]
        prob = count / total if total > 0 else 0.0

        await session.execute(text("""
            INSERT INTO transition_matrix
                (id, tenant_id, entity_domain, from_state, to_state,
                 transition_count, total_from_count, probability,
                 first_observed, last_observed, observation_window_start,
                 matrix_version, updated_at)
            VALUES
                (gen_random_uuid(), :tenant_id, :entity_domain, :from_state, :to_state,
                 :count, :total, :prob,
                 now(), now(), :window_start,
                 :version, now())
        """), {
            "tenant_id": tenant_id,
            "entity_domain": entity_domain,
            "from_state": from_s,
            "to_state": to_s,
            "count": count,
            "total": total,
            "prob": prob,
            "window_start": window_start,
            "version": new_version,
        })

    # Record provenance
    total_transitions = sum(transition_counts.values())
    distinct_states = len(set(
        s for pair in transition_counts.keys() for s in pair
    ))

    await _record_version(
        session, tenant_id, entity_domain, new_version,
        window_start, window_end, total_transitions,
        distinct_states, len(transition_counts), "FULL_RECOMPUTE"
    )

    return new_version
```

---

## 6. Sequence Window Configuration

### 6.1 Window Parameters

| Parameter | Default | Per-Domain Override | Rationale |
|---|---|---|---|
| `sequence_window_days` | 180 | RAN: 90, TRANSPORT: 180, IP: 90, CORE: 365, VNF: 180 | How far back the transition matrix looks. RAN entities have fast state cycles (alarms clear in hours); CORE entities have slow cycles (capacity changes over months). |
| `min_observations_stable` | 20 | - | Minimum transitions from a given `from_state` before its outgoing probabilities are considered stable (Section 7). |
| `min_observations_report` | 5 | - | Minimum transitions before a state pair appears in API responses. Below this, the pair is tagged as `LOW_CONFIDENCE`. |
| `max_sequence_retention_days` | 1095 | - | How long sequence log entries are retained (Section 3.1.3). |
| `full_recompute_interval_hours` | 24 | - | How often the full recompute job runs per (tenant, domain). |

### 6.2 Window Sliding

The observation window slides forward as time progresses. On each full recompute:

```
window_end   = now()
window_start = now() - sequence_window_days
```

Transitions that occurred before `window_start` are excluded from the recompute. This means the matrix naturally "forgets" old patterns while incremental updates add new ones.

Between full recomputes, incremental updates add to the matrix but do not remove expired transitions. The full recompute corrects this drift. With a 24-hour recompute interval and a 90-day minimum window, the maximum staleness is ~1.1% (1 day out of 90).

---

## 7. Stability and Confidence

### 7.1 Minimum Observation Threshold

A transition probability `P(to_state | from_state)` is marked as **stable** only when:

```
total_from_count >= min_observations_stable (default: 20)
```

Below this threshold, the probability estimate has high variance and should not be used for expectation violation detection. The T5.2 consumer MUST check the `total_from_count` before using a probability value.

### 7.2 Confidence Categorization

| total_from_count | Category | Consumer Behaviour |
|---|---|---|
| < 5 | `INSUFFICIENT` | Do not use. Not reported in API. |
| 5 -- 19 | `LOW_CONFIDENCE` | Report with warning flag. T5.2 ignores. |
| 20 -- 99 | `STABLE` | Safe for expectation violation detection. |
| >= 100 | `HIGH_CONFIDENCE` | Strong statistical basis. |

### 7.3 Laplace Smoothing

To avoid zero-probability transitions (which would make T5.2's log-probability calculation produce -infinity), the probability computation applies Laplace smoothing with pseudocount alpha = 1:

```
P_smoothed(to_state | from_state) = (transition_count + alpha) / (total_from_count + alpha * V)
```

Where `V` is the number of distinct `to_state` values observed from `from_state` plus 1 (the unseen-state pseudocount).

Smoothing is applied at query time by the consumer, NOT stored in the `probability` column. The stored `probability` is the raw MLE estimate. This preserves the raw counts for auditability while allowing consumers to apply different smoothing strategies.

---

## 8. Consumer Interface

### 8.1 Query: Entity Sequence

```python
async def get_entity_sequence(
    session: AsyncSession,
    tenant_id: str,
    entity_id: UUID,
    limit: int = 100,
    since: Optional[datetime] = None,
) -> list[EntitySequenceLogORM]:
    """
    Get the most recent `limit` sequence entries for an entity,
    optionally filtered to entries after `since`.
    Ordered newest-first for display, oldest-first for transition analysis.
    """
```

### 8.2 Query: Transition Probabilities from State

```python
async def get_transitions_from(
    session: AsyncSession,
    tenant_id: str,
    entity_domain: str,
    from_state: str,
    min_confidence: str = "LOW_CONFIDENCE",
) -> list[TransitionRow]:
    """
    Get all outgoing transitions from a given state, filtered by confidence.
    Returns rows ordered by probability descending.
    Used by T5.2 to answer: "What states are expected to follow from_state?"
    """
```

### 8.3 Query: Expected vs Observed Transition

```python
async def get_transition_probability(
    session: AsyncSession,
    tenant_id: str,
    entity_domain: str,
    from_state: str,
    to_state: str,
) -> Optional[TransitionRow]:
    """
    Get the specific transition probability for a (from, to) pair.
    Returns None if the transition has never been observed.
    Used by T5.2 to answer: "How likely is this specific transition?"
    """
```

### 8.4 Query: Matrix Summary

```python
async def get_matrix_summary(
    session: AsyncSession,
    tenant_id: str,
    entity_domain: str,
) -> MatrixSummary:
    """
    Get the current state of the transition matrix for a domain.
    Returns: version, state vocabulary size, total transitions,
    stable transition count, window boundaries.
    """
```

---

## 9. Telecom Example: eNB State Transitions

### 9.1 Scenario

Tenant `telco2` operates 500 eNodeBs. Each eNB generates alarms, telemetry, and change records. Over 90 days, the temporal sequence infrastructure captures the following for entity `ENB-4412` (entity_domain = `RAN`):

### 9.2 Entity Sequence Log (excerpt)

```
entity_id: ENB-4412 (UUID: a1b2c3...)
tenant_id: telco2

# Time-ordered sequence:
t=00h  NOMINAL:TELEMETRY_EVENT:INFO          (routine KPI report)
t=02h  NOMINAL:TELEMETRY_EVENT:INFO          (routine KPI report)
t=04h  NOMINAL:TELEMETRY_EVENT:INFO          (routine KPI report)
t=06h  DARK_ATTRIBUTE:TELEMETRY_EVENT:WARNING (RSRP degradation detected)
t=07h  DARK_ATTRIBUTE:ALARM:MINOR            (threshold crossing alarm)
t=08h  DARK_NODE:ALARM:MAJOR                 (cell unavailable)
t=10h  NOMINAL:ALARM:CLEAR                   (alarm cleared)
t=12h  NOMINAL:TELEMETRY_EVENT:INFO          (KPIs recovered)
...
```

### 9.3 Transition Matrix (RAN domain, telco2)

After 90 days of observing 500 eNBs, the matrix for `(telco2, RAN)` contains:

| from_state | to_state | count | total_from | probability | confidence |
|---|---|---|---|---|---|
| NOMINAL:TELEMETRY_EVENT:INFO | NOMINAL:TELEMETRY_EVENT:INFO | 45,230 | 47,100 | 0.960 | HIGH_CONFIDENCE |
| NOMINAL:TELEMETRY_EVENT:INFO | DARK_ATTRIBUTE:TELEMETRY_EVENT:WARNING | 1,120 | 47,100 | 0.024 | HIGH_CONFIDENCE |
| NOMINAL:TELEMETRY_EVENT:INFO | DARK_NODE:ALARM:MAJOR | 47 | 47,100 | 0.001 | HIGH_CONFIDENCE |
| DARK_ATTRIBUTE:TELEMETRY_EVENT:WARNING | DARK_ATTRIBUTE:ALARM:MINOR | 890 | 1,150 | 0.774 | HIGH_CONFIDENCE |
| DARK_ATTRIBUTE:TELEMETRY_EVENT:WARNING | NOMINAL:TELEMETRY_EVENT:INFO | 180 | 1,150 | 0.157 | HIGH_CONFIDENCE |
| DARK_ATTRIBUTE:TELEMETRY_EVENT:WARNING | DARK_NODE:ALARM:MAJOR | 80 | 1,150 | 0.070 | STABLE |
| DARK_ATTRIBUTE:ALARM:MINOR | DARK_NODE:ALARM:MAJOR | 620 | 910 | 0.681 | HIGH_CONFIDENCE |
| DARK_ATTRIBUTE:ALARM:MINOR | NOMINAL:ALARM:CLEAR | 210 | 910 | 0.231 | HIGH_CONFIDENCE |
| DARK_NODE:ALARM:MAJOR | NOMINAL:ALARM:CLEAR | 710 | 750 | 0.947 | HIGH_CONFIDENCE |
| DARK_NODE:ALARM:MAJOR | DARK_NODE:ALARM:CRITICAL | 40 | 750 | 0.053 | STABLE |
| NOMINAL:ALARM:CLEAR | NOMINAL:TELEMETRY_EVENT:INFO | 880 | 920 | 0.957 | HIGH_CONFIDENCE |

### 9.4 What This Enables for Tier 3

**Expectation Violation Detection (T5.2)** can now answer:
- "ENB-4412 just transitioned from NOMINAL directly to DARK_NODE:ALARM:MAJOR. P(DARK_NODE:ALARM:MAJOR | NOMINAL:TELEMETRY_EVENT:INFO) = 0.001. This skipped the usual degradation phase (0.960 probability of staying nominal, 0.024 probability of going to warning first). Flag as expectation violation."

**Causal Direction Testing** can now answer:
- "Does DARK_ATTRIBUTE:TELEMETRY_EVENT:WARNING precede DARK_NODE:ALARM:MAJOR? P(MAJOR | WARNING) = 0.070, but does WARNING consistently appear before MAJOR for the same entity? Check if the temporal ordering is consistent across entities."

### 9.5 The Normal Lifecycle Pattern

The matrix reveals the standard eNB failure lifecycle:

```
NOMINAL -> WARNING -> MINOR_ALARM -> MAJOR_ALARM -> CLEAR -> NOMINAL
  (0.024)   (0.774)    (0.681)        (0.947)       (0.957)
```

With high-probability self-transitions at NOMINAL (0.960) representing the steady state. Any deviation from this pattern (e.g., NOMINAL jumping directly to MAJOR at 0.001 probability) is the signal T5.2 uses to fire expectation violations.

---

## 10. Maintenance Operations

### 10.1 Full Recompute Schedule

The full recompute runs as a periodic task (default: every 24 hours per tenant per domain). It is scheduled by the existing maintenance sweep infrastructure.

```python
async def maintenance_recompute_all(session: AsyncSession, tenant_id: str) -> None:
    """Recompute transition matrices for all entity domains in a tenant."""
    domains = await _get_active_domains(session, tenant_id)
    for domain in domains:
        await full_recompute(session, tenant_id, domain)
```

### 10.2 Sequence Log Pruning

Entries older than `max_sequence_retention_days` are deleted in batches:

```sql
DELETE FROM entity_sequence_log
WHERE tenant_id = :tenant_id
  AND event_timestamp < now() - interval ':retention_days days'
LIMIT 10000;
-- Repeat until 0 rows affected
```

### 10.3 Matrix Cleanup

Transition rows with `transition_count = 0` after a full recompute (transitions that fell outside the window) are deleted by the recompute job itself (the DELETE + re-INSERT pattern in Section 5.3.2 handles this implicitly).

Version history entries in `transition_matrix_version` older than 90 days are pruned to keep provenance manageable.

---

## 11. Invariants

| Invariant | Description |
|---|---|
| INV-7 | `tenant_id` present and indexed on all three tables. All queries scoped by tenant. |
| INV-15 | Sequence log is append-only during normal operation. Entries are only removed by retention pruning, never by fragment state changes. |
| INV-16 | Transition matrix probabilities sum to 1.0 (within floating-point tolerance) for each `from_state` within a `(tenant_id, entity_domain)` partition after a full recompute. Incremental updates may cause transient drift of up to 1.1%. |
| INV-17 | `transition_count <= total_from_count` enforced by CHECK constraint. |
| INV-18 | Every sequence log entry traces back to exactly one fragment via `fragment_id`. |
| INV-19 | Matrix version monotonically increases per `(tenant_id, entity_domain)`. |

---

## 12. Storage Estimates

### 12.1 Sequence Log

Per sequence log entry: ~200 bytes (strings + UUID + timestamps).

For a tenant with 10,000 entities averaging 10 observations/day over 180 days:
- Entries: 10,000 * 10 * 180 = 18,000,000
- Storage: 18M * 200 bytes = ~3.6 GB
- With BTREE indexes: ~5 GB total

### 12.2 Transition Matrix

Per matrix row: ~300 bytes.

For a tenant with 5 entity domains averaging 50 distinct states per domain:
- Max rows per domain: 50 * 50 = 2,500 (dense; actual is sparse, typically 10-20% fill)
- Typical rows per domain: ~300
- Total rows: 5 * 300 = 1,500
- Storage: 1,500 * 300 bytes = ~450 KB (negligible)

### 12.3 Version History

Per version record: ~200 bytes.
At 1 recompute/day * 5 domains * 90-day retention: 450 records = ~90 KB (negligible)

---

## 13. Migration

### 13.1 Alembic Steps

```
1. CREATE TABLE entity_sequence_log (Section 3.1)
2. CREATE TABLE transition_matrix (Section 3.2)
3. CREATE TABLE transition_matrix_version (Section 3.3)
4. CREATE INDEXES (Sections 3.1.1, 3.2.1, 3.3.1)
5. ADD CHECK CONSTRAINTS (Section 3.2.2)
6. RUN backfill job (Section 4.4) — populates sequence log from existing fragments
7. RUN initial full_recompute for all tenants — populates transition matrices
```

Steps 6-7 are data migrations run after schema migration, not within the Alembic revision itself.

### 13.2 Rollback

All three tables are new. Rollback is DROP TABLE in reverse order (version history, matrix, sequence log). No existing tables are modified.

---

Generated: 2026-03-16 | Task D2.1 | Abeyance Memory v3.0 | Discovery Mechanism #7 | Tier 2
