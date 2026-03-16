# Abeyance Memory v3.0 — Scalability Analysis

**Task**: T6.1 — Scalability Analysis
**Phase**: 6
**Date**: 2026-03-16
**Status**: Design Specification
**Scope**: Bottleneck identification, capacity modelling, horizontal scaling triggers
**Target**: 50M active fragments, 10K–100K events/sec, 100 tenants

---

## 1. Executive Summary

The v3.0 architecture is capable of handling the stated targets but only with specific
horizontal scaling interventions. On a single-node deployment (one App VM, one DB VM), the
system saturates well before the upper targets. The primary bottlenecks, in order of impact:

| Rank | Bottleneck | Saturates at | Mitigation |
|------|-----------|-------------|-----------|
| 1 | T-VEC CPU throughput | ~2 fragments/sec (~7,200/hr) steady state | Horizontal T-VEC workers |
| 2 | TSLAM-8B GPU throughput | ~1.5 fragments/sec per GPU | Multiple GPU sidecars |
| 3 | pgvector HNSW / IVFFlat ANN latency at 50M rows | ~200–500ms per query at scale | Index partitioning; read replicas |
| 4 | Enrichment pipeline concurrency gate | `ENRICHMENT_CONCURRENCY=4` hard ceiling | Distribute enrichment workers |
| 5 | Expiration batch I/O | 14.4M rows/day ingestion; 730-day retention = ~10.5B row ceiling without expiration | Run expiration daily; TOMBSTONE path critical |
| 6 | Accumulation graph clustering (hot path) | ~1,000 edge evaluations per trigger, bounded post-fix | Already bounded; safe to 500K active fragments |
| 7 | Discovery mechanism batch jobs | Unparallelised per-tenant scans; scheduling window narrows at 100 tenants | Parallelise with per-tenant workers |

---

## 2. T-VEC 1.5B Throughput Analysis

### 2.1 Baseline Numbers (per node, ARM Ampere Altra, Oracle A1)

From `serving_architecture.md §2.4`:

| Mode | Batch Size | Texts/sec | Fragments/sec | Latency (p50) |
|------|-----------|-----------|---------------|---------------|
| Single text, no coalescing | 1 | 2–3 | 0.7–1.0 | ~400ms |
| Micro-batch (3 texts per fragment) | 3 | 5–7 | 1.7–2.3 | ~500ms |
| Coalesced batch | 32 | 15–20 | 5.0–6.7 | ~2.0s |

Each fragment requires exactly 3 T-VEC calls (semantic, topological, operational). With micro-batching
these are issued as a single `model.encode([s, t, o])` call.

**Tokens/sec estimate**: Average text length is 128 tokens. At micro-batch throughput of 5–7 texts/sec,
the model processes approximately 640–896 tokens/sec on a single ARM Ampere Altra OCPU pair.

With TVEC_MAX_WORKERS=2, two batches can overlap (one tokenising, one in forward pass). This is the
safe ceiling on the reference hardware — adding a third worker risks exhausting the 12 GB VM RAM
(3 GB model + 2×0.75 GB activations already = 4.5 GB; a third worker adds ~0.75 GB activations
while Kafka, Caddy, and FastAPI consume the remainder).

### 2.2 Fragment Throughput at Scale

| Ingestion Rate | T-VEC Demand | Single Node Capacity | Gap |
|----------------|-------------|---------------------|-----|
| 1,000 events/min (17/sec) | 51 texts/sec | 15–20 texts/sec | **Saturated 3–4x** |
| 10,000 events/min (167/sec) | 501 texts/sec | 15–20 texts/sec | **Saturated 25–33x** |
| 100K events/sec | 300K texts/sec | 15–20 texts/sec | **Saturated ~15,000x** |

At steady-state production (10K events/sec = 600K events/min), a single T-VEC node is not remotely
adequate for real-time enrichment. The enrichment pipeline must be decoupled from ingest via a durable
queue and run asynchronously, with multiple T-VEC workers operating in parallel.

**Key finding**: For 10K–100K events/sec targets, T-VEC enrichment must be horizontally distributed.
The enrichment pipeline is already async (Kafka consumer model); the scaling path is adding enrichment
worker processes, each with their own T-VEC instance.

### 2.3 Fragment Enrichment vs. Ingest Decoupling

The practical deployment model separates:
- **Ingest tier**: Accept events, write raw fragment rows (status=INGESTED) to PostgreSQL — no T-VEC dependency on the ingest path.
- **Enrichment tier**: Consumer workers pull fragments from the INGESTED queue and call T-VEC. Enrichment is latency-tolerant (minutes, not milliseconds).

Under this model, the T-VEC capacity constraint becomes a queue depth and enrichment latency question, not an ingest blocker. The scaling trigger for additional enrichment workers is:
- Queue depth of INGESTED fragments exceeds 10,000 (approximately 5 minutes of enrichment backlog at one worker's capacity), OR
- Enrichment p95 latency exceeds 60 seconds per fragment.

### 2.4 T-VEC Horizontal Scaling Trigger

| Metric | Threshold | Action |
|--------|-----------|--------|
| INGESTED queue depth | > 10,000 rows | Add 1 enrichment worker (= 1 T-VEC instance) |
| Enrichment p95 latency | > 60s/fragment | Add 1 enrichment worker |
| T-VEC timeout rate | > 5% over 5-min window | Investigate OOM; optionally add worker |
| Enrichment lag (queue drain rate < ingest rate) | Sustained > 10 min | Add 2 enrichment workers |

Each additional enrichment worker is an independent process (FastAPI worker or separate container)
with its own T-VEC executor. Workers must be stateless; the INGESTED queue is coordinated by a
Kafka consumer group or a PostgreSQL-backed work queue with advisory locks.

---

## 3. TSLAM-8B Throughput Analysis

### 3.1 GPU Path (vLLM, Primary)

From `serving_architecture.md §3.4`:

| Scenario | Input tokens | Output tokens | Throughput | Latency (p50) |
|----------|-------------|---------------|------------|---------------|
| Single request (entity extraction) | ~400 | ~150 | 50–80 tokens/sec output | ~2–3s |
| 4 concurrent requests (vLLM continuous batching) | ~400 | ~150 | 150–250 tokens/sec aggregate | ~3–4s |

**Fragments/sec (GPU)**:
- Single request: 1 fragment / 2.5s = **0.4 fragments/sec**
- 4 concurrent (max-num-seqs=8): ~1.5 fragments/sec aggregate

With `ENRICHMENT_CONCURRENCY=4` and `TSLAM_CONCURRENCY=8`, vLLM handles batching internally.
One GPU saturates at approximately **5,400 fragments/hour** (1.5 × 3,600).

### 3.2 CPU Fallback Path (llama-cpp, TSLAM-4B)

From `serving_architecture.md §4.3`:

| Scenario | Input tokens | Output tokens | Throughput | Latency (p50) |
|----------|-------------|---------------|------------|---------------|
| Single request, serialised | ~400 | ~150 | 8–12 tokens/sec output | ~12–18s |

**Fragments/sec (CPU fallback)**: 1 fragment / 15s = **0.067 fragments/sec** (~240 fragments/hour).

This is a degraded fallback only. At any volume exceeding a few hundred fragments per hour,
CPU-only TSLAM is a bottleneck. It must not be treated as a production-grade serving path for
high-throughput deployments.

### 3.3 TSLAM vs. T-VEC Throughput Comparison

| Component | Fragments/sec (nominal) | Fragments/hour |
|-----------|------------------------|----------------|
| T-VEC (micro-batch, single node) | 1.7–2.3 | 6,120–8,280 |
| TSLAM-8B GPU (4 concurrent) | ~1.5 | ~5,400 |
| TSLAM-4B CPU (serialised) | ~0.067 | ~240 |

T-VEC and TSLAM-8B GPU are approximately matched in throughput on the reference hardware.
The enrichment pipeline's real bottleneck is whichever runs slower on the deployed hardware.
Benchmark both on target ARM hardware; T-VEC estimates are conservative for NEON SIMD.

### 3.4 TSLAM Horizontal Scaling Trigger

| Metric | Threshold | Action |
|--------|-----------|--------|
| TSLAM p95 latency | > 10s (GPU) | Check vLLM queue depth; if sustained, add GPU sidecar |
| TSLAM backend | `fallback` for > 15 min | Operator intervention: restart vLLM sidecar |
| Entity extraction method | `regex` on > 20% fragments in a 10-min window | TSLAM degraded; scale CPU fallback or restore GPU |
| Hypothesis generation queue depth | > 5,000 rows | Add TSLAM GPU capacity or increase max_num_seqs |

---

## 4. pgvector at 50M Rows — Query Latency Estimates

### 4.1 Index Type Assessment: IVFFlat vs. HNSW

The v3.0 design specifies **IVFFlat** for both `abeyance_fragment` (hot) and `cold_fragment` (cold).
The forensic audit and cold storage redesign maintained IVFFlat with a dynamic `lists = ceil(sqrt(n))`.
HNSW is not currently specified but is evaluated here for completeness.

**IVFFlat at 50M rows**:

IVFFlat divides vectors into Voronoi cells (lists). At query time, `nprobe` cells are scanned.
- `lists = ceil(sqrt(50,000,000)) = ceil(7,071) ≈ 7,071`
- Default `nprobe = 1`: scans 50M / 7,071 ≈ 7,072 vectors per query
- Recommended `nprobe = 10` for 95%+ recall: scans 70,720 vectors per query

**IVFFlat query latency estimates at 50M rows, 1536-dim**:

| nprobe | Vectors scanned | Estimated latency (single core, Postgres heap scan) |
|--------|----------------|------------------------------------------------------|
| 1 | ~7,072 | ~20–50ms |
| 10 | ~70,720 | ~150–400ms |
| 20 | ~141,440 | ~300–800ms |

These estimates assume:
- Postgres shared_buffers: 2 GB (vectors partially cached)
- ARM NEON SIMD for cosine distance (pgvector uses this)
- No concurrent heavy writes during query

With `tenant_id` filtering applied as a pre-filter (not as an IVFFlat predicate), the effective
scan scope drops by 1/100 for a 100-tenant deployment with even distribution:
- Per-tenant rows: 50M / 100 = 500K
- `lists = ceil(sqrt(500,000)) = 708`
- At `nprobe=10`: scans 7,080 vectors per query
- **Estimated per-tenant IVFFlat latency: 10–30ms** — well within SLA

**Critical insight**: The 50M row target is a global figure. If tenant isolation is enforced by
the `tenant_id` filter at the IVFFlat query level (which the v3.0 code does: `.where(tenant_id == tid)`),
the per-tenant index traversal cost scales with per-tenant row count, not total row count. At 100 tenants
with even distribution, 500K rows/tenant is the effective index size.

**HNSW comparison** (for reference; not currently specified):
- HNSW at 500K rows/tenant: query latency ~2–10ms at 95%+ recall
- HNSW memory cost: ~3 bytes/dim/vector at M=16 → 1536 × 3 × 500K ≈ 2.3 GB per tenant index
- At 100 tenants: 230 GB for HNSW indexes alone — impractical on the reference hardware

**Verdict**: IVFFlat with per-tenant query filtering is the correct choice at this scale on the
reference hardware. HNSW becomes viable only if per-tenant row counts exceed ~2M and dedicated
hardware (high-RAM instances) is available.

### 4.2 Index Rebuild at 50M Rows

The cold storage weekly rebuild procedure (`§4.3` of `cold_storage.md`) uses `CREATE INDEX CONCURRENTLY`.
At 50M rows, this is a multi-hour operation:

| Table size | Estimated rebuild duration | I/O pressure |
|------------|---------------------------|--------------|
| 500K rows (per-tenant hot) | 30–90 min | Moderate |
| 5M rows (large tenant cold) | 3–8 hours | High |
| 50M rows (global cold, shared index) | 24–72 hours | Very high |

**Recommendation**: Partition `cold_fragment` by `tenant_id` (PostgreSQL declarative partitioning or
logical sharding). Each partition has its own IVFFlat index. Rebuild is per-partition, parallelisable,
and scoped to a manageable row count (~500K/tenant). This is the primary mitigation for cold storage
scalability.

### 4.3 pgvector Capacity Limits

| Scenario | Row count | lists | nprobe | p50 latency | p99 latency | Assessment |
|----------|-----------|-------|--------|-------------|-------------|------------|
| Single tenant, hot store | 500K | 708 | 10 | 10–30ms | 50–100ms | Safe |
| Single tenant, hot store | 2M | 1,415 | 10 | 30–80ms | 100–300ms | Acceptable |
| Single tenant, hot store | 5M | 2,236 | 10 | 80–200ms | 300–700ms | Marginal |
| Global cold, unpartitioned | 50M | 7,071 | 10 | 200–500ms | 1–2s | Unacceptable |
| Global cold, partitioned | 500K/tenant | 708 | 10 | 10–30ms | 50–100ms | Safe |

**Hard capacity limit**: A single unpartitioned IVFFlat index on `cold_fragment` at 50M rows
with `nprobe=10` yields latency in the 200–500ms range at p50, exceeding the acceptable threshold
for interactive re-hydration queries. Partitioning by `tenant_id` is required before the cold store
reaches ~5M total rows.

**Horizontal scaling trigger for pgvector**:

| Metric | Threshold | Action |
|--------|-----------|--------|
| Hot store ANN p95 latency | > 100ms | Rebuild index with higher `nprobe`; consider read replica |
| Cold store total rows | > 5M (global) or > 1M/tenant | Partition `cold_fragment` by tenant_id |
| `snap_engine_ann_fallback_count` | > 0 sustained | Index absent or corrupt; rebuild immediately |
| DB vacuum lag on `abeyance_fragment` | > 1 hour | Hot store has fragmented heap; VACUUM ANALYZE |

---

## 5. Accumulation Graph at Scale — Remediated Query Performance

### 5.1 Post-Fix Complexity (F-5.2 / F-5.3 from `accumulation_graph_fix.md`)

The T2.1 remediation replaced two severe defects:

**F-5.2 (detect_and_evaluate_clusters)**: Replaced full-tenant edge load with a two-hop anchored
BFS bounded by `MAX_CLUSTER_EDGES = MAX_CLUSTER_SIZE × MAX_EDGES_PER_FRAGMENT = 50 × 20 = 1,000`.

| Active fragments | Edges (worst case pre-fix) | Edges loaded post-fix |
|-----------------|--------------------------|----------------------|
| 100K | 1M | ≤ 1,000 |
| 500K | 5M | ≤ 1,000 |
| 1M | 10M | ≤ 1,000 |
| 50M (cold) | N/A (cold store) | ≤ 1,000 |

Post-fix, each cluster evaluation is O(1) in active fragment count for the hot path (triggered by
a specific fragment). Memory consumption per call is bounded at ~200 KB (1,000 edges × ~200 bytes
per ORM object), independent of tenant size.

**F-5.3 (prune_stale_edges)**: Replaced 2N+1 round-trips with a single LEFT JOIN + batch DELETE.

| Batch size | DB round-trips pre-fix | DB round-trips post-fix | Time (1ms avg) |
|------------|------------------------|------------------------|----------------|
| 1,000 edges | 2,001 | 2 | ~2ms |
| 10,000 edges | 20,001 | 2 | ~2ms |

### 5.2 Scale Limits for the Remediated Graph

The post-fix accumulation graph is safe to:

| Metric | Safe limit | Failure mode beyond limit |
|--------|------------|--------------------------|
| Active fragments per tenant (hot path) | ~2M | Two-hop expansion step 2 uses `ANY(:candidate_ids)` with up to 21 UUIDs. At >2M fragments/tenant, index selectivity drops for the bitmap scan; query time increases. |
| Total edges per tenant | ~20M | Background paginated scan (5K edges/page) at 20M edges requires 4,000 pages. At 50ms/page, full scan = ~200s. Schedule during off-peak windows. |
| MAX_PRUNE_BATCH at 10K edges | 10,000 | If stale edge accumulation exceeds 10K/maintenance pass, increase batch size or run more frequently. |
| Cluster evaluation concurrency | ENRICHMENT_CONCURRENCY = 4 | At 4 concurrent enrichments, 4 simultaneous cluster evaluations. Each bounded at 1K edges. No contention at this scale. |

### 5.3 Background Full Evaluation at Scale

When `trigger_fragment_id` is None (background scan), the keyset-paginated path processes 5K
edges per page. At 100 tenants × 20K edges/tenant = 2M total edges, a single background pass
requires 400 pages at ~50ms/page = ~20 seconds. This is a maintenance window operation and
should be scheduled daily, not continuously.

**Scaling trigger for background graph scans**:

| Metric | Threshold | Action |
|--------|-----------|--------|
| Total `accumulation_edge` rows per tenant | > 500K | Schedule daily background evaluation during off-peak hours |
| Edge churn rate (inserts/hour per fragment) | > 10 | Clustering instability; investigate similarity function inputs |
| `cluster_snapshot` insert rate > 5× fragment ingestion rate | 10-min window | Cooling period enforcement (Scenario 7 from `failure_recovery.md`) |

---

## 6. Cold Storage Volume Projections and Expiration Impact

### 6.1 Ingestion Rate vs. Retention Tiers

From `cold_storage.md §6.1`, the stated growth model is:
- 10K events/min × 60 × 24 = **14.4M rows/day** entering the system (not yet in cold)
- Hot store retains active fragments; cold store receives fragments after they expire from hot

Hot store retention is governed by the snap lifecycle (fragments expire after decay). Assume a
90-day average hot store retention (empirical; varies by tenant activity). Then cold ingest:
- Steady state: fragments expiring from hot at ~14.4M/day enter cold at ~14.4M/day

**Without expiration**: cold_fragment grows at 14.4M/day. At day 730 the table reaches ~10.5B rows.
With expiration tiers (v3.0 policy):

| Day | ACTIVE rows | COMPRESSED rows | TOMBSTONED rows | DELETED rows | Total live rows |
|-----|-------------|-----------------|-----------------|--------------|-----------------|
| 90 | 1.3B | 0 | 0 | 0 | 1.3B |
| 365 | 5.3B | 0 | 0 | 0 | 5.3B |
| 730 | 5.3B | 5.3B | 0 | 0 | 10.5B |
| 1095 | 5.3B | 5.3B | 5.3B | 0 | 15.8B |
| 1460 | 5.3B | 5.3B | 5.3B | 5.3B deletions processed | ~10.5B |

At steady state (after day 1095), the table stabilises at ~10.5B rows with annual churn of ~5.3B
deletions. This is a very large table; operational concerns follow.

### 6.2 Storage Volume Estimates

**Per row footprint (ACTIVE tier)**:
- Fixed columns (UUID × 3, strings, floats, timestamps): ~300 bytes
- `emb_semantic` Vector(1536): 1536 × 4 bytes = 6,144 bytes
- `emb_topological` Vector(1536): 6,144 bytes
- `emb_temporal` Vector(256): 1,024 bytes
- `emb_operational` Vector(1536): 6,144 bytes
- JSONB columns (entities, failure_mode_tags): ~200 bytes avg
- Total per row (ACTIVE): **~20 KB**

**Per row footprint (TOMBSTONED tier)**:
- All four embedding columns set NULL (save ~19 KB)
- Total per row (TOMBSTONED): **~500 bytes**

**Storage projections at steady state (10.5B rows)**:

| Tier mix | Rows | Avg row size | Total data size |
|----------|------|-------------|----------------|
| ACTIVE (< 1 year) | 5.3B | 20 KB | ~100 TB |
| COMPRESSED (1–2 years) | 5.3B | 19 KB | ~95 TB |
| TOMBSTONED (2–3 years) | 5.3B | 0.5 KB | ~2.6 TB |

The TOMBSTONED tier saves ~99% of storage compared to ACTIVE. However, ACTIVE + COMPRESSED still
represent ~195 TB of data at the stated ingestion rate. This is far beyond a single 100 GB block
volume on Oracle Always Free.

**Critical finding**: At 10K events/sec (600K/min), the stated ingestion rate in the requirements
cannot be supported on a single Oracle Always Free VM. The cold storage volume projections assume a
significantly lower real-world throughput (1K–10K events/min is more realistic for the reference
platform). At a more realistic 1K events/min:

| Scenario | events/min | rows/day (cold) | Storage (ACTIVE, steady-state 1yr) |
|----------|-----------|-----------------|-------------------------------------|
| Reference platform | 1,000 | 1.44M | ~10.5 TB |
| Production SaaS (small) | 10,000 | 14.4M | ~105 TB |
| Requirements ceiling | 6,000,000 | 8.6B | ~62.5 PB |

**The 10K–100K events/sec target is architecturally incompatible with PostgreSQL-only cold storage
on a single VM.** The cold storage tier requires a tiered storage architecture (object storage for
TOMBSTONED and DELETED rows, columnar store for COMPRESSED) at scale.

### 6.3 Expiration Batch Job Performance

The `run_expiration_pass()` method processes each tier with separate UPDATE and DELETE statements.
At 10M rows/day entering the expiration pipeline:

| Operation | Rows/day | Estimated time (1M rows/min UPDATE) | Frequency |
|-----------|----------|--------------------------------------|-----------|
| ACTIVE → COMPRESSED | ~14.4M (after 365 days) | ~14 min | Daily |
| COMPRESSED → TOMBSTONED | ~14.4M (after 730 days) | ~14 min | Daily |
| TOMBSTONED → DELETE | ~14.4M (after 1095 days) | ~2 min (DELETE is faster than UPDATE) | Daily |

**Index considerations for expiration**: The `ix_cold_frag_expires` index on `(expiration_tier, expires_at)`
supports all three expiration queries efficiently. At 10B+ rows, UPDATE statements touching 14M rows/day
will generate significant WAL volume and checkpoint pressure. Use `work_mem = 256MB` for the expiration
session and schedule during the lowest-traffic window.

### 6.4 Expiration Impact on ANN Index

Each TOMBSTONE operation NULLs four embedding columns and changes `expiration_tier`. The IVFFlat partial
index (`WHERE mask_X = false`) must be rebuilt after significant TOMBSTONE batches. Tombstoning 14.4M
rows/day represents a ~0.3% change per index at 5B ACTIVE rows — below the 20% drift threshold for
automatic rebuild. No additional rebuilds are triggered by normal expiration cadence.

**Exception**: The first TOMBSTONE pass (at day 730) simultaneously tombstones ~5.3B rows. This will
trigger immediate index rebuild for all four columns. Plan for a 24–72 hour maintenance window.

---

## 7. Discovery Mechanism Batch Jobs at Scale

### 7.1 Current Architecture (Inferred)

Discovery jobs identify new fragments eligible for snap evaluation, cluster recalculation, and
backfill. From `failure_recovery.md`, these include:

| Job | Operation | Current batch size | Frequency |
|-----|-----------|-------------------|-----------|
| T-VEC backfill | Re-enrich mask=FALSE fragments | 500 fragments/pass | On recovery |
| TSLAM re-extraction | Re-extract regex-tagged fragments | 200 fragments/pass | On recovery |
| Crash recovery | Re-enrich all-mask-FALSE + stale | Unbounded (detection query) | Every 10 min |
| Background cluster eval | Full-graph union-find scan | 5K edges/page | Background |
| Expiration pass | Tiered UPDATE/DELETE | Per-tenant, unbounded | Daily |
| IVFFlat rebuild | `CREATE INDEX CONCURRENTLY` | Per-column | Weekly |

### 7.2 Scheduling Constraints at 100 Tenants

At 100 tenants, each per-tenant batch job must complete within its scheduling window:

| Job | Per-tenant duration (estimate) | Time for 100 tenants (sequential) | Daily window available | Problem? |
|-----|-------------------------------|----------------------------------|----------------------|---------|
| Expiration pass | ~14 min (at 14.4M rows/day/tenant) | ~23 hours | 24 hours | **Marginal** |
| IVFFlat rebuild | 30–90 min (500K rows) | 50–150 hours | 168 hours (weekly) | **Blocked** |
| Background cluster eval | ~20s (2M edges/tenant) | ~33 min (100 tenants) | 24 hours | Safe |
| Crash recovery | ~5s (detection query + small batch) | ~8 min (100 tenants) | 24 hours | Safe |

**Critical scheduling constraint**: Weekly IVFFlat rebuild for 100 tenants × 4 indexes = 400 index
builds. At 90 min/build sequentially, this requires 600 hours — far exceeding the 168-hour weekly window.

**Expiration pass**: At 100 tenants and 14.4M rows/day/tenant (high-throughput scenario), sequential
per-tenant expiration requires 23 hours/day. Any increase in ingest rate or tenant count would push this
over 24 hours.

### 7.3 Parallelism Requirements

| Job | Parallelism strategy | Max parallel degree | Notes |
|-----|---------------------|-------------------|-------|
| Expiration pass | Tenant-parallel via worker pool | 10 tenants concurrent | UPDATE contention per tenant is negligible; main limit is DB connection pool |
| IVFFlat rebuild | Tenant-parallel; 1 index per tenant at a time | 10 tenants concurrent (40 concurrent index builds is too high) | `CREATE INDEX CONCURRENTLY` requires 1 WAL sender per build |
| Background cluster eval | Tenant-parallel via async tasks | 20 tenants concurrent | CPU-bound; event loop safe (keyset query + in-memory union-find) |
| T-VEC backfill | Tenant-parallel; rate-limited per tenant | 5 tenants concurrent | T-VEC executor bounded; per-tenant rate limit to 500 frags/min |

**Horizontal scaling trigger for batch jobs**:

| Metric | Threshold | Action |
|--------|-----------|--------|
| Expiration pass wall-clock time | > 20 hours/day | Add expiration workers; parallelise to 10 tenants |
| IVFFlat rebuild backlog | > 7 days (weekly window missed) | Parallelise rebuilds; upgrade DB VM; partition tables |
| Tenant count | > 50 | Enable parallel batch job execution for all maintenance job types |
| Per-tenant fragment count (hot) | > 1M | Increase IVFFlat rebuild from weekly to twice weekly |

### 7.4 Crash Recovery Job at Scale

The crash recovery detection query (`all masks FALSE + status=INGESTED + created_at > 30 min`)
runs every 10 minutes across all tenants. At 100 tenants and 500K fragments/tenant, the detection
query scans the `abeyance_fragment` index `ix_abeyance_fragment_tenant_status` for status=INGESTED rows,
then evaluates mask columns. This is bounded by the number of INGESTED fragments (those awaiting
enrichment), not total fragment count. At steady-state where enrichment keeps pace with ingest, the
INGESTED population is small (~minutes of backlog). The query remains fast.

**Degradation case**: If enrichment workers fall behind and the INGESTED population grows to millions,
the crash recovery detection query performs a large index scan. Mitigation: add a partial index
`WHERE status = 'INGESTED' AND mask_semantic = FALSE AND mask_topological = FALSE AND mask_operational = FALSE AND mask_temporal = FALSE`
to accelerate crash detection. This is a supplementary index recommendation beyond the current schema.

---

## 8. Concrete Capacity Limits and Horizontal Scaling Triggers Summary

### 8.1 Capacity Limits (Single-Node Reference Deployment)

| Dimension | Single-Node Limit | Bottleneck |
|-----------|------------------|-----------|
| **Fragment enrichment rate** | 2–7 fragments/sec | T-VEC CPU (ARM Ampere Altra, 2 workers) |
| **Entity extraction rate** | 0.4–1.5 fragments/sec | TSLAM-8B GPU (vLLM, max-num-seqs=8) |
| **Net enrichment throughput** | 0.4–1.5 fragments/sec | TSLAM is the tighter bound |
| **Hot store ANN query latency** | <30ms (up to 500K frags/tenant) | pgvector IVFFlat, per-tenant filtering |
| **Cold store ANN query latency** | <30ms (up to 500K frags/tenant); 200–500ms at 50M global unpartitioned | Partitioning required above 5M total rows |
| **Accumulation graph hot-path** | Bounded at 1,000 edges/call — no scalability limit post-fix | Post-fix constant-time per trigger |
| **Expiration job** | ~14 min/tenant/day at 14.4M rows/day | Parallelisation required above 40 tenants |
| **IVFFlat rebuild** | ~90 min/tenant, 400 builds/week for 100 tenants | Parallelisation required above 2 tenants |
| **Cold storage capacity** | 100 GB block volume (Oracle Always Free) | **Hard limit**; at 14.4M rows/day, filled in hours without expiration |

### 8.2 Horizontal Scaling Triggers (Ordered by Urgency)

| # | Trigger Condition | Scale Action | Urgency |
|---|------------------|-------------|---------|
| 1 | Tenant count > 10 AND weekly IVFFlat rebuild time > 7 days | Enable parallel rebuild worker pool (10 concurrent) | High |
| 2 | INGESTED queue depth > 10,000 rows | Add enrichment worker (+ 1 T-VEC instance, + 1 TSLAM-8B GPU sidecar or TSLAM-4B) | High |
| 3 | Cold store total rows > 5M (global) | Partition `cold_fragment` by tenant_id; add block volume storage | High |
| 4 | Enrichment p95 latency > 60s | Add enrichment workers | Medium |
| 5 | Tenant count > 50 | Enable parallel batch job execution for expiration and cluster eval | Medium |
| 6 | Hot store ANN p95 > 100ms | Rebuild IVFFlat with higher lists; add pgvector read replica | Medium |
| 7 | TSLAM p95 latency > 10s on GPU | Add vLLM GPU instance; load-balance TSLAMService | Medium |
| 8 | Expiration pass > 20 hours/day | Parallelise expiration to 10 tenants; review retention tiers | Medium |
| 9 | Per-tenant hot store > 2M fragments | Migrate hot store to HNSW (memory permitting) or add read replica | Low |
| 10 | events/sec > 1,000 sustained | Move enrichment to async queue; decouple from ingest path | Low (already async) |

### 8.3 Architecture Invariants That Cannot Be Scaled Horizontally Without Redesign

The following components are **not horizontally scalable** in the current v3.0 design. Scaling beyond
the stated limits requires redesign outside the scope of this document:

1. **Single PostgreSQL instance**: All fragment state, snap decisions, accumulation graph, cluster
   snapshots, and cold storage are on one PostgreSQL instance. The current design has no read replica,
   no sharding, and no external write coordinator. Read replicas for ANN queries are addable without
   redesign; write scaling requires partitioning or multi-primary.

2. **Single Kafka broker (KRaft)**: The `serving_architecture.md` specifies a single Kafka instance.
   At 100K events/sec, a single KRaft broker approaches its throughput ceiling (~100 MB/s sustained
   write, depending on message size). At ~1 KB/event, 100K events/sec = 100 MB/s. This is the
   single-broker ceiling.

3. **T-VEC singleton per process**: The `_tvec_model` is a process-global singleton protected by an
   `asyncio.Lock`. Multiple enrichment workers must be separate processes — the model cannot be shared
   across processes without a dedicated T-VEC serving API (e.g., a triton inference server or a T-VEC
   HTTP API sidecar).

4. **TSLAM one-directional fallback**: The `serving_architecture.md §4.1` specifies that once TSLAM
   falls back to llama-cpp, it does not auto-recover. At scale with multiple worker processes, each
   worker independently manages its own TSLAM state. A global health recovery signal (via Redis or
   a coordination endpoint) is needed to recover all workers simultaneously without a full restart.

---

## 9. Recommended Scaling Sequence

For a deployment growing from pilot to the stated targets, the recommended scaling sequence is:

**Phase 1 (0–10 tenants, ≤ 10K events/min)**
- Single App VM, single DB VM. Reference deployment as specified.
- Monitor INGESTED queue depth and enrichment lag. Expiration runs nightly.
- IVFFlat rebuild: sequential, no parallelism needed.

**Phase 2 (10–50 tenants, ≤ 100K events/min)**
- Add 2 enrichment workers (separate processes or containers). Each has its own T-VEC executor.
- Introduce parallel batch job execution: expiration and IVFFlat rebuild with 5-concurrent worker pool.
- Partition `cold_fragment` by tenant_id (declarative, 50 partitions initially).
- Upgrade DB VM to higher-RAM instance (24–48 GB) for shared_buffers growth.
- Consider PostgreSQL read replica for ANN-heavy query paths.

**Phase 3 (50–100 tenants, ≤ 1M events/min)**
- 5–10 enrichment workers. GPU sidecar per worker or shared GPU cluster (vLLM multi-model server).
- Parallelise all batch jobs to 10-tenant concurrency.
- Migrate T-VEC to a dedicated inference API (Triton or a T-VEC-specific FastAPI service).
- Distribute Kafka to 3+ brokers with partition replication.
- Evaluate TimescaleDB continuous aggregates for the expiration tier (compression policies replace manual tiering).
- Object storage (e.g., OCI Object Storage) for TOMBSTONED rows; PostgreSQL retains only ACTIVE + COMPRESSED.

**Phase 4 (> 100 tenants, > 1M events/min)**
- Out of scope for the v3.0 specification. Requires database sharding, multi-region deployment,
  and a dedicated vector database layer (Weaviate, Qdrant, or pgvector on distributed Postgres).

---

## 10. Assumptions and Caveats

1. **T-VEC throughput estimates** are derived from SentenceTransformer ARM CPU benchmarks for 1.5B
   parameter models. Actual throughput on Oracle Ampere Altra may differ by ±50%. **Benchmark on
   target hardware before sizing enrichment worker count.**

2. **TSLAM-8B throughput estimates** assume vLLM on a single consumer GPU (RTX 3090/4090 class or
   A10G). On Oracle Always Free (no GPU), the TSLAM-4B CPU fallback is the only path; throughput is
   ~0.067 fragments/sec. The 100K events/sec target is not achievable without GPU infrastructure.

3. **pgvector latency estimates** assume adequate `shared_buffers` (index working set cached in RAM).
   On a DB VM with 12 GB RAM allocated primarily to Postgres, the IVFFlat centroid data for 500K
   rows/tenant (10 tenants = 5M total) fits comfortably. Beyond that, disk I/O dominates.

4. **Accumulation graph post-fix** bounds are hard-coded: `MAX_CLUSTER_SIZE = 50`,
   `MAX_EDGES_PER_FRAGMENT = 20`, `MAX_CLUSTER_EDGES = 1,000`. Increasing these constants increases
   memory per cluster evaluation linearly and must be re-evaluated against VM RAM headroom.

5. **The 10K–100K events/sec target** from the requirements acceptance criteria likely refers to the
   ingest acceptance rate (raw events written to Kafka), not the enrichment processing rate. Ingest
   and enrichment are decoupled (async queue). Real-time enrichment at 100K events/sec is impossible
   on any single-GPU configuration with an 8B-parameter LLM.

---

*Document complete. Task T6.1 — Scalability Analysis output.*
