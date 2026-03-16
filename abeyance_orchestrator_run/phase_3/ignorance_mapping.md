# Abeyance Memory v3.0 — Ignorance Mapping Specification

**Task:** T3.1 — Discovery Mechanism #2: Ignorance Mapping
**Discovery Tier:** TIER 1 — Foundation (no LLM dependency, operates on existing data only)
**Generated:** 2026-03-16
**Addresses Findings:** F-4.2 (entity extraction single point of failure; silent decay to zero)
**Depends On:** T1.2 (ORM Schema), T2.6 (Observability Metrics)

---

## 1. Purpose and Motivation

Ignorance Mapping is a passive, continuous measurement layer. It does not enrich fragments or
trigger snap evaluation. Its sole function is to answer the question:

> "Where in the fragment corpus does the system lack the information needed to make reliable
> correlation decisions — and what caused that lack?"

Without this layer, the system silently discards correlated evidence. Finding F-4.2 documents the
most severe instance: entity extraction failure causes fragments to never reach snap evaluation and
decay to zero with no operator-visible record of what was lost or why. Ignorance Mapping makes
this failure mode observable, persistent, and actionable.

The output of ignorance mapping — the ignorance map — is not a display artifact. It is a
structured data product consumed by Discovery Mechanism #3 (Enrichment Priority Routing) to
direct future enrichment effort toward the regions of highest information deficit.

---

## 2. Scope Boundaries

| In scope | Out of scope |
|---|---|
| Measuring entity extraction success rates per entity type, source type, and time window | Modifying the enrichment chain |
| Measuring mask distribution across the active and cold fragment populations | Designing or modifying snap scoring |
| Detecting fragments that reach EXPIRED/COLD with all masks FALSE and zero evaluations | Designing Discovery Mechanism #1 or #3 |
| Defining "high ignorance" regions quantitatively | Triggering re-enrichment directly |
| Generating exploration directives for downstream routing | Any LLM inference |
| Tenant-isolated storage and provenance logging | Real-time alerting (handled by T2.6) |

---

## 3. Conceptual Model

### 3.1 What is Ignorance?

A fragment carries ignorance on a given embedding dimension if the corresponding mask is FALSE.
The fragment exists in the system but contributes zero usable signal on that dimension. When all
three T-VEC masks are FALSE, the fragment contributes only its temporal embedding
(`emb_temporal`, which is always valid) to any snap evaluation — meaning it carries less than
17% of the nominal signal weight in the default profile.

Three distinct causes of ignorance are tracked:

| Cause | Code | Description |
|---|---|---|
| `EXTRACTION_FAILURE` | EF | Entity extraction produced an empty result; topological and downstream operational embeddings cannot be generated. Directly corresponds to F-4.2. |
| `MODEL_FAILURE` | MF | T-VEC inference failed on one or more dimensions; mask set FALSE per schema rules (INV-12). |
| `UNENRICHED` | UE | Fragment is newly ingested and enrichment has not yet run. Transient; resolves within enrichment latency SLO. |

A fourth implicit cause exists for cold fragments:

| Cause | Code | Description |
|---|---|---|
| `ARCHIVED_INVALID` | AI | Fragment was archived to cold storage with one or more masks FALSE and was never re-enriched during its active lifetime. This is the permanent record of ignorance that was never resolved. |

### 3.2 Ignorance Score

The ignorance score `I(f)` for a fragment `f` is defined as the fraction of T-VEC embedding
dimensions that are invalid:

```
I(f) = (1 - mask_semantic) + (1 - mask_topological) + (1 - mask_operational)
       -----------------------------------------------------------------------
                                      3
```

`I(f)` is in [0.0, 1.0]. `emb_temporal` is excluded because it has no mask and is always valid.
A fragment with all three T-VEC masks TRUE has `I(f) = 0.0` (fully informed). A fragment with
all three FALSE has `I(f) = 1.0` (maximally ignorant on T-VEC dimensions).

### 3.3 High-Ignorance Region

A region of the fragment corpus is "high-ignorance" if the mean ignorance score across the
fragments in that region exceeds a defined threshold. Regions are defined by the cross-product
of `(source_type, entity_type, time_window)`.

Quantitative definition:

```
HIGH_IGNORANCE_THRESHOLD = 0.40

A region R is high-ignorance if:
    mean(I(f) for f in R) >= HIGH_IGNORANCE_THRESHOLD

AND at least one of the following conditions holds:
    (a) The region contains >= MIN_POPULATION_FOR_HIGH_IGNORANCE fragments, OR
    (b) The region's extraction success rate is < 0.60 for a named entity type

MIN_POPULATION_FOR_HIGH_IGNORANCE = 10
```

Rationale for 0.40: this corresponds to having at least two of the three T-VEC dimensions
invalid on average. At this level, snap scoring in the default profile falls below 50% of its
nominal weight budget on T-VEC dimensions, making correlation decisions unreliable.

A region with fewer than `MIN_POPULATION_FOR_HIGH_IGNORANCE` fragments is classified as
`SPARSE` rather than `HIGH_IGNORANCE`, even if individual fragment ignorance is high. Sparse
regions are noted but do not generate exploration directives.

---

## 4. Algorithm

The ignorance mapping algorithm runs as a periodic background job: `IgnoranceMappingJob`. It
does not run inline with enrichment or snap evaluation. It reads from `abeyance_fragment`,
`cold_fragment`, and `fragment_entity_ref`. It writes to the tables defined in Section 6.

### 4.1 Entity Extraction Success Rate Computation

**Inputs:**
- `abeyance_fragment` rows in ACTIVE, NEAR_MISS, STALE, EXPIRED states (not INGESTED, which
  is pre-enrichment, and not SNAPPED/COLD, which are handled separately)
- Time window: configurable, default `[now - 24h, now]`
- Grouping: `(source_type, entity_type, time_bucket)`

**Algorithm:**

```
For each time_bucket T in the configured window:
    For each source_type S:
        Let F = fragments with source_type = S, created_at in T, snap_status != INGESTED

        total_fragments = |F|
        if total_fragments == 0: skip

        # Entity extraction success: fragment has at least one extracted entity
        # of any type. "Extraction failure" = extracted_entities JSONB array is empty.
        extraction_success = COUNT(f in F where jsonb_array_length(f.extracted_entities) > 0)
        extraction_rate(S, T) = extraction_success / total_fragments

        # Per entity type: count fragments that have at least one entity of that type
        For each entity_type E in known_entity_types:
            type_success = COUNT(f in F where f.extracted_entities @> '[{"type": E}]')
            type_extraction_rate(S, E, T) = type_success / total_fragments

        Write IgnoranceExtractionStat record (Section 6.1)
```

**Known entity types for telecom domain:**

```
NETWORK_ELEMENT   -- routers, switches, base stations, RAN nodes
INTERFACE         -- port identifiers, interface names (e.g., GigE0/0/1)
ALARM_CODE        -- vendor alarm codes (e.g., RTRV-ALM-EQPT, OLT-LOS)
IP_ADDRESS        -- IPv4/IPv6 addresses
CIRCUIT_ID        -- circuit or tunnel identifiers
CUSTOMER_ID       -- customer or service identifiers
VENDOR_TAG        -- vendor-specific equipment identifiers
FAILURE_MODE      -- standardized failure classification tags
```

Entity types are extensible via configuration. New types added to the configuration are
automatically included in the next job run without schema changes.

**Complexity:** O(F) per time bucket per source type, where F is the fragment count in that
bucket. The `extracted_entities` GIN index (`ix_abeyance_fragment_entities`) on
`abeyance_fragment` makes the per-entity-type containment queries O(F/k) where k is the
average number of distinct entity types per fragment. Total job complexity per run:
O(F_active * E * W) where F_active is the active fragment population, E is the number of known
entity types (bounded at 32 by configuration), and W is the number of time buckets
(bounded at 48 for 24h window with 30-minute buckets). This is O(F_active) with bounded
constants.

### 4.2 Mask Distribution Computation

**Inputs:**
- `abeyance_fragment` rows in ACTIVE, NEAR_MISS states (the live searchable population)
- Grouping: `(source_type, time_bucket)`

**Algorithm:**

```
For each time_bucket T:
    For each source_type S:
        Let F = active/near_miss fragments with source_type = S, created_at in T

        total = |F|
        if total == 0: skip

        # Per-dimension valid fraction
        semantic_valid = COUNT(f in F where f.mask_semantic = TRUE) / total
        topological_valid = COUNT(f in F where f.mask_topological = TRUE) / total
        operational_valid = COUNT(f in F where f.mask_operational = TRUE) / total
        # emb_temporal: always valid, fraction = 1.0 by definition (not tracked separately)

        # Joint mask patterns (all 8 combinations of 3 boolean masks)
        For each mask_pattern P in {(T,T,T), (T,T,F), (T,F,T), ..., (F,F,F)}:
            pattern_count(P) = COUNT(f in F where masks match P) / total

        # Ignorance score distribution
        mean_ignorance = mean(I(f) for f in F)
        p50_ignorance = median(I(f) for f in F)
        p95_ignorance = 95th_percentile(I(f) for f in F)

        is_high_ignorance = (mean_ignorance >= HIGH_IGNORANCE_THRESHOLD AND total >= MIN_POPULATION)

        Write IgnoranceMaskDistribution record (Section 6.2)
```

**Complexity:** O(F_active) per run. The mask columns are NOT NULL with fast boolean evaluation.
No subquery joins required. A single sequential scan over the relevant fragment population
computes all statistics. For large populations (>100K), this scan runs against the
`ix_abeyance_fragment_tenant_status` index to limit to ACTIVE/NEAR_MISS rows, then evaluates
mask columns in a single pass.

**SQL implementation pattern (one query per tenant):**

```sql
SELECT
    source_type,
    date_trunc('30 minutes', created_at) AS time_bucket,
    COUNT(*)                                                           AS total,
    COUNT(*) FILTER (WHERE mask_semantic    = TRUE) * 1.0 / COUNT(*) AS semantic_valid_fraction,
    COUNT(*) FILTER (WHERE mask_topological = TRUE) * 1.0 / COUNT(*) AS topological_valid_fraction,
    COUNT(*) FILTER (WHERE mask_operational = TRUE) * 1.0 / COUNT(*) AS operational_valid_fraction,
    AVG(
        (CASE WHEN mask_semantic    THEN 0 ELSE 1 END +
         CASE WHEN mask_topological THEN 0 ELSE 1 END +
         CASE WHEN mask_operational THEN 0 ELSE 1 END)::float / 3.0
    )                                                                  AS mean_ignorance_score,
    PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY
        (CASE WHEN mask_semantic    THEN 0 ELSE 1 END +
         CASE WHEN mask_topological THEN 0 ELSE 1 END +
         CASE WHEN mask_operational THEN 0 ELSE 1 END)::float / 3.0
    )                                                                  AS p50_ignorance_score,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY
        (CASE WHEN mask_semantic    THEN 0 ELSE 1 END +
         CASE WHEN mask_topological THEN 0 ELSE 1 END +
         CASE WHEN mask_operational THEN 0 ELSE 1 END)::float / 3.0
    )                                                                  AS p95_ignorance_score
FROM abeyance_fragment
WHERE
    tenant_id = :tenant_id
    AND snap_status IN ('ACTIVE', 'NEAR_MISS')
    AND created_at >= :window_start
GROUP BY source_type, date_trunc('30 minutes', created_at)
ORDER BY time_bucket;
```

### 4.3 Silent Decay Detection (F-4.2 Specific)

This is the most critical component. Finding F-4.2 states: fragments without extracted entities
never reach snap evaluation and decay to zero silently. The silent decay detector identifies
these fragments and creates a permanent record before they transition to COLD.

**Definition — Silent Decay:** A fragment that satisfies all of the following:
1. `snap_status` IN ('EXPIRED', 'COLD')
2. `jsonb_array_length(extracted_entities) = 0` (no entities were ever extracted)
3. No row exists in `snap_decision_record` with `new_fragment_id = fragment.id` OR
   `candidate_fragment_id = fragment.id` (was never evaluated as either side of a snap pair)
4. `current_decay_score < SILENT_DECAY_THRESHOLD` at time of expiry

```
SILENT_DECAY_THRESHOLD = 0.05
```

A fragment decayed below 5% of its initial relevance without ever being compared against another
fragment is classified as silently decayed. The threshold of 0.05 corresponds to approximately
4.3 half-lives of decay, which at the default decay rate of 0.1/day represents ~30 days of
complete neglect.

**Algorithm:**

```
Run once per maintenance cycle, after DecayEngine.run_decay_pass() completes.

Step 1 — Identify candidates:
    Let C = fragments where:
        snap_status IN ('EXPIRED', 'COLD')
        AND created_at >= job_last_run_at  # only process new expirations
        AND jsonb_array_length(extracted_entities) = 0

Step 2 — Confirm no snap evaluation occurred:
    For each fragment f in C:
        evaluated = EXISTS(
            SELECT 1 FROM snap_decision_record
            WHERE (new_fragment_id = f.id OR candidate_fragment_id = f.id)
              AND tenant_id = f.tenant_id
        )
        if NOT evaluated AND f.current_decay_score < SILENT_DECAY_THRESHOLD:
            classify f as SILENTLY_DECAYED

Step 3 — Classify root cause:
    For each silently-decayed fragment f:
        # Determine which extraction path was attempted
        if f.source_type = 'MANUAL':
            cause = 'EXTRACTION_FAILURE' (manual fragments always have entities explicitly set)
        else:
            # Check if any model error was logged against this fragment
            # by querying provenance log (Section 7)
            cause = lookup_extraction_cause(f.id)
            # Returns: EXTRACTION_FAILURE (regex also failed), MODEL_FAILURE (TSLAM down),
            # or UNENRICHED (enrichment never ran — indicates pipeline gap, not model failure)

Step 4 — Write record:
    Write SilentDecayRecord (Section 6.3) for each classified fragment.

Step 5 — Aggregate statistics:
    Write or update IgnoranceSilentDecayStat (Section 6.4) grouping by
    (source_type, cause, time_bucket).
```

**Complexity:** Step 1 is O(expired_this_cycle) using the `ix_abeyance_fragment_tenant_status`
index filtered to EXPIRED/COLD. Step 2 is O(|C|) with one indexed lookup per fragment against
`ix_sdr_new_frag`. Total: O(expired_this_cycle) per run, which is bounded by the decay pass
batch size.

**Note on Step 2 join:** For large expired populations, Step 2 can be rewritten as a single
anti-join:

```sql
SELECT f.id, f.source_type, f.current_decay_score, f.created_at
FROM abeyance_fragment f
WHERE f.tenant_id     = :tenant_id
  AND f.snap_status   IN ('EXPIRED', 'COLD')
  AND f.created_at    >= :last_run_at
  AND jsonb_array_length(f.extracted_entities) = 0
  AND f.current_decay_score < :silent_decay_threshold
  AND NOT EXISTS (
      SELECT 1 FROM snap_decision_record sdr
      WHERE sdr.tenant_id = f.tenant_id
        AND (sdr.new_fragment_id = f.id OR sdr.candidate_fragment_id = f.id)
  );
```

The `NOT EXISTS` subquery uses `ix_sdr_new_frag` for the `new_fragment_id` lookup. The
`candidate_fragment_id` path requires a separate index (see Section 6.5).

### 4.4 Ignorance Map Aggregation

After Sections 4.1–4.3 complete for a given run, the job aggregates results into a per-tenant
ignorance map: a ranked list of regions with their ignorance scores and recommended priorities.

**Algorithm:**

```
For each (source_type S, entity_type E, time_bucket T) region R:
    extraction_rate = from IgnoranceExtractionStat
    mask_dist = from IgnoranceMaskDistribution (for matching S, T)
    silent_decay_count = from IgnoranceSilentDecayStat (for matching S, T)

    region_ignorance_score = weighted_combination(
        w1 * (1 - extraction_rate(S, E, T)),   # w1 = 0.50
        w2 * mask_dist.mean_ignorance_score,    # w2 = 0.35
        w3 * min(1.0, silent_decay_count / 10)  # w3 = 0.15, capped at 10 events
    )
    # region_ignorance_score is in [0.0, 1.0]

    is_high_ignorance = (
        region_ignorance_score >= HIGH_IGNORANCE_THRESHOLD
        AND region_fragment_count >= MIN_POPULATION_FOR_HIGH_IGNORANCE
    )

    classification = 'HIGH_IGNORANCE' if is_high_ignorance
                   else 'SPARSE' if region_fragment_count < MIN_POPULATION_FOR_HIGH_IGNORANCE
                   else 'NOMINAL'

    Write IgnoranceMapEntry record (Section 6.5)

Sort all IgnoranceMapEntry records for this tenant by region_ignorance_score DESC.
Assign priority_rank = row_number() to each HIGH_IGNORANCE region.
```

**Weights rationale:**
- Extraction rate carries 50% of the weight because entity extraction failure (F-4.2) is the
  most common and most damaging cause of ignorance. Without entities, topological embedding
  and neighbourhood lookup both fail.
- Mask distribution carries 35% because it reflects the combined effect of all model failures
  (not just entity extraction) on the actual embedding population.
- Silent decay count carries 15% because it measures the historical consequence — evidence that
  was permanently lost — rather than the current state, which is already captured by extraction
  rate and mask distribution.

These weights are stored in configuration (see Section 8.2) and are not hard-coded.

---

## 5. Exploration Directives

An exploration directive is a structured record produced by the ignorance mapper that tells
Discovery Mechanism #3 (Enrichment Priority Routing) which regions need enrichment attention
and what kind.

### 5.1 Directive Structure

```
ExplorationDirective:
    directive_id:        UUID (generated at creation)
    tenant_id:           VARCHAR(100)
    region_key:          VARCHAR(500) — "{source_type}::{entity_type}::{time_bucket_iso}"
    created_at:          TIMESTAMP WITH TIME ZONE
    ignorance_score:     FLOAT [0.0, 1.0]
    priority_rank:       INTEGER (1 = highest priority)
    recommended_action:  ENUM (see below)
    target_entity_types: TEXT[] — entity types most deficient in this region
    supporting_evidence: JSONB — counts and rates that justify the directive
    consumed_by:         VARCHAR(100) — NULL until a downstream mechanism reads it
    consumed_at:         TIMESTAMP WITH TIME ZONE — NULL until consumed
    expires_at:          TIMESTAMP WITH TIME ZONE — directives older than 48h are stale
```

### 5.2 Recommended Actions

| Action | Trigger condition | Meaning for downstream routing |
|---|---|---|
| `RETRY_ENTITY_EXTRACTION` | extraction_rate(S, E, T) < 0.60 AND source_type is not MANUAL | Re-run TSLAM entity extraction on fragments in this region that have empty extracted_entities |
| `RETRY_TSLAM_EMBEDDING` | mask_topological_valid_fraction < 0.70 AND extraction_rate >= 0.60 | Entities exist but topology embedding failed; re-run T-VEC on topological text |
| `RETRY_TVEC_FULL` | All three mask valid fractions < 0.50 | Full T-VEC re-enrichment needed; likely model outage recovery window |
| `REVIEW_REGEX_COVERAGE` | extraction_rate < 0.60 AND abeyance_model_fallback_total shows regex is active | Regex patterns have insufficient coverage for this source_type; operator action needed |
| `INVESTIGATE_SOURCE` | source_type = MANUAL AND extraction_rate < 0.60 | Manual fragments lacking entities; likely operator data quality issue, not model failure |

### 5.3 How Directives Direct Enrichment Priority

The priority rank assigned to each HIGH_IGNORANCE region corresponds directly to the order in
which Discovery Mechanism #3 should schedule re-enrichment attempts. The mechanism reads
directives in ascending `priority_rank` order and submits fragments matching the region key to
the appropriate enrichment step, subject to the back-pressure constraints defined in the
ingestion queue (HIGH_WATER_MARK, CRITICAL_WATER_MARK from T2.6).

Directives do not modify existing fragments directly. They are advisory. Discovery Mechanism #3
decides whether and when to act based on current queue depth and system health.

Directives expire after 48 hours. If the underlying ignorance has not been addressed within
48 hours, the next ignorance mapping job run regenerates new directives reflecting the current
state.

---

## 6. Storage Schema

All tables are tenant-isolated: `tenant_id` is on every table and every index. Row-level
security or application-layer filtering enforces isolation — consistent with INV-7.

### 6.1 Table: `ignorance_extraction_stat`

Stores per-(source_type, entity_type, time_bucket) entity extraction success rates.

```sql
CREATE TABLE ignorance_extraction_stat (
    id                   UUID        NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    tenant_id            VARCHAR(100) NOT NULL,
    computed_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
    job_run_id           UUID        NOT NULL,  -- FK to ignorance_job_run.id
    time_bucket_start    TIMESTAMPTZ  NOT NULL,
    time_bucket_end      TIMESTAMPTZ  NOT NULL,
    source_type          VARCHAR(50)  NOT NULL,
    entity_type          VARCHAR(100) NOT NULL,  -- 'ALL' for aggregate across all types
    total_fragments      INTEGER      NOT NULL CHECK (total_fragments >= 0),
    success_count        INTEGER      NOT NULL CHECK (success_count >= 0),
    extraction_rate      FLOAT        NOT NULL CHECK (extraction_rate >= 0.0 AND extraction_rate <= 1.0),
    CONSTRAINT chk_success_lte_total CHECK (success_count <= total_fragments)
);

CREATE INDEX ix_ign_extr_stat_tenant_bucket
    ON ignorance_extraction_stat (tenant_id, time_bucket_start, source_type);

CREATE INDEX ix_ign_extr_stat_tenant_job
    ON ignorance_extraction_stat (tenant_id, job_run_id);

CREATE INDEX ix_ign_extr_stat_low_rate
    ON ignorance_extraction_stat (tenant_id, extraction_rate)
    WHERE extraction_rate < 0.60;  -- partial index for high-ignorance queries
```

### 6.2 Table: `ignorance_mask_distribution`

Stores per-(source_type, time_bucket) mask statistics for the active fragment population.

```sql
CREATE TABLE ignorance_mask_distribution (
    id                       UUID        NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    tenant_id                VARCHAR(100) NOT NULL,
    computed_at              TIMESTAMPTZ  NOT NULL DEFAULT now(),
    job_run_id               UUID        NOT NULL,
    time_bucket_start        TIMESTAMPTZ  NOT NULL,
    time_bucket_end          TIMESTAMPTZ  NOT NULL,
    source_type              VARCHAR(50)  NOT NULL,
    total_fragments          INTEGER      NOT NULL CHECK (total_fragments >= 0),
    semantic_valid_fraction  FLOAT        NOT NULL CHECK (semantic_valid_fraction  BETWEEN 0.0 AND 1.0),
    topological_valid_fraction FLOAT      NOT NULL CHECK (topological_valid_fraction BETWEEN 0.0 AND 1.0),
    operational_valid_fraction FLOAT      NOT NULL CHECK (operational_valid_fraction BETWEEN 0.0 AND 1.0),
    -- Joint mask pattern distribution (8 possible patterns)
    pattern_ttt_fraction     FLOAT        NOT NULL,  -- all three TRUE
    pattern_ttf_fraction     FLOAT        NOT NULL,  -- sem=T, topo=T, op=F
    pattern_tft_fraction     FLOAT        NOT NULL,
    pattern_ftt_fraction     FLOAT        NOT NULL,
    pattern_tff_fraction     FLOAT        NOT NULL,
    pattern_ftf_fraction     FLOAT        NOT NULL,
    pattern_fft_fraction     FLOAT        NOT NULL,
    pattern_fff_fraction     FLOAT        NOT NULL,  -- all three FALSE (maximally ignorant)
    -- Ignorance score statistics
    mean_ignorance_score     FLOAT        NOT NULL CHECK (mean_ignorance_score BETWEEN 0.0 AND 1.0),
    p50_ignorance_score      FLOAT        NOT NULL CHECK (p50_ignorance_score  BETWEEN 0.0 AND 1.0),
    p95_ignorance_score      FLOAT        NOT NULL CHECK (p95_ignorance_score  BETWEEN 0.0 AND 1.0),
    is_high_ignorance        BOOLEAN      NOT NULL DEFAULT FALSE,
    CONSTRAINT chk_pattern_fractions_sum CHECK (
        ABS((pattern_ttt_fraction + pattern_ttf_fraction + pattern_tft_fraction +
             pattern_ftt_fraction + pattern_tff_fraction + pattern_ftf_fraction +
             pattern_fft_fraction + pattern_fff_fraction) - 1.0) < 0.001
    )
);

CREATE INDEX ix_ign_mask_dist_tenant_bucket
    ON ignorance_mask_distribution (tenant_id, time_bucket_start, source_type);

CREATE INDEX ix_ign_mask_dist_high_ignorance
    ON ignorance_mask_distribution (tenant_id)
    WHERE is_high_ignorance = TRUE;
```

### 6.3 Table: `ignorance_silent_decay_record`

Individual record for each fragment that decayed silently (F-4.2 tracking).

```sql
CREATE TABLE ignorance_silent_decay_record (
    id                  UUID        NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    tenant_id           VARCHAR(100) NOT NULL,
    fragment_id         UUID        NOT NULL,  -- references abeyance_fragment.id (may be COLD)
    detected_at         TIMESTAMPTZ  NOT NULL DEFAULT now(),
    job_run_id          UUID        NOT NULL,
    source_type         VARCHAR(50)  NOT NULL,
    snap_status_at_detection VARCHAR(20) NOT NULL,  -- EXPIRED or COLD
    decay_score_at_detection FLOAT   NOT NULL,
    ingestion_timestamp TIMESTAMPTZ  NOT NULL,  -- copied from fragment
    event_timestamp     TIMESTAMPTZ,            -- copied from fragment (may be NULL)
    days_in_system      FLOAT        NOT NULL,  -- computed: (detected_at - ingestion_timestamp)
    extraction_cause    VARCHAR(30)  NOT NULL,  -- EXTRACTION_FAILURE, MODEL_FAILURE, UNENRICHED
    -- Mask state at detection (copied from fragment)
    mask_semantic_at_detection    BOOLEAN NOT NULL,
    mask_topological_at_detection BOOLEAN NOT NULL,
    mask_operational_at_detection BOOLEAN NOT NULL,
    CONSTRAINT chk_extraction_cause CHECK (
        extraction_cause IN ('EXTRACTION_FAILURE', 'MODEL_FAILURE', 'UNENRICHED', 'UNKNOWN')
    )
);

CREATE INDEX ix_ign_silent_decay_tenant_time
    ON ignorance_silent_decay_record (tenant_id, detected_at);

CREATE INDEX ix_ign_silent_decay_fragment
    ON ignorance_silent_decay_record (tenant_id, fragment_id);

CREATE INDEX ix_ign_silent_decay_cause
    ON ignorance_silent_decay_record (tenant_id, extraction_cause, source_type);

-- Prevent double-recording the same fragment
CREATE UNIQUE INDEX uq_ign_silent_decay_fragment
    ON ignorance_silent_decay_record (tenant_id, fragment_id);
```

### 6.4 Table: `ignorance_silent_decay_stat`

Aggregated silent decay counts per (source_type, cause, time_bucket). Written after Section 4.3.

```sql
CREATE TABLE ignorance_silent_decay_stat (
    id                   UUID        NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    tenant_id            VARCHAR(100) NOT NULL,
    computed_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
    job_run_id           UUID        NOT NULL,
    time_bucket_start    TIMESTAMPTZ  NOT NULL,
    time_bucket_end      TIMESTAMPTZ  NOT NULL,
    source_type          VARCHAR(50)  NOT NULL,
    extraction_cause     VARCHAR(30)  NOT NULL,
    silent_decay_count   INTEGER      NOT NULL CHECK (silent_decay_count >= 0),
    mean_days_in_system  FLOAT        NOT NULL CHECK (mean_days_in_system >= 0.0),
    max_days_in_system   FLOAT        NOT NULL CHECK (max_days_in_system >= 0.0)
);

CREATE INDEX ix_ign_sd_stat_tenant_bucket
    ON ignorance_silent_decay_stat (tenant_id, time_bucket_start, source_type);
```

### 6.5 Table: `ignorance_map_entry`

The aggregated map: one row per (source_type, entity_type, time_bucket) region per job run.

```sql
CREATE TABLE ignorance_map_entry (
    id                     UUID        NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    tenant_id              VARCHAR(100) NOT NULL,
    job_run_id             UUID        NOT NULL,
    computed_at            TIMESTAMPTZ  NOT NULL DEFAULT now(),
    time_bucket_start      TIMESTAMPTZ  NOT NULL,
    time_bucket_end        TIMESTAMPTZ  NOT NULL,
    source_type            VARCHAR(50)  NOT NULL,
    entity_type            VARCHAR(100) NOT NULL,
    region_fragment_count  INTEGER      NOT NULL CHECK (region_fragment_count >= 0),
    region_ignorance_score FLOAT        NOT NULL CHECK (region_ignorance_score BETWEEN 0.0 AND 1.0),
    classification         VARCHAR(20)  NOT NULL,  -- HIGH_IGNORANCE, NOMINAL, SPARSE
    priority_rank          INTEGER,                -- NULL if not HIGH_IGNORANCE
    recommended_action     VARCHAR(50)  NOT NULL,
    target_entity_types    TEXT[]       NOT NULL DEFAULT '{}',
    supporting_evidence    JSONB        NOT NULL DEFAULT '{}',
    -- Component scores (for auditability)
    component_extraction   FLOAT        NOT NULL,  -- 1 - extraction_rate
    component_mask         FLOAT        NOT NULL,  -- mean_ignorance_score from mask dist
    component_silent_decay FLOAT        NOT NULL,  -- min(1.0, silent_decay_count / 10)
    CONSTRAINT chk_classification CHECK (
        classification IN ('HIGH_IGNORANCE', 'NOMINAL', 'SPARSE')
    ),
    CONSTRAINT chk_priority_rank_coherence CHECK (
        (classification = 'HIGH_IGNORANCE' AND priority_rank IS NOT NULL)
        OR (classification != 'HIGH_IGNORANCE' AND priority_rank IS NULL)
    )
);

CREATE INDEX ix_ign_map_entry_tenant_job
    ON ignorance_map_entry (tenant_id, job_run_id);

CREATE INDEX ix_ign_map_entry_high_ignorance
    ON ignorance_map_entry (tenant_id, priority_rank)
    WHERE classification = 'HIGH_IGNORANCE';

CREATE INDEX ix_ign_map_entry_tenant_source
    ON ignorance_map_entry (tenant_id, source_type, time_bucket_start);
```

### 6.6 Table: `exploration_directive`

Directives consumed by Discovery Mechanism #3.

```sql
CREATE TABLE exploration_directive (
    id                   UUID        NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    tenant_id            VARCHAR(100) NOT NULL,
    job_run_id           UUID        NOT NULL,
    region_key           VARCHAR(500) NOT NULL,
    created_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
    expires_at           TIMESTAMPTZ  NOT NULL,  -- created_at + INTERVAL '48 hours'
    ignorance_score      FLOAT        NOT NULL CHECK (ignorance_score BETWEEN 0.0 AND 1.0),
    priority_rank        INTEGER      NOT NULL,
    recommended_action   VARCHAR(50)  NOT NULL,
    target_entity_types  TEXT[]       NOT NULL DEFAULT '{}',
    supporting_evidence  JSONB        NOT NULL DEFAULT '{}',
    consumed_by          VARCHAR(100),           -- NULL until read by downstream mechanism
    consumed_at          TIMESTAMPTZ,            -- NULL until consumed
    CONSTRAINT chk_consumed_coherence CHECK (
        (consumed_by IS NULL) = (consumed_at IS NULL)
    )
);

CREATE INDEX ix_expl_directive_tenant_unconsumed
    ON exploration_directive (tenant_id, priority_rank)
    WHERE consumed_at IS NULL AND expires_at > now();

CREATE INDEX ix_expl_directive_tenant_job
    ON exploration_directive (tenant_id, job_run_id);
```

### 6.7 Table: `ignorance_job_run`

Job provenance and execution history.

```sql
CREATE TABLE ignorance_job_run (
    id                UUID        NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    tenant_id         VARCHAR(100) NOT NULL,
    started_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    completed_at      TIMESTAMPTZ,            -- NULL until job completes
    status            VARCHAR(20)  NOT NULL DEFAULT 'RUNNING',
    window_start      TIMESTAMPTZ  NOT NULL,
    window_end        TIMESTAMPTZ  NOT NULL,
    time_bucket_size  INTERVAL     NOT NULL DEFAULT '30 minutes',
    fragments_scanned INTEGER      NOT NULL DEFAULT 0,
    extraction_stats_written  INTEGER NOT NULL DEFAULT 0,
    mask_stats_written        INTEGER NOT NULL DEFAULT 0,
    silent_decay_detected     INTEGER NOT NULL DEFAULT 0,
    map_entries_written       INTEGER NOT NULL DEFAULT 0,
    directives_generated      INTEGER NOT NULL DEFAULT 0,
    error_message     TEXT,                  -- NULL unless status = ERROR
    config_snapshot   JSONB        NOT NULL DEFAULT '{}',  -- weights and thresholds at run time
    CONSTRAINT chk_job_status CHECK (
        status IN ('RUNNING', 'COMPLETED', 'ERROR', 'PARTIAL')
    )
);

CREATE INDEX ix_ign_job_run_tenant_time
    ON ignorance_job_run (tenant_id, started_at DESC);
```

### 6.8 Additional Index for Silent Decay Anti-Join

The silent decay detection query (Section 4.3) uses `candidate_fragment_id` in
`snap_decision_record`. The existing `ix_sdr_new_frag` index covers `new_fragment_id` only.
A companion index is required:

```sql
CREATE INDEX ix_sdr_candidate_frag
    ON snap_decision_record (candidate_fragment_id);
```

This index is added by the ignorance mapping migration, not the T1.2 migration.

---

## 7. Provenance Logging

Every write to every table in Section 6 is traceable to a specific `ignorance_job_run.id`.
This satisfies the requirement that the origin of each map entry, directive, and silent decay
record is auditable without consulting application logs.

The extraction cause classification in `ignorance_silent_decay_record.extraction_cause` is
determined by consulting the existing `ProvenanceLogger` records. The mapping job queries the
provenance log for each silently-decayed fragment to find the enrichment chain event that
corresponds to its ingestion. If the provenance log shows entity extraction was attempted and
produced zero results (EXTRACTION_FAILURE), this is distinguished from a case where no
enrichment event exists at all (UNENRICHED — pipeline gap, distinct from model failure).

**Provenance log query pattern:**

```sql
-- For a given fragment_id, find the most recent enrichment provenance entry
SELECT event_type, metadata
FROM discovery_ledger
WHERE tenant_id = :tenant_id
  AND fragment_id = :fragment_id
  AND event_type IN (
      'ENRICHMENT_ENTITY_EXTRACTION_FAILED',
      'ENRICHMENT_TSLAM_FALLBACK',
      'ENRICHMENT_REGEX_FAILED',
      'ENRICHMENT_COMPLETED_NO_ENTITIES'
  )
ORDER BY created_at DESC
LIMIT 1;
```

If no matching provenance event exists, `extraction_cause = 'UNKNOWN'` is recorded. This
distinguishes a genuine data gap from a diagnosed failure.

The `config_snapshot` JSONB in `ignorance_job_run` captures the complete configuration at job
runtime (weights, thresholds, entity type list, time bucket size). If weights are changed
between runs, the provenance record reflects what configuration produced each map entry.

---

## 8. Interfaces

### 8.1 Internal Interface: `IgnoranceMappingJob`

This is the primary execution entry point. It is not a HTTP endpoint — it is a scheduled
background task invoked by the maintenance scheduler.

```python
class IgnoranceMappingJob:
    """
    Tier 1 ignorance mapping job. No LLM calls. Reads from abeyance_fragment,
    cold_fragment, snap_decision_record, discovery_ledger. Writes to ignorance_*
    and exploration_directive tables.
    """

    def __init__(
        self,
        session: AsyncSession,
        config: IgnoranceMappingConfig,
        provenance_logger: ProvenanceLogger,
    ) -> None: ...

    async def run(self, tenant_id: str) -> IgnoranceJobRunSummary:
        """
        Execute a full ignorance mapping pass for one tenant.
        Returns a summary with counts of records written and directives generated.
        Creates an ignorance_job_run record before starting; updates it on completion.
        """
        ...

    async def run_all_tenants(self) -> list[IgnoranceJobRunSummary]:
        """
        Iterate over all active tenants and call run() for each.
        Tenants are processed sequentially to avoid DB connection saturation.
        """
        ...
```

### 8.2 Configuration: `IgnoranceMappingConfig`

```python
@dataclass
class IgnoranceMappingConfig:
    # Time window for extraction and mask stats
    window_hours: int = 24              # look back this many hours
    time_bucket_minutes: int = 30       # aggregate into buckets of this size

    # High-ignorance classification thresholds
    high_ignorance_threshold: float = 0.40
    min_population_for_high_ignorance: int = 10
    low_extraction_rate_threshold: float = 0.60

    # Silent decay detection
    silent_decay_threshold: float = 0.05

    # Aggregation weights for region_ignorance_score
    weight_extraction: float = 0.50
    weight_mask: float = 0.35
    weight_silent_decay: float = 0.15

    # Directive expiry
    directive_expiry_hours: int = 48

    # Silent decay normalization denominator
    silent_decay_normalization: int = 10

    # Known entity types (extensible via config file)
    known_entity_types: list[str] = field(default_factory=lambda: [
        'NETWORK_ELEMENT', 'INTERFACE', 'ALARM_CODE', 'IP_ADDRESS',
        'CIRCUIT_ID', 'CUSTOMER_ID', 'VENDOR_TAG', 'FAILURE_MODE',
    ])

    # Schedule
    run_interval_minutes: int = 60      # how often to run the full job
```

### 8.3 Read Interface: `IgnoranceMapReader`

Used by Discovery Mechanism #3 (Enrichment Priority Routing) and by the observability API
to expose ignorance data to operators.

```python
class IgnoranceMapReader:

    async def get_active_directives(
        self,
        tenant_id: str,
        limit: int = 50,
    ) -> list[ExplorationDirective]:
        """
        Return unconsumed, non-expired directives for a tenant, ordered by priority_rank ASC.
        """
        ...

    async def mark_directive_consumed(
        self,
        directive_id: UUID,
        consumer_id: str,
    ) -> None:
        """
        Mark a directive as consumed. Called by Discovery Mechanism #3 when it has
        acted on the directive. Idempotent — safe to call multiple times.
        """
        ...

    async def get_ignorance_summary(
        self,
        tenant_id: str,
        as_of_job_run_id: UUID | None = None,
    ) -> IgnoranceSummary:
        """
        Return the most recent (or specified) ignorance map summary for a tenant.
        Includes high-ignorance region count, total silent decay count, and
        worst-dimension mask valid fractions.
        """
        ...

    async def get_silent_decay_records(
        self,
        tenant_id: str,
        since: datetime,
        limit: int = 500,
    ) -> list[SilentDecayRecord]:
        """
        Return individual silent decay records for operator review.
        Supports pagination via limit and since parameters.
        """
        ...
```

### 8.4 HTTP API Endpoints (read-only)

Two operator-facing endpoints are exposed. These are read-only and do not modify any state.

```
GET /api/v1/abeyance/ignorance/summary?tenant_id={id}
    Returns: IgnoranceSummary (most recent job run)

GET /api/v1/abeyance/ignorance/silent-decay?tenant_id={id}&since={iso8601}&limit={n}
    Returns: paginated list of SilentDecayRecord
```

These endpoints require authentication (same auth as all other Abeyance API endpoints).
They are not part of the Tier 1 core; they surface the data for operator tooling.

---

## 9. Concrete Telecom Example

### 9.1 Scenario

A mobile network operator runs a tenant `telco2`. Their event stream includes alarms from two
source types: `ALARM` (structured NMS alarm events) and `LOG` (syslog lines from routers
and base stations). Over a 6-hour window, 4,200 fragments are ingested: 3,100 ALARMs and
1,100 LOGs.

A known issue: the TSLAM-8B entity extraction model is struggling with vendor-specific alarm
codes from a recently added vendor (Vendor X). Vendor X alarm codes use a proprietary prefix
(`VX-`) that TSLAM was not trained on. The regex fallback also has no pattern for this prefix.

### 9.2 Ignorance Map Job Output

**Extraction stat results (abbreviated):**

| source_type | entity_type    | total_fragments | success_count | extraction_rate |
|---|---|---|---|---|
| ALARM       | ALL            | 3,100           | 2,945         | 0.950           |
| ALARM       | ALARM_CODE     | 3,100           | 1,240         | 0.400           |
| ALARM       | NETWORK_ELEMENT| 3,100           | 2,890         | 0.932           |
| LOG         | ALL            | 1,100           | 1,067         | 0.970           |
| LOG         | ALARM_CODE     | 1,100           | 1,043         | 0.948           |

The "ALL" aggregate extraction rate for ALARM is 0.950 — most fragments have at least one
entity extracted. But `ALARM_CODE` extraction rate is 0.400 — the Vendor X codes are being
missed. Fragments with no alarm code entity still have `NETWORK_ELEMENT` entities, so they
do reach snap evaluation, but with degraded topological embedding quality (the neighbourhood
expansion uses all entity types, and alarm code entities anchor the failure mode profile lookup).

**Mask distribution results (ALARM source_type, 6h window):**

| mask_semantic | mask_topological | mask_operational | fraction |
|---|---|---|---|
| TRUE  | TRUE  | TRUE  | 0.820 |
| TRUE  | TRUE  | FALSE | 0.092 |
| TRUE  | FALSE | FALSE | 0.041 |
| FALSE | FALSE | FALSE | 0.029 |
| other patterns | | | 0.018 |

mean_ignorance_score = 0.148 (low; most fragments are well-formed)
is_high_ignorance = FALSE (mean < 0.40 threshold)

**Silent decay detection:**

In the prior 24h, 18 ALARM fragments expired with empty `extracted_entities`. These are Vendor X
alarms from a branch office where the NMS sends alarm notifications without the standard alarm
fields populated. Investigation via provenance log shows `ENRICHMENT_REGEX_FAILED` for all 18
fragments — TSLAM failed, regex fallback also found no pattern.

`ignorance_silent_decay_record` receives 18 rows with `extraction_cause = EXTRACTION_FAILURE`.

**Ignorance map entry for (ALARM, ALARM_CODE, current 6h bucket):**

```json
{
  "source_type": "ALARM",
  "entity_type": "ALARM_CODE",
  "region_fragment_count": 3100,
  "component_extraction": 0.600,
  "component_mask": 0.148,
  "component_silent_decay": 0.180,
  "region_ignorance_score": 0.600 * 0.50 + 0.148 * 0.35 + 0.180 * 0.15,
  "region_ignorance_score_computed": 0.380,
  "classification": "NOMINAL",
  "recommended_action": "REVIEW_REGEX_COVERAGE"
}
```

region_ignorance_score = 0.380. This is below the HIGH_IGNORANCE_THRESHOLD of 0.40, so this
region is classified as NOMINAL rather than HIGH_IGNORANCE. No exploration directive is
generated. However, the `REVIEW_REGEX_COVERAGE` action is attached to alert the operator that
the regex coverage is insufficient for `ALARM_CODE` on `ALARM` source type.

**After the operator adds a regex pattern for `VX-\d{4,6}`:**

The next job run shows extraction_rate(ALARM, ALARM_CODE) = 0.88. The region_ignorance_score
drops to 0.141. The `REVIEW_REGEX_COVERAGE` recommendation is no longer generated. The 18
historical silent decay records remain as a permanent audit trail of the gap.

### 9.3 High-Ignorance Example (contrast case)

Suppose the TSLAM-8B service goes down for 4 hours during a network outage. During that window,
800 ALARM fragments are ingested with TSLAM down and the regex fallback producing empty results
for 70% of alarms (only structured alarms with parseable fields succeed):

- extraction_rate(ALARM, ALL) = 0.30
- mask_topological_valid_fraction = 0.28 (topology depends on entities)
- mask_operational_valid_fraction = 0.55 (some fingerprints built from structured fields)
- mean_ignorance_score = 0.39
- silent_decay_count for this 4h window = 0 (fragments are still ACTIVE, not yet expired)

component_extraction = 1.0 - 0.30 = 0.70
component_mask = 0.39
component_silent_decay = 0.0

region_ignorance_score = 0.70 * 0.50 + 0.39 * 0.35 + 0.0 * 0.15 = 0.350 + 0.137 = 0.487

region_ignorance_score = 0.487 >= HIGH_IGNORANCE_THRESHOLD (0.40)
AND region_fragment_count = 800 >= MIN_POPULATION (10)

Classification: HIGH_IGNORANCE
priority_rank: 1 (highest for this tenant at this run)
recommended_action: RETRY_ENTITY_EXTRACTION

An `ExplorationDirective` is written. Discovery Mechanism #3 picks this up and schedules
re-enrichment of the 800 affected ALARM fragments once the TSLAM service is restored.

---

## 10. Computational Complexity Summary

| Operation | Complexity | Bound |
|---|---|---|
| Extraction stat computation | O(F_active × E × W) | F_active ≤ 500K (RES-3.1-2), E ≤ 32 (config), W ≤ 48 (24h / 30min buckets) |
| Mask distribution computation | O(F_active × W) | Same bounds; single-pass SQL aggregate |
| Silent decay detection (identify candidates) | O(F_expired_this_cycle) | Bounded by decay batch size |
| Silent decay detection (anti-join) | O(F_expired × log(SDR)) | SDR indexed on new_fragment_id and candidate_fragment_id |
| Ignorance map aggregation | O(S × E × W) | S ≤ 6 source types, E ≤ 32 entity types, W ≤ 48 buckets = ≤ 9,216 regions |
| Directive generation | O(H) | H = number of HIGH_IGNORANCE regions; H ≤ S × E × W |
| **Total per run** | **O(F_active)** | Dominated by extraction stat scan; all other operations are sublinear in active fragment count |

The job is designed to complete within 5 minutes for the maximum fragment population per tenant.
At 500K active fragments with a 24h window and 30-minute buckets, the extraction stat computation
involves approximately 500K × 6 (source types) × 32 (entity types) = 96M boolean evaluations.
This is handled by the database's FILTER aggregation in a single sequential scan per source
type per tenant, not in application code.

**No N+1 patterns:** All aggregations are set-based SQL operations. The only per-row operation
is the provenance log lookup for silently-decayed fragments (Step 3 of Section 4.3), which is
bounded by the number of newly expired fragments in a single maintenance cycle — typically
hundreds, not tens of thousands.

---

## 11. Integration Points

| System | Direction | What is consumed |
|---|---|---|
| `abeyance_fragment` | READ | Mask columns, extracted_entities, snap_status, created_at, source_type |
| `snap_decision_record` | READ | new_fragment_id, candidate_fragment_id (for silent decay anti-join) |
| `discovery_ledger` | READ | Provenance events for extraction cause classification |
| `MaintenanceService` | TRIGGER | IgnoranceMappingJob is invoked after each decay pass completes |
| Discovery Mechanism #3 | READ | `exploration_directive` table via `IgnoranceMapReader.get_active_directives()` |
| `AbeyanceMetrics` (T2.6) | EMIT | New metrics: `abeyance_ignorance_high_regions`, `abeyance_ignorance_silent_decay_total`, `abeyance_ignorance_job_duration_seconds` (see Section 12) |

The ignorance mapping job does NOT write to `abeyance_fragment`. It does NOT trigger enrichment
directly. It does NOT modify snap decision records. All modifications are confined to the six
tables defined in Section 6.

---

## 12. New Observability Metrics

Three metrics are added to the `abeyance_` namespace defined in T2.6. They follow the same
naming conventions and emission patterns established there.

```
abeyance_ignorance_high_regions
    Type: Gauge
    Labels: tenant_id
    Description: Count of HIGH_IGNORANCE regions identified in the most recent job run.
    Emission: IgnoranceMappingJob.run() on completion.

abeyance_ignorance_silent_decay_total
    Type: Counter
    Labels: tenant_id, source_type, extraction_cause
    Description: Cumulative count of fragments classified as silently decayed.
    Emission: IgnoranceMappingJob during Step 4 of Section 4.3, one increment per record.

abeyance_ignorance_job_duration_seconds
    Type: Histogram
    Buckets: [1, 5, 10, 30, 60, 120, 180, 300, 600]
    Labels: tenant_id, status
    Description: Wall-clock duration of each ignorance mapping job run per tenant.
    Emission: IgnoranceMappingJob.run() on exit.
```

Alerting rule for persistent high-ignorance regions (recommended addition to T2.6 alerting):

```yaml
- alert: AbeyancePersistentHighIgnoranceRegion
  expr: |
    abeyance_ignorance_high_regions > 0
  for: 2h
  labels:
    severity: warning
    subsystem: ignorance_mapping
  annotations:
    summary: "High-ignorance regions present for tenant {{ $labels.tenant_id }} for 2+ hours"
    description: >
      One or more region-entity-type combinations have been classified as HIGH_IGNORANCE
      for over 2 hours. Unconsumed exploration directives are waiting. Check that
      Discovery Mechanism #3 is running and processing directives.
      Root cause may be sustained entity extraction failure (F-4.2) or T-VEC outage.
```

---

*End of T3.1 Ignorance Mapping Specification*
*Version: 1.0 | Task: T3.1 | Discovery Tier: 1 | Phase: 3*
