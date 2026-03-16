# Abeyance Memory v3.0 — Failure Recovery Procedures

**Task**: T2.7 — Failure Recovery Procedures
**Date**: 2026-03-16
**Scope**: Deterministic recovery for all failure scenarios with the local-LLM architecture

---

## Overview

The Abeyance Memory subsystem has a clear durability hierarchy:

1. **PostgreSQL** is the system of record. INV-12 guarantees deterministic full state rebuild from PostgreSQL alone.
2. **Redis** is a best-effort notification layer. Loss of Redis never loses state.
3. **T-VEC / TSLAM** are enrichment accelerators. Failure degrades embedding quality but does not block fragment ingestion.
4. **Vector indexes** are derived structures. They can be rebuilt from stored vectors in `abeyance_fragment`.
5. **In-process state** (circuit breakers, BFS caches) is ephemeral and always disposable.

All recovery procedures must preserve the following invariants:
- INV-11: No similarity computation against invalid vectors (NULL + FALSE mask)
- INV-12: PostgreSQL alone is sufficient for full rebuild
- INV-10: Provenance trails remain append-only through and after recovery
- INV-7: Tenant isolation is never compromised during recovery

---

## Scenario 1: T-VEC 1.5B Unavailability

### What T-VEC Produces
- `emb_semantic` (1536-dim, but sub-divided: SEMANTIC_DIM=512 + TOPOLOGICAL_DIM=384 + OPERATIONAL_DIM=384 = 1280 dims via T-VEC)
- Controls `mask_semantic`, `mask_topological`, `mask_operational` on `abeyance_fragment`
- CPU-bound process, ~3GB RAM, no GPU dependency

### Detection
- Primary: Health check endpoint on the T-VEC sidecar process. Liveness probe with 10-second timeout.
- Secondary: Enrichment chain receives embedding call timeout or connection refused. The `_compute_embeddings()` method in `enrichment_chain.py` catches this exception.
- Observable metric: `abeyance_enrichment_mask_false_rate` rising above baseline for `mask_semantic`, `mask_topological`, `mask_operational` simultaneously.
- Alarm condition: Three consecutive fragment enrichments with all three T-VEC masks FALSE.

### Recovery Steps

**During Outage (degrade, do not block):**

1. `EnrichmentChain._compute_embeddings()` catches the exception from the T-VEC call.
2. Set `emb_semantic = NULL`, `mask_semantic = FALSE`.
3. Set `emb_topological = NULL`, `mask_topological = FALSE`.
4. Set `emb_operational = NULL`, `mask_operational = FALSE`.
5. `emb_temporal` is sinusoidal (pure math, always valid) — compute normally. `mask_temporal = TRUE`.
6. Set `emb_enriched = NULL`. The enriched embedding is the concatenation of all four sub-vectors. If any T-VEC component is NULL, the enriched embedding cannot be formed and must be NULL.
7. Persist the fragment to PostgreSQL with all three T-VEC masks FALSE. The fragment is valid — it is in state INGESTED with degraded enrichment.
8. Snap evaluation in `SnapEngine.evaluate()` must skip similarity scoring for sub-vector pairs where either fragment's mask is FALSE for that dimension. A fragment with `mask_semantic = FALSE` and `mask_topological = FALSE` can only be evaluated on entity overlap (Jaccard) and operational fingerprint similarity. The snap threshold is not relaxed — absence of valid embedding dimensions reduces the composite score naturally.
9. Accumulation graph edges can still be created from entity-based affinity. Topological and semantic components of affinity will be absent, producing lower edge weights.

**On Recovery:**

The backfill procedure is an offline job that re-enriches fragments that have one or more T-VEC masks FALSE and `status IN ('INGESTED', 'ACTIVE', 'NEAR_MISS')`. SNAPPED, STALE, EXPIRED, and COLD fragments are not backfilled — their snap decisions are immutable (INV-5).

```
Backfill Query:
  SELECT id, raw_content, source_type, event_timestamp, tenant_id
  FROM abeyance_fragment
  WHERE (mask_semantic = FALSE OR mask_topological = FALSE OR mask_operational = FALSE)
    AND status IN ('INGESTED', 'ACTIVE', 'NEAR_MISS')
  ORDER BY created_at ASC
  LIMIT 500  -- batch size
```

For each fragment in the backfill batch:
1. Call T-VEC with `raw_content` to produce `emb_semantic`, `emb_topological`, `emb_operational`.
2. Retrieve existing `emb_temporal` (it was computed correctly during original enrichment).
3. Recompute `emb_enriched` as the concatenation of the four sub-vectors.
4. UPDATE `abeyance_fragment` SET `emb_semantic = $1, emb_topological = $2, emb_operational = $3, emb_enriched = $4, mask_semantic = TRUE, mask_topological = TRUE, mask_operational = TRUE` WHERE `id = $5`.
5. Log the backfill operation to `fragment_history` as event_type `EMBEDDING_BACKFILL` (INV-10).
6. After backfill, re-trigger `SnapEngine.evaluate()` for the fragment if it is still in ACTIVE or NEAR_MISS state.

**Rate Limiting the Backfill:**
The backfill job runs at a maximum of 500 fragments per minute to avoid overwhelming T-VEC on restart. It competes with live enrichment for T-VEC capacity; live enrichment takes priority. The job is idempotent — it can be interrupted and restarted without double-processing because it only processes fragments where at least one T-VEC mask is FALSE.

### Data Loss Assessment
- **No fragment data is lost.** All fragments are persisted to PostgreSQL with their raw content.
- **Snap decisions may be degraded or deferred.** Fragments enriched during outage have lower composite snap scores due to missing dimensions, resulting in more NEAR_MISS outcomes and fewer SNAPPED outcomes. Some hypothesis formations that would have occurred are deferred until backfill completes.
- **Edge weights in accumulation_graph are lower.** Edges created during outage have entity-only affinity. These are not retroactively updated — backfill re-triggers snap evaluation which may add new edges, but existing edges are not recalculated.

### SLA Impact
- Fragment ingestion: No degradation. Fragments continue to be accepted and persisted.
- Snap formation: Degraded. Entity-only matching reduces precision. Expect 20-40% reduction in snap rate depending on content type.
- Backfill duration: Estimated 500 fragments/minute throughput. 100K fragments with masks FALSE requires approximately 3.3 hours to fully backfill.
- Recovery is complete when the backfill queue is empty and `abeyance_enrichment_mask_false_rate` returns to baseline.

---

## Scenario 2: TSLAM-8B Unavailability

### What TSLAM-8B Produces
- Entity extraction from `raw_content` via `EnrichmentChain._llm_extract_entities()`
- Hypothesis generation (TSLAM provides structured failure mode candidates and relationship hypotheses)
- GPU-bound, highest-resource component of the enrichment pipeline

### Detection
- Primary: TSLAM-8B health check fails or returns error on a test inference call.
- Secondary: `_llm_extract_entities()` raises an exception or returns an empty result for content that regex would catch.
- Observable metric: Entity extraction method tagging in fragment metadata — `entity_extraction_method: "llm"` vs `entity_extraction_method: "regex"`. A spike in regex-method fragments indicates TSLAM-8B fallback is active.
- TSLAM-4B (CPU fallback) has its own health check. If TSLAM-4B is also unavailable, the system falls through to regex-only.

### Recovery Steps

**TSLAM-8B Down, TSLAM-4B Available:**

`EnrichmentChain._resolve_entities()` has a defined fallback order:
1. Attempt `_llm_extract_entities()` via TSLAM-8B.
2. On failure (exception, timeout, or empty result), attempt `_llm_extract_entities()` via TSLAM-4B.
3. On TSLAM-4B failure, fall through to `_regex_extract_entities()`.

When TSLAM-8B is unavailable, the fallback to TSLAM-4B is automatic and transparent. Entity quality is somewhat reduced (4B vs 8B parameter model) but TSLAM-4B covers the same entity domains.

**TSLAM-8B and TSLAM-4B Both Down (Regex Fallback):**

`_regex_extract_entities()` uses `ENTITY_PATTERNS` to extract entities matching known telco patterns:

| Pattern | Domain |
|---------|--------|
| `(LTE\|NR\|GSM\|UMTS)-\w+-[A-Z0-9]+` | RAN |
| `SITE-[A-Z]+-\d+` | SITE |
| `ENB-\d+`, `GNB-\d+` | RAN |
| `TN-[A-Z]+-\d+`, `S1-\d+-\d+` | TRANSPORT |
| `VLAN-\d+`, IPv4 CIDR | IP |
| `CR-[A-Z]+-\d+` | CORE |
| `VNF-[A-Z0-9-]+` | VNF |
| `CHG-\d{4}-[A-Z]+-\d+` | (change record) |

Regex fallback limitations:
- Free-text descriptions of entities are not extracted ("the router in the Frankfurt PoP" is missed).
- Entity type inference is pattern-only — entities not matching the patterns are dropped.
- Hypothesis generation is suspended during TSLAM outage. Hypotheses are queued.

**Hypothesis Generation Queue:**

When TSLAM is unavailable, hypothesis generation requests are written to a durable queue table:

```sql
-- Table: hypothesis_generation_queue
-- Columns: id, tenant_id, fragment_id, raw_content, created_at, status, attempt_count
```

The queue is processed when TSLAM recovers. Processing order: FIFO by `created_at`. Maximum 3 retry attempts per entry. After 3 failures, status is set to ABANDONED and logged to `fragment_history` as event_type `HYPOTHESIS_GENERATION_ABANDONED`.

**Entity Quality Flag:**

Fragments enriched via regex-only fallback are tagged with `entity_extraction_method: "regex"` in their `metadata` JSON column. This enables targeted re-extraction after TSLAM recovery.

**On TSLAM Recovery:**

Re-extraction job:
```
SELECT id, raw_content, tenant_id
FROM abeyance_fragment
WHERE metadata->>'entity_extraction_method' = 'regex'
  AND status IN ('INGESTED', 'ACTIVE', 'NEAR_MISS')
ORDER BY created_at ASC
LIMIT 200
```

For each fragment:
1. Call `_llm_extract_entities()` via TSLAM-8B.
2. Compare newly extracted entity set to existing `fragment_entity_ref` rows.
3. INSERT new entity refs for newly discovered entities.
4. Do NOT delete existing entity refs — entities found by regex are valid, LLM adds to them.
5. Re-trigger `SnapEngine.evaluate()` for the fragment if still in ACTIVE or NEAR_MISS — new entities may create new snap opportunities.
6. Log to `fragment_history` as event_type `ENTITY_REEXTRACTION`.

Process the hypothesis generation queue in parallel with re-extraction.

### Data Loss Assessment
- **No fragment data is lost.** All fragments are persisted.
- **Entity coverage is reduced during outage.** Free-text entity references are missed. This reduces snap opportunities for fragments that reference entities only in natural language.
- **Hypothesis quality is deferred, not lost.** The queue ensures all fragments that needed hypothesis generation will receive it after recovery.
- **Snap decisions made during outage use reduced entity sets.** These snap decisions are immutable (INV-5). Re-extraction may identify additional snap relationships not caught during the outage, but existing snaps are not invalidated.

### SLA Impact
- Fragment ingestion: No degradation.
- Entity coverage: Reduced to pattern-matched entities only. Estimated 30-50% reduction in entity coverage for free-text sources (TICKET_TEXT, CLI_OUTPUT).
- Snap rate: Reduced proportionally to entity coverage reduction.
- Hypothesis generation: Deferred until recovery. Queue depth grows at the fragment ingestion rate.
- Recovery queue drain: Process at a maximum of 200 fragments per minute after TSLAM restores, giving live traffic priority.

---

## Scenario 3: Redis Loss

### Redis Role in the System
Redis provides:
1. **Notification streams** (`RedisNotifier`): Consumers receive snap events, cluster events, and state changes. Stream length capped at 10,000 per stream (RES-3.2-4).
2. **Back-pressure tracking**: The event ingestion queue uses Redis to track pending count for HIGH_WATER_MARK and CRITICAL_WATER_MARK (RES-3.4-1).
3. **Ephemeral deduplication cache**: Dedup keys computed by `_compute_dedup_key()` may be cached in Redis for fast lookup.

Redis is explicitly not the system of record. PROV-4.3-1 documents the Write-Ahead Pattern: PostgreSQL is committed first, Redis notification is best-effort.

### Detection
- Primary: Connection refused or timeout on Redis health check.
- Secondary: `RedisNotifier` raises `ConnectionError` during notification attempt.
- Observable metric: `redis_notification_failure_count` counter in application metrics.

### State Lost vs. Recoverable

**State Lost Permanently on Redis Failure (no replica):**
- Pending stream messages not yet consumed by downstream consumers. If consumers have not processed these messages before Redis fails, those specific notification events are lost. Consumers must fall back to PostgreSQL polling.
- Back-pressure counters. These are reset on Redis restart. The ingestion queue resumes accepting at full rate on reconnect regardless of actual pending count. This is acceptable — PostgreSQL is not overwhelmed because the back-pressure system is a throttle, not a gate.
- Ephemeral dedup cache entries. Fragments may be double-ingested if the same event arrives twice during the window between Redis loss and the dedup cache rebuild. The dedup key is also written to `abeyance_fragment.dedup_key` in PostgreSQL, so duplicate detection can be done via PostgreSQL query at the cost of higher latency.

**State Recoverable from PostgreSQL WAL:**
- All fragment state. `abeyance_fragment` contains the authoritative lifecycle state.
- All snap decisions. `snap_decision_log` contains full scoring breakdowns.
- All cluster evaluations. `cluster_snapshot` contains member lists and scores.
- All edge data. `accumulation_edge` contains the full accumulation graph.
- All provenance. `fragment_history` contains every state transition.
- Consumer position. Consumers recover by querying PostgreSQL for events with `created_at > last_processed_timestamp`, as documented in PROV-4.3-1.

### Recovery Steps

**During Redis Outage:**

1. `RedisNotifier.notify()` catches the connection error, logs a WARNING, and returns without raising. The application layer continues normally — the fragment write to PostgreSQL has already committed.
2. Downstream consumers that rely on Redis streams switch to PostgreSQL polling mode. They query `fragment_history` for new events since their last processed timestamp. Polling interval: 5 seconds.
3. Back-pressure tracking falls back to PostgreSQL: count of fragments in `status = 'INGESTED'` with `created_at > NOW() - INTERVAL '5 minutes'` is used as a proxy for queue depth.
4. Dedup is performed against PostgreSQL `abeyance_fragment.dedup_key` column with a covering index. Latency increases from ~1ms (Redis) to ~5ms (PostgreSQL index scan), acceptable under normal load.

**On Redis Recovery:**

1. `RedisNotifier` reconnects automatically on next notification attempt.
2. No replay of missed notifications is performed — consumers are already in PostgreSQL polling mode and have processed all events via that path.
3. Consumers switch back to Redis streams from PostgreSQL polling. The transition point is: after two consecutive successful Redis operations, switch back to stream mode.
4. Redis stream position for consumers is reset to the current tail (not replayed). Notifications for events during the outage were delivered via PostgreSQL polling — replaying them via Redis would cause double-processing.
5. Back-pressure counters are reset to zero and rebuild from the PostgreSQL proxy measurement over the next 30 seconds.

### Data Loss Assessment
- **No fragment data is lost.** PostgreSQL was committed before any Redis operation was attempted.
- **Notification events are lost for consumers that were not in PostgreSQL polling mode.** Any consumer that did not implement the PostgreSQL fallback (PROV-4.3-1) will miss events during the outage. This is a consumer implementation gap, not a data loss in the system of record.
- **Dedup window has a brief gap at the moment of Redis failure.** Fragments whose dedup key was in Redis but not yet committed to `abeyance_fragment` (impossible given write-ahead order) would be duplicated. In practice, the write-ahead pattern ensures dedup_key is in PostgreSQL before any Redis operation, so no gap exists.

### SLA Impact
- Fragment ingestion: No degradation. Ingestion continues normally.
- Notification latency: Increases from near-real-time (Redis) to polling interval (5 seconds). Consumers experience up to 5-second delay on snap and cluster notifications.
- Dedup latency: Increases from ~1ms to ~5ms. Negligible at normal throughput.
- Back-pressure accuracy: Proxy measurement is less precise than the real counter. In practice, this only matters if the system is near the water marks during the Redis outage.

---

## Scenario 4: Vector Index Corruption

### Indexes at Risk
The `abeyance_fragment` table has IVFFlat indexes per embedding column:

| Index Name | Column | Dimension |
|------------|--------|-----------|
| `ix_frag_emb_semantic` | `emb_semantic` | 512 |
| `ix_frag_emb_topological` | `emb_topological` | 384 |
| `ix_frag_emb_temporal` | `emb_temporal` | 256 |
| `ix_frag_emb_operational` | `emb_operational` | 384 |
| `ix_frag_emb_enriched` | `emb_enriched` | 1536 |
| `ix_cold_frag_emb` | `cold_fragment.enriched_embedding` | 1536 |

IVFFlat indexes can be corrupted by unclean shutdown, storage hardware failure, or partial writes during index rebuild. The base table data (the actual vector values stored in the row) is separate from the index structure and is protected by PostgreSQL WAL.

### Detection
- Primary: pgvector ANN query using `<=>` operator raises `ERROR` or returns inconsistent results (known test queries return wrong nearest neighbors).
- Secondary: PostgreSQL `pg_catalog.pg_index` shows `indisvalid = false` for the affected index.
- Diagnostic query:
  ```sql
  SELECT indexname, indisvalid
  FROM pg_indexes JOIN pg_class ON pg_class.relname = pg_indexes.indexname
  JOIN pg_index ON pg_index.indexrelid = pg_class.oid
  WHERE tablename IN ('abeyance_fragment', 'cold_fragment');
  ```
- Application-level detection: ANN search returns 0 results for a query that known fragments should satisfy. The `SnapEngine._targeted_retrieval()` method falls back to exact scan if ANN returns 0 results for a non-empty entity set.

### Impact During Rebuild

The rebuild procedure uses `CREATE INDEX CONCURRENTLY`. PostgreSQL allows concurrent reads and writes during a concurrent index build. The implications are:

- New fragments can be ingested and persisted normally.
- ANN searches fall back to exact scan (sequential scan with `<=>` operator, no index) for the duration of the rebuild. Exact scan is O(N) vs. O(sqrt(N)) for IVFFlat.
- At 500K active fragments (RES-3.1-2), exact scan for `emb_enriched` (1536-dim) takes approximately 2-5 seconds per query depending on hardware, vs. <100ms with IVFFlat. This is the primary SLA impact.
- Snap evaluation slows proportionally. The back-pressure system (RES-3.4-1) may engage if snap evaluation backs up.
- Multiple indexes can be rebuilt concurrently if the system has sufficient I/O capacity. Rebuilding all six concurrently is safe but stresses disk and CPU. Recommended order: rebuild `emb_enriched` first (most performance-critical for cold storage search), then `emb_semantic` (used in snap scoring), then the remaining four.

### Rebuild Procedure (Per Index)

**Step 1: Identify the corrupt index.**
```sql
SELECT indexname FROM pg_indexes
WHERE tablename = 'abeyance_fragment'
  AND indexname LIKE 'ix_frag_emb_%';
```

**Step 2: Drop the corrupt index.**
```sql
DROP INDEX CONCURRENTLY ix_frag_emb_semantic;
```
If `DROP INDEX CONCURRENTLY` fails because the index is in an invalid state, use `DROP INDEX` (non-concurrent) during a maintenance window.

**Step 3: Rebuild with IVFFlat.**
```sql
CREATE INDEX CONCURRENTLY ix_frag_emb_semantic
  ON abeyance_fragment
  USING ivfflat (emb_semantic vector_cosine_ops)
  WITH (lists = 100);
```
The `lists` parameter for IVFFlat should be set to `sqrt(N)` where N is the number of non-NULL rows for that column. At 500K active fragments with 80% mask TRUE, N ≈ 400K, giving `lists = 632`. Round to `lists = 100` for the initial build (conservative, always valid). Re-tune after rebuild.

**Step 4: Verify the index.**
```sql
SET enable_seqscan = off;
SELECT id FROM abeyance_fragment
ORDER BY emb_semantic <=> $query_vector
LIMIT 5;
SET enable_seqscan = on;
```
If this returns results without error, the index is healthy.

**Step 5: Repeat for each corrupt index.**

**Cold Storage (`cold_fragment`):**
```sql
DROP INDEX CONCURRENTLY ix_cold_frag_emb;
CREATE INDEX CONCURRENTLY ix_cold_frag_emb
  ON cold_fragment
  USING ivfflat (enriched_embedding vector_cosine_ops)
  WITH (lists = 100);
```

### Fallback During Rebuild

`SnapEngine._targeted_retrieval()` must implement a fallback for the period when the IVFFlat index is absent:
1. Attempt ANN search via `<=>` with index.
2. On `ProgrammingError` or `OperationalError` from pgvector, fall back to: retrieve candidates matching entity overlap first (Jaccard pre-filter via `fragment_entity_ref`), then compute cosine similarity in Python for the reduced candidate set.
3. Log the fallback via a counter metric `snap_engine_ann_fallback_count`. A sustained non-zero rate indicates the index is absent or corrupt.

### Data Loss Assessment
- **No data is lost.** Vector values are stored in the base table, not the index. The index is a derived access structure only.
- **Snap decisions made during rebuild are valid but less precise.** The entity-overlap pre-filter reduces the candidate set differently than ANN. Some candidates that ANN would have returned are missed, and some that ANN would have excluded are included. Net effect: marginally different snap outcomes, all of which are valid given the data examined.

### SLA Impact
- ANN search latency: Increases from <100ms to 2-5 seconds per query during rebuild.
- Snap throughput: Reduced by 10-50x depending on active fragment population.
- Rebuild duration: Estimated 30-90 minutes for `emb_enriched` at 500K fragments with `CREATE INDEX CONCURRENTLY`.
- Back-pressure may engage at HIGH_WATER_MARK (500 pending) during rebuild peak. This is expected and acceptable.

---

## Scenario 5: Partial Event Loss

### Definition
Partial event loss occurs when a fragment is persisted to `abeyance_fragment` but one or more of its embedding dimensions is NULL with a FALSE mask, not due to a full T-VEC or TSLAM outage, but due to a transient error during enrichment (network timeout to a specific endpoint, out-of-memory on a single inference, partial enrichment chain crash).

### Mask-Based Detection

Every fragment row carries four mask columns:
- `mask_semantic` (BOOLEAN)
- `mask_topological` (BOOLEAN)
- `mask_temporal` (BOOLEAN, always TRUE — sinusoidal, cannot fail)
- `mask_operational` (BOOLEAN)

A fragment with partial enrichment shows one or two FALSE masks while `mask_temporal = TRUE` and status is beyond INGESTED.

Detection query:
```sql
SELECT id, tenant_id, mask_semantic, mask_topological, mask_temporal, mask_operational,
       created_at, status
FROM abeyance_fragment
WHERE (mask_semantic = FALSE OR mask_topological = FALSE OR mask_operational = FALSE)
  AND mask_temporal = TRUE
  AND status NOT IN ('EXPIRED', 'COLD')
ORDER BY created_at DESC;
```

A non-empty result set with recent `created_at` timestamps indicates partial enrichment loss occurring now or in the recent past.

### Re-Enrichment of Missing Dimensions

**Semantic only (mask_semantic = FALSE, others TRUE):**
Re-call T-VEC with `raw_content` to produce only `emb_semantic`. Update the row. Recompute `emb_enriched` from the now-complete set.

**Topological only (mask_topological = FALSE):**
Re-call T-VEC with the topological text input (built from `entity_refs` joined with `shadow_topology` neighbourhood). This requires the entity refs to be intact — if they are, recompute `emb_topological` and update.

**Operational only (mask_operational = FALSE):**
Re-call T-VEC with the operational text input (built from failure modes and fingerprint stored in `operational_fingerprint` column). Update `emb_operational`.

**Multiple dimensions missing simultaneously:**
Re-run the full `_compute_embeddings()` call against the persisted data. This is equivalent to a full backfill for that fragment.

After any mask is set to TRUE from FALSE, recompute `emb_enriched` as the concatenation of the four sub-vectors and update the row.

**Re-enrichment triggers snap re-evaluation** for fragments in ACTIVE or NEAR_MISS status. The fragment may now qualify for snaps it previously missed.

### Distinguishing Partial Loss from Intentional NULL

The mask columns are the authoritative indicator. A NULL embedding with mask TRUE is a bug (should never occur — the mask system is the invariant guard). A NULL embedding with mask FALSE is expected and intentional. Re-enrichment targets only mask-FALSE rows.

### Data Loss Assessment
- **Fragment content is never lost.** `raw_content` is persisted before any enrichment begins.
- **Snap opportunities during the partial loss window may be missed.** These are not recoverable retroactively — re-enrichment creates new snap opportunities going forward but cannot re-run historical evaluations against past fragments that have since changed state.

### SLA Impact
- Isolated partial loss events: No measurable SLA impact. Re-enrichment runs as a low-priority background job.
- Systemic partial loss (many fragments affected): Treated as a T-VEC or TSLAM degradation event — see Scenarios 1 and 2.

---

## Scenario 6: Mid-Enrichment Crash

### Definition
A mid-enrichment crash occurs when the application process dies (OOM kill, SIGKILL, host crash) during execution of `EnrichmentChain.enrich()`, between the point where the fragment is written to PostgreSQL and the point where enrichment completes and all masks are updated.

### Detection

A fragment in mid-enrichment crash state has the following signature:
- `status = 'INGESTED'` (the initial status assigned at write time)
- All T-VEC masks FALSE: `mask_semantic = FALSE AND mask_topological = FALSE AND mask_operational = FALSE`
- `mask_temporal = FALSE` (sinusoidal computation had not yet run, or temporal enrichment is bundled with the failed call)
- `created_at` is stale: `created_at < NOW() - INTERVAL '30 minutes'` and status has not advanced

The combination of ALL masks FALSE plus stale `created_at` is the fingerprint of a crashed enrichment, as opposed to a fragment still in the enrichment pipeline.

Detection query:
```sql
SELECT id, tenant_id, created_at, status
FROM abeyance_fragment
WHERE mask_semantic = FALSE
  AND mask_topological = FALSE
  AND mask_temporal = FALSE
  AND mask_operational = FALSE
  AND status = 'INGESTED'
  AND created_at < NOW() - INTERVAL '30 minutes';
```

A non-empty result set indicates fragments that crashed mid-enrichment and were not recovered.

**Critical distinction from a fragment still in the enrichment pipeline:**
A fragment in active enrichment will have `created_at < NOW() - INTERVAL '30 minutes'` only if enrichment has been running for more than 30 minutes, which is far beyond the normal enrichment duration. Normal enrichment completes in under 60 seconds. The 30-minute threshold is therefore a reliable stale indicator.

### Recovery vs. Expiry Decision

**Recovery (attempt first):**

If the fragment's `raw_content` is non-NULL and within the 64KB limit (INV-6), re-enrichment is possible:
1. Call `EnrichmentChain.enrich()` with the fragment's stored `raw_content`, `source_type`, `event_timestamp`, `tenant_id`, and `source_ref`.
2. If a dedup key match exists (another fragment with the same dedup_key was successfully enriched), the crash fragment is a duplicate. Mark it EXPIRED and log to `fragment_history` as event_type `CRASH_DEDUP_EXPIRED`.
3. If enrichment succeeds, update the fragment with the computed embeddings, masks, and entity refs. Advance status to ACTIVE.
4. Log to `fragment_history` as event_type `CRASH_RECOVERY`.

**Expiry (if recovery is not possible):**

If `raw_content` is NULL (crash occurred before write completed — rare, requires transaction rollback detection), or if enrichment fails after 3 retry attempts:
1. Set `status = 'EXPIRED'`.
2. Log to `fragment_history` as event_type `CRASH_RECOVERY_FAILED`.
3. Do not archive to cold storage — the fragment has no valid content or embedding.

**Recovery Window:**
The recovery job runs every 10 minutes, checking for the crash signature. Fragments that have been in the crash state for more than 730 days (INV-6 hard lifetime) are expired without recovery attempt.

### Idempotency

The recovery job is idempotent. If it runs against the same fragment multiple times:
- If enrichment succeeds on first attempt, status advances to ACTIVE. Subsequent runs skip ACTIVE fragments.
- If enrichment fails, attempt_count increments. After 3 failures, status is set to EXPIRED. Subsequent runs skip EXPIRED fragments.

### Data Loss Assessment
- **Raw content is preserved** if the PostgreSQL transaction committed before the crash. The crash must occur after the initial INSERT commits for the fragment to appear in the detection query.
- **Enrichment work is lost** and must be redone. This is acceptable — enrichment is a derived computation from `raw_content`.
- **Entity refs may be partially written** if the crash occurred between the fragment INSERT and the `fragment_entity_ref` INSERTs. The recovery job must re-run entity extraction regardless of existing entity refs. It should replace (DELETE + INSERT) entity refs for crash-recovered fragments to avoid partial/corrupt entity sets.

### SLA Impact
- Crash recovery is a background job with no impact on live fragment processing.
- Fragments in crash state do not participate in snap evaluation (status = INGESTED, masks all FALSE) — no spurious snap matches.
- Recovery window: up to 40 minutes from crash to recovery (10-minute job interval + up to 30-minute detection window).

---

## Scenario 7: Clustering Instability

### Definition
Clustering instability occurs when the accumulation graph oscillates — fragments repeatedly enter and leave cluster memberships, causing `cluster_snapshot` to grow unboundedly and edge weights to fluctuate. This violates INV-4 (monotonic cluster convergence).

### Root Causes in the Current Architecture
1. **Edge weight decrease**: INV-4 states edges only increase scores. If the codebase has a path where `affinity_score` passed to `add_or_update_edge()` is lower than the existing edge's score and the UPDATE applies it, oscillation occurs. This is a code invariant violation, not a system failure.
2. **Fragment expiry + re-ingestion**: When a fragment expires and a near-identical event is re-ingested, a new fragment_id is assigned. The new fragment starts without edges. The cluster may temporarily split and reform, creating edge churn in the snapshot log.
3. **Concurrent enrichment race**: Two enrichment workers process semantically similar fragments simultaneously. Both pass snap evaluation against the same stored fragments and create overlapping edge sets. Under normal load this is benign, but under high-throughput burst, it can create short-term cluster instability.

### Detection
- Primary: `cluster_snapshot` insert rate exceeds 5x the fragment ingestion rate for the same tenant over a 10-minute window.
- Secondary: The same `cluster_id` appears in `cluster_snapshot` with significantly different member sets in consecutive evaluations (set symmetric difference > 20% of members).
- Monitoring query:
  ```sql
  SELECT tenant_id, COUNT(*) as snapshot_count, MIN(evaluated_at), MAX(evaluated_at)
  FROM cluster_snapshot
  WHERE evaluated_at > NOW() - INTERVAL '10 minutes'
  GROUP BY tenant_id
  HAVING COUNT(*) > 50;
  ```

### Dampening Strategy

**Edge Score Monotonicity Enforcement (prevents source of oscillation):**

In `AccumulationGraph.add_or_update_edge()`, the UPDATE must use:
```sql
UPDATE accumulation_edge
SET affinity_score = GREATEST(affinity_score, $new_score),
    updated_at = NOW()
WHERE tenant_id = $tenant_id
  AND fragment_a_id = $frag_a
  AND fragment_b_id = $frag_b;
```
The `GREATEST()` function enforces INV-4 at the database level. Any code path that passes a lower score does not decrease the edge. This is the primary dampening mechanism.

**Cluster Evaluation Cooling Period:**

After a cluster is evaluated and a `cluster_snapshot` is written, the same cluster (same set of fragment_ids) should not be re-evaluated within a cooling window of 60 seconds. Implementation: cache the last evaluation timestamp per cluster member set hash in Redis (best-effort), or in a `cluster_evaluation_cooldown` table in PostgreSQL (durable fallback).

If Redis is available, use:
```
Key: cluster_cooldown:{tenant_id}:{sorted_member_set_hash}
TTL: 60 seconds
```

If Redis is unavailable, skip cooling period enforcement — the cluster may be re-evaluated more frequently, but correctness is maintained.

**Burst Dampening for Concurrent Enrichment:**

When `detect_and_evaluate_clusters()` is triggered by a fragment enrichment, the trigger is the fragment's accumulation graph neighborhood, not the full graph. This limits the scope of each cluster evaluation to the subgraph adjacent to the triggering fragment. Oscillation in one region of the graph does not cascade to the full graph.

**Fragment Re-ingestion Edge Churn:**

When a new fragment is created that is semantically equivalent to an expired fragment (same dedup key is a strong signal), the system should attempt to link the new fragment's edges to the expired fragment's historical cluster membership, carrying forward edge context rather than starting fresh. This requires:
1. On enrichment, check if `dedup_key` matches an EXPIRED fragment.
2. If so, copy the expired fragment's `accumulation_edge` rows to the new fragment's id (adjusting foreign keys).
3. This is an optimization, not a requirement — the system converges correctly without it, just more slowly.

### Edge Churn Measurement

Edge churn rate: number of new `accumulation_edge` inserts per fragment per hour. Expected baseline: 0-3 new edges per fragment per hour. Churn alarm threshold: >10 new edges per fragment per hour for the same fragment_id over a 1-hour window.

```sql
SELECT fragment_a_id, fragment_b_id, COUNT(*) as update_count
FROM accumulation_edge
WHERE updated_at > NOW() - INTERVAL '1 hour'
  AND tenant_id = $tenant_id
GROUP BY fragment_a_id, fragment_b_id
HAVING COUNT(*) > 10;
```

A non-empty result indicates pathological edge churn for specific fragment pairs. Investigate the similarity function inputs for those pairs.

### Data Loss Assessment
- **No data is lost during clustering instability.** All cluster snapshots are append-only (INV-10). The provenance log is complete.
- **Snap decisions are unaffected.** Snap is per-fragment-pair (INV-5), not per-cluster. Cluster instability does not retroactively invalidate snaps.
- **Cluster scores may be transiently lower** during instability (smaller cluster = lower LME score with correlation discount). They recover as the cluster stabilizes.

### SLA Impact
- `cluster_snapshot` table growth rate increases. If churn persists for hours, disk space may be consumed faster than expected. Monitor table size and trigger the cluster snapshot archival job if needed.
- Cluster snap notifications to Redis streams may fire more frequently. Consumer idempotency is required — consumers should deduplicate cluster events by `cluster_id + evaluated_at`.
- No impact on fragment ingestion, snap evaluation, or decay.

---

## Recovery Decision Matrix

| Scenario | Detectable Without Human? | Auto-Recovery? | Max Data Loss | SLA Impact |
|----------|--------------------------|----------------|---------------|------------|
| T-VEC unavailability | Yes (health check) | Yes (NULL + mask FALSE; backfill on recovery) | Zero fragment loss; deferred snaps | Reduced snap rate |
| TSLAM-8B unavailability | Yes (health check + method tag) | Yes (4B fallback, then regex; hypothesis queue) | Zero fragment loss; reduced entity coverage | Reduced snap precision |
| Redis loss | Yes (connection error) | Yes (PostgreSQL polling fallback) | Notification events for non-fallback consumers | +5s notification latency |
| Vector index corruption | Yes (ANN error or indisvalid) | Yes (exact scan fallback; concurrent rebuild) | Zero | Severe snap latency increase during rebuild |
| Partial event loss | Yes (mask query) | Yes (background re-enrichment job) | Missed snap window during loss | Low (background only) |
| Mid-enrichment crash | Yes (all masks FALSE + stale created_at) | Yes (background recovery job; expiry after 3 failures) | Fragment lost only if raw_content NULL at crash | Low (background only) |
| Clustering instability | Yes (snapshot rate + member set diff) | Partial (GREATEST() prevents oscillation; cooling period dampens) | None | Elevated disk/stream usage |

---

## Invariant Preservation Through Recovery

All recovery procedures are required to preserve the following invariants without exception:

| Invariant | Recovery Constraint |
|-----------|-------------------|
| INV-5 (Irreversible Snaps) | Re-enrichment and re-extraction never unsnap a fragment. New snap opportunities are created; existing snaps are not invalidated. |
| INV-7 (Tenant Isolation) | All backfill, recovery, and re-enrichment queries must include `tenant_id` scope. Cross-tenant recovery operations are prohibited. |
| INV-10 (Append-Only Provenance) | All recovery events (EMBEDDING_BACKFILL, ENTITY_REEXTRACTION, CRASH_RECOVERY, etc.) must be logged to `fragment_history`. No state changes are silent. |
| INV-11 (Valid Embeddings) | No similarity computation is performed against a fragment with a FALSE mask on the relevant embedding dimension. Recovery sets embeddings only when computation succeeds — never zero-fills. |
| INV-12 (State Rebuild from PostgreSQL) | All recovery procedures read source data from PostgreSQL. No recovery procedure depends on Redis or in-memory state as its input. |

---

*Document complete. Task T2.7 output.*
