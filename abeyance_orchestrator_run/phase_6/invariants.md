# Abeyance Memory v3.0 -- Hard System Invariants (Definitive)

**Version:** 3.0
**Date:** 2026-03-16
**Scope:** Merged from LLD v2.0 invariants + all Phase 1-5 redesign invariants
**Status:** Normative. Every subsystem implementation MUST satisfy the invariants listed here.

---

## How to Read This Document

Each invariant has:
- **ID**: Stable identifier. v2.0 IDs preserved; new IDs use `INV-` prefix with numeric or subsystem-scoped suffixes.
- **Statement**: What must always be true.
- **Testable Assertion**: A concrete, automatable check.
- **Enforcing Subsystem(s)**: The code module(s) responsible.
- **Violation Consequence**: What breaks if the invariant is violated.
- **Lineage**: Whether inherited from v2.0, updated, or new in v3.0.

---

## Category 1: Fragment Lifecycle

### INV-1 -- Fragment State Machine Determinism
- **Statement:** Fragment lifecycle is a deterministic state machine: `INGESTED -> ACTIVE -> NEAR_MISS -> SNAPPED|STALE -> EXPIRED -> COLD`. Only transitions defined in `VALID_TRANSITIONS` are permitted.
- **Testable Assertion:** For every `(old_state, new_state)` pair in `fragment_history`, assert `(old_state, new_state) in VALID_TRANSITIONS`.
- **Enforcing Subsystem:** Fragment lifecycle layer, `SnapStatus` enum, application-layer `VALID_TRANSITIONS` dict.
- **Violation Consequence:** Fragments enter undefined states; decay, scoring, and cold-storage logic produce undefined behaviour.
- **Lineage:** v2.0 INV-1 -- preserved unchanged.

### INV-5 -- Irreversible Snaps
- **Statement:** Fragment joins (snaps) are irreversible except via explicit operator action. Once a fragment reaches `SNAPPED`, no automated process may transition it to any prior state.
- **Testable Assertion:** No row in `fragment_history` has `old_state = 'SNAPPED'` and `new_state NOT IN ('EXPIRED', 'COLD')` unless `event_type = 'OPERATOR_OVERRIDE'`.
- **Enforcing Subsystem:** SnapEngine, application-layer authorization.
- **Violation Consequence:** Snapped fragments re-enter evaluation, producing duplicate or contradictory incident correlations.
- **Lineage:** v2.0 INV-5 -- preserved unchanged.

### INV-6 -- Hard Fragment Bounds
- **Statement:** Every fragment has hard bounds: 730-day max lifetime, 64KB max `raw_content`, 90-day idle timeout.
- **Testable Assertion:** `SELECT count(*) FROM abeyance_fragment WHERE age(now(), created_at) > interval '730 days' AND status NOT IN ('EXPIRED','COLD') = 0`. `raw_content` length <= 65536 bytes. No fragment with `last_evaluated_at` older than 90 days in a non-terminal state.
- **Enforcing Subsystem:** DecayEngine, fragment validation, `max_lifetime_days` column default.
- **Violation Consequence:** Unbounded fragment accumulation; memory and storage growth without limit.
- **Lineage:** v2.0 INV-6 -- preserved unchanged.

---

## Category 2: Scoring and Arithmetic Bounds

### INV-2 -- Monotonic Decay
- **Statement:** Decay is strictly monotonic decreasing under constant conditions. `new_score <= old_score` for every decay pass. The near-miss boost factor is capped at `[1.0, 1.5]`.
- **Testable Assertion:** For every `DECAY_UPDATE` row in `fragment_history`: `new_score <= old_score`. Boost factor = `1.0 + min(near_miss_count, 10) * 0.05` is in `[1.0, 1.5]`.
- **Enforcing Subsystem:** DecayEngine, `min(computed_score, old_score)` defense-in-depth.
- **Violation Consequence:** Fragments gain energy over time, defeating the core memory-fade model. Stale signals persist indefinitely.
- **Lineage:** v2.0 INV-2 -- preserved; boost cap from ALG-2.1-1 merged.

### INV-3 -- Bounded Scoring Arithmetic
- **Statement:** All scoring arithmetic uses bounded domains. `raw_composite` in `[0.0, 1.0]`, `temporal_modifier` in `[0.5, 1.0]`, `snap_score = raw_composite * temporal_modifier` in `[0.0, 1.0]`.
- **Testable Assertion:** `_clamp()` applied to every per-dimension score and final composite. Unit test: any combination of valid inputs produces output in `[0.0, 1.0]`.
- **Enforcing Subsystem:** SnapEngine, AccumulationGraph, DecayEngine.
- **Violation Consequence:** Scores exceed 1.0 or go negative, breaking threshold comparisons and producing meaningless confidence values.
- **Lineage:** v2.0 INV-3 -- preserved unchanged.

### INV-8 -- Score Range Guarantee
- **Statement:** No scoring function produces output outside `[0.0, 1.0]`.
- **Testable Assertion:** Property-based test: for all scoring functions `f`, `0.0 <= f(*args) <= 1.0` across randomized input space.
- **Enforcing Subsystem:** SnapEngine, AccumulationGraph, DecayEngine -- `_clamp()` defense-in-depth.
- **Violation Consequence:** Downstream consumers (threshold logic, UI, provenance) receive garbage values.
- **Lineage:** v2.0 INV-8 -- preserved unchanged.

### INV-13 -- Multiple Comparisons Correction
- **Statement:** Sidak correction applied across K failure mode profiles: `adjusted_threshold = 1 - (1 - base_threshold)^(1/K)`.
- **Testable Assertion:** For K > 1, `adjusted_threshold > base_threshold`. For K=1, `adjusted_threshold == base_threshold`.
- **Enforcing Subsystem:** SnapEngine, Sidak correction logic.
- **Violation Consequence:** False positive rate inflated proportionally to the number of failure mode profiles evaluated.
- **Lineage:** v2.0 INV-13 -- preserved unchanged.

---

## Category 3: Embedding Validity and Mask Enforcement

### INV-11 -- Mathematically Valid Embeddings (UPDATED)
- **Statement:** Every similarity computation uses mathematically meaningful vectors. Embedding validity is tracked via per-column boolean masks (`mask_semantic`, `mask_topological`, `mask_operational`). `emb_temporal` has no mask (always valid). When a mask is `FALSE`, the corresponding embedding column is `NULL` and MUST NOT be used in any similarity computation.
- **Testable Assertion:** `SELECT count(*) FROM abeyance_fragment WHERE mask_semantic = FALSE AND emb_semantic IS NOT NULL = 0` (and analogous for topo, operational). No code path computes cosine similarity on a dimension whose mask is `FALSE`.
- **Enforcing Subsystem:** EnrichmentChain, ORM CHECK constraints, SnapEngine `available_d(A,B)` predicate.
- **Violation Consequence:** Similarity scores computed against NULL/garbage vectors produce random correlations. Hash-embedding fallback (the v1 bug) is the canonical example.
- **Lineage:** v2.0 INV-11 -- **updated** in Phase 1. JSONB mask array replaced with per-column booleans. CHECK constraints enforce mask/embedding coherence at DB level.

### INV-12-EMB -- NULL Embedding Semantics (NEW)
- **Statement:** `NULL` embedding = unknown. Zero-vector fill and hash fallback are prohibited. No code path may substitute a zero vector or a deterministic hash for a missing embedding.
- **Testable Assertion:** Codebase grep: no occurrence of `_hash_embedding`, no zero-fill of embedding columns. `SELECT count(*) FROM abeyance_fragment WHERE emb_semantic = array_fill(0, ARRAY[dim]) = 0`.
- **Enforcing Subsystem:** EnrichmentChain (structural enforcement -- no fallback code path exists), ORM schema.
- **Violation Consequence:** Silent corruption of similarity scores. The v1 hash-embedding bug (F-3.3) is reinstated.
- **Lineage:** **New in v3.0** (Phase 1 ORM schema INV-12, Phase 2 telemetry aligner INV-TA-5).

### INV-14 -- Mask/Embedding Coherence (NEW)
- **Statement:** CHECK constraints enforce that `mask_X = TRUE` implies `emb_X IS NOT NULL` and `mask_X = FALSE` implies `emb_X IS NULL`, for X in {semantic, topological, operational}.
- **Testable Assertion:** Attempt to INSERT a row with `mask_semantic = TRUE, emb_semantic = NULL` -- must fail with CHECK violation.
- **Enforcing Subsystem:** PostgreSQL CHECK constraints on `abeyance_fragment`.
- **Violation Consequence:** Mask says "valid" but embedding is missing, causing NullPointerException in scoring. Or mask says "invalid" but embedding is present, causing it to be silently ignored.
- **Lineage:** **New in v3.0** (Phase 1 ORM schema INV-13).

### INV-15 -- Snap Decision Dimensional Transparency (NEW)
- **Statement:** `snap_decision_record` stores five explicit per-dimension scores. A `NULL` score means the dimension was excluded from the comparison (mask was `FALSE` for one or both fragments).
- **Testable Assertion:** For every `snap_decision_record` row, if `score_semantic IS NOT NULL` then both fragments had `mask_semantic = TRUE` at evaluation time.
- **Enforcing Subsystem:** SnapEngine, `score_pair_v3()`.
- **Violation Consequence:** Audit trail cannot distinguish "dimension scored 0.0" from "dimension not evaluated", making forensic analysis impossible.
- **Lineage:** **New in v3.0** (Phase 1 ORM schema INV-14).

---

## Category 4: Scoring Weight Integrity (NEW)

### INV-16 -- Available Weight Sum Positive (NEW)
- **Statement:** The sum of weights for available dimensions is always > 0 during snap scoring. Temporal and entity_overlap dimensions are always available, guaranteeing a non-zero denominator.
- **Testable Assertion:** In `score_pair_v3()`, `sum(w_i for i in available_dims) > 0` before weight redistribution.
- **Enforcing Subsystem:** SnapEngine weight redistribution logic.
- **Violation Consequence:** Division by zero in weight redistribution, producing NaN scores.
- **Lineage:** **New in v3.0** (Phase 1 snap_scoring INV-NEW-1).

### INV-17 -- Adjusted Weights Sum to Unity (NEW)
- **Statement:** After redistribution for masked dimensions, the adjusted weights sum to exactly 1.0.
- **Testable Assertion:** `abs(sum(adjusted_weights) - 1.0) < 1e-9` for every evaluation.
- **Enforcing Subsystem:** SnapEngine weight redistribution formula.
- **Violation Consequence:** Composite score is no longer a proper weighted average; scores drift outside expected range despite individual components being in `[0.0, 1.0]`.
- **Lineage:** **New in v3.0** (Phase 1 snap_scoring INV-NEW-2).

### INV-18 -- No Cosine on NULL Embeddings (NEW)
- **Statement:** No cosine similarity computation is ever performed on a `NULL` embedding vector. The availability predicate prevents computation on unavailable dimensions.
- **Testable Assertion:** Code coverage: every call to cosine similarity is guarded by `available_d(A, B)` check. Integration test: fragments with `mask_semantic=FALSE` never produce a non-NULL `score_semantic` in `snap_decision_record`.
- **Enforcing Subsystem:** SnapEngine `available_d(A,B)` predicate.
- **Violation Consequence:** `cosine_similarity(NULL, vec)` raises exception or returns garbage.
- **Lineage:** **New in v3.0** (Phase 1 snap_scoring INV-NEW-3).

### INV-19 -- Strictly Positive Weights (NEW)
- **Statement:** Every failure mode profile weight must be strictly positive (> 0.0). Zero weights are prohibited; use a very small weight (e.g., 0.05) for structurally irrelevant dimensions.
- **Testable Assertion:** Schema validation on failure mode profile load: `all(w > 0.0 for w in profile.weights)`.
- **Enforcing Subsystem:** SnapEngine profile loader.
- **Violation Consequence:** Zero weight breaks the redistribution formula's proportionality guarantee. A dimension with weight 0 receives 0 redistributed weight, masking information loss.
- **Lineage:** **New in v3.0** (Phase 1 snap_scoring invariant on positive weights).

---

## Category 5: Tenant Isolation and Security

### INV-7 -- Tenant Isolation
- **Statement:** `tenant_id` is immutably bound at ingestion and verified at every cross-boundary operation. Every database table includes `tenant_id`. Every query filters by `tenant_id`. Cross-tenant operations are impossible by query construction.
- **Testable Assertion:** Codebase audit: every SQL query on abeyance tables includes `tenant_id` in WHERE clause. No API endpoint serves data without tenant context.
- **Enforcing Subsystem:** All query paths, fragment ingestion, all subsystems.
- **Violation Consequence:** Data leakage between tenants. Critical security violation.
- **Lineage:** v2.0 INV-7 -- preserved unchanged. Confirmed across all Phase 1-5 subsystems.

---

## Category 6: Resource Bounds and Growth Control

### INV-4 -- Monotonic Cluster Convergence
- **Statement:** Cluster membership is monotonic convergent. Edge weight updates only increase scores (`GREATEST()` at DB level). This prevents clustering oscillation.
- **Testable Assertion:** For every `UPDATE` to `accumulation_edge`, `new_affinity_score >= old_affinity_score` (enforced by `GREATEST()` in SQL).
- **Enforcing Subsystem:** AccumulationGraph, edge update logic, `GREATEST()` in UPDATE statement.
- **Violation Consequence:** Clustering oscillation; `cluster_snapshot` grows unboundedly; edge weights fluctuate, producing inconsistent incident groupings.
- **Lineage:** v2.0 INV-4 -- preserved unchanged.

### INV-9 -- Bounded Resource Growth
- **Statement:** Total resource growth per tenant is O(n) with fragment count. Hard caps: 20 edges per fragment, 50 members per cluster, 500 BFS expansion results, 200 snap candidates per evaluation, 10,000 decay batch size, 10,000 Redis stream length, < 500K active fragments per tenant.
- **Testable Assertion:** For each bound, query the relevant table and assert count <= limit.
- **Enforcing Subsystem:** AccumulationGraph (eviction policies), SnapEngine (LIMIT clauses), DecayEngine (batch size), ShadowTopology (BFS cap), RedisNotifier (MAXLEN).
- **Violation Consequence:** Quadratic or exponential resource consumption; query timeouts; OOM on evaluation paths.
- **Lineage:** v2.0 INV-9 -- preserved. Individual caps from RES-3.x merged into single invariant.

---

## Category 7: Provenance and Observability

### INV-10 -- Append-Only Provenance
- **Statement:** All provenance trails are append-only and tamper-evident. Tables: `fragment_history`, `snap_decision_record`, `cluster_snapshot`. No UPDATE or DELETE on these tables.
- **Testable Assertion:** PostgreSQL trigger or policy: any UPDATE/DELETE on provenance tables raises an error. Row count is monotonically non-decreasing.
- **Enforcing Subsystem:** ProvenanceLogger, database schema constraints.
- **Violation Consequence:** Audit trail is compromised; incident forensics become unreliable; regulatory compliance failure.
- **Lineage:** v2.0 INV-10 -- preserved unchanged.

### INV-12 -- State Rebuild from PostgreSQL
- **Statement:** Deterministic full state rebuild from PostgreSQL alone. Redis is best-effort notification only. Write-ahead pattern: (1) persist to PostgreSQL, (2) commit, (3) best-effort Redis notify. Consumers recover by querying PostgreSQL for events > `last_processed_timestamp`.
- **Testable Assertion:** Integration test: kill Redis, verify all state is recoverable from PostgreSQL. No recovery procedure depends on Redis or in-memory state.
- **Enforcing Subsystem:** Write-Ahead pattern, ProvenanceLogger, all event publishers.
- **Violation Consequence:** Redis failure causes data loss; system cannot recover to consistent state.
- **Lineage:** v2.0 INV-12 -- preserved unchanged.

---

## Category 8: Back-Pressure and Operational Safety

### INV-BP-1 -- Queue Saturation Back-Pressure
- **Statement:** `HIGH_WATER_MARK` (500 pending) returns HTTP 429. `CRITICAL_WATER_MARK` (2000 pending) opens circuit breaker for 30 seconds.
- **Testable Assertion:** Load test: push 501 events, verify 429 response. Push 2001, verify circuit breaker opens.
- **Enforcing Subsystem:** Event ingestion queue, circuit breaker.
- **Violation Consequence:** Unbounded queue growth; OOM; cascading failure to downstream systems.
- **Lineage:** v2.0 RES-3.4-1 -- promoted to hard invariant.

### INV-SERVE-1 -- No Blocking on Event Loop (NEW)
- **Statement:** No blocking call ever runs on the asyncio event loop. All I/O-bound and CPU-bound work is dispatched to thread/process pools.
- **Testable Assertion:** Code audit: no synchronous `requests`, `time.sleep`, or blocking DB calls on the event loop. Latency monitoring: p99 event loop lag < 10ms.
- **Enforcing Subsystem:** Serving architecture (FastAPI), `run_in_executor` wrappers.
- **Violation Consequence:** Event loop starvation; request timeouts cascade across all concurrent requests.
- **Lineage:** **New in v3.0** (Phase 1 serving_architecture).

---

## Category 9: Telemetry Aligner (NEW)

### INV-TA-1 -- No Hash-Based Vectors
- **Statement:** `embed_anomaly` never returns a hash-based vector under any execution path.
- **Testable Assertion:** Codebase grep: `_hash_embedding` does not exist. Unit test: all failure paths return `(None, False)`.
- **Enforcing Subsystem:** TelemetryAligner (`embed_anomaly`).
- **Violation Consequence:** Hash vectors produce random similarity scores, reinstating the v1 F-3.3 bug.
- **Lineage:** **New in v3.0** (Phase 2 telemetry_aligner_fix INV-TA-1, INV-TA-5).

### INV-TA-2 -- No Zero-Filled Vectors
- **Statement:** `embed_anomaly` never returns a zero-filled vector under any execution path.
- **Testable Assertion:** Unit test: all failure paths return `(None, False)`, never `(np.zeros(dim), False)`.
- **Enforcing Subsystem:** TelemetryAligner (`embed_anomaly`).
- **Violation Consequence:** Zero vectors produce cosine similarity of 0.0 or NaN with all other vectors, silently disabling the operational dimension.
- **Lineage:** **New in v3.0** (Phase 2 telemetry_aligner_fix INV-TA-2).

### INV-TA-3 -- Graceful T-VEC Unavailability
- **Statement:** `embed_anomaly` never raises an exception to its caller regardless of T-VEC state. Returns `(None, False)` when T-VEC is unavailable.
- **Testable Assertion:** Inject T-VEC failure; verify `embed_anomaly` returns `(None, False)` without exception.
- **Enforcing Subsystem:** TelemetryAligner, `try/except` with structured logging.
- **Violation Consequence:** Unhandled exception propagates to fragment ingestion, causing fragment loss.
- **Lineage:** **New in v3.0** (Phase 2 telemetry_aligner_fix INV-TA-3, INV-TA-4).

### INV-TA-4 -- Async Contract
- **Statement:** `embed_anomaly` is a coroutine (`async def`) and must be awaited by all callers.
- **Testable Assertion:** Static analysis: all call sites use `await embed_anomaly(...)`.
- **Enforcing Subsystem:** TelemetryAligner, Python type checker.
- **Violation Consequence:** Coroutine object returned instead of result; embedding silently missing.
- **Lineage:** **New in v3.0** (Phase 2 telemetry_aligner_fix INV-TA-6).

---

## Category 10: Negative Evidence and Disconfirmation (NEW)

### INV-NE-1 -- Disconfirmation Only Accelerates Decay
- **Statement:** Disconfirmation can only accelerate decay (reduce scores), never increase them. `apply_accelerated_decay()` enforces `new_score <= old_score`. Propagation penalties apply to transient snap scores, not stored decay scores.
- **Testable Assertion:** For every `ACCELERATED_DECAY` event in `fragment_history`, `new_score <= old_score`. Propagation penalty factor in `[PENALTY_FLOOR, 1.0] = [0.30, 1.0]`.
- **Enforcing Subsystem:** NegativeEvidenceProcessor, DecayEngine `apply_accelerated_decay()`.
- **Violation Consequence:** Disconfirmed fragments gain energy, contradicting operator feedback.
- **Lineage:** **New in v3.0** (Phase 3 negative_evidence, invariant analysis).

### INV-NE-2 -- Penalty Factor Bounded
- **Statement:** Propagation penalty factor is clamped to `[0.30, 1.0]`. Penalized snap scores remain in `[0.0, 1.0]`.
- **Testable Assertion:** `0.30 <= penalty_factor <= 1.0` for all evaluated propagation penalties.
- **Enforcing Subsystem:** NegativeEvidenceProcessor.
- **Violation Consequence:** Penalty factor below floor causes excessive suppression; above 1.0 causes amplification.
- **Lineage:** **New in v3.0** (Phase 3 negative_evidence INV-3/INV-8 analysis).

---

## Category 11: Surprise Engine (NEW)

### INV-S1 -- Surprise Value Bounded
- **Statement:** Surprise value in `[0.0, 20.0]` bits. Enforced by `min(-log2(...), 20.0)` cap and Laplace smoothing to prevent `-log2(0)`.
- **Testable Assertion:** For every `surprise_event` row, `0.0 <= surprise_value <= 20.0`.
- **Enforcing Subsystem:** SurpriseEngine.
- **Violation Consequence:** Infinite or NaN surprise values corrupt downstream priority queues.
- **Lineage:** **New in v3.0** (Phase 3 surprise_engine INV-S1).

### INV-S2 -- Minimum Data Threshold
- **Statement:** No surprise computation on insufficient data. `total_mass < MINIMUM_MASS` check returns `None`.
- **Testable Assertion:** Unit test: distribution with mass below threshold produces `None`, not a numeric surprise value.
- **Enforcing Subsystem:** SurpriseEngine.
- **Violation Consequence:** Surprise scores on sparse data are dominated by noise, generating false discoveries.
- **Lineage:** **New in v3.0** (Phase 3 surprise_engine INV-S2).

### INV-S3 -- Non-Negative Histogram Bins
- **Statement:** Histogram bin counts are always non-negative. Decay multiplies by positive alpha; Laplace adds positive pseudocount.
- **Testable Assertion:** `all(bin >= 0 for bin in histogram.bins)` after every update.
- **Enforcing Subsystem:** SurpriseEngine histogram management.
- **Violation Consequence:** Negative bin counts produce invalid probability distributions.
- **Lineage:** **New in v3.0** (Phase 3 surprise_engine INV-S3).

### INV-S4 -- Score-Before-Update Ordering
- **Statement:** Surprise is computed before the histogram is updated in `evaluate_surprise()`.
- **Testable Assertion:** Code audit: `compute_surprise()` call precedes `update_histogram()` call.
- **Enforcing Subsystem:** SurpriseEngine `evaluate_surprise()`.
- **Violation Consequence:** Current observation is included in the "expected" distribution, diluting surprise and missing anomalies.
- **Lineage:** **New in v3.0** (Phase 3 surprise_engine INV-S4).

### INV-S5 -- Surprise Tenant Isolation
- **Statement:** `tenant_id` in primary key of distribution state; leading column in all surprise_event indexes.
- **Testable Assertion:** Schema check: `tenant_id` is part of PK for `surprise_distribution_state` and leading index column for `surprise_event`.
- **Enforcing Subsystem:** SurpriseEngine, PostgreSQL schema.
- **Violation Consequence:** Cross-tenant surprise contamination.
- **Lineage:** **New in v3.0** (Phase 3 surprise_engine INV-S5). Reinforces INV-7.

### INV-S6 -- Effective Threshold Floor
- **Statement:** Effective surprise threshold >= `DEFAULT_THRESHOLD`. `max(compute_surprise_threshold(...), DEFAULT_THRESHOLD)`.
- **Testable Assertion:** For all threshold computations, `effective_threshold >= DEFAULT_THRESHOLD`.
- **Enforcing Subsystem:** SurpriseEngine threshold logic.
- **Violation Consequence:** Threshold drops to zero, causing every observation to trigger a surprise event.
- **Lineage:** **New in v3.0** (Phase 3 surprise_engine INV-S6).

### INV-S7 -- Surprise Events Persisted Before Enqueue
- **Statement:** `persist_surprise_event()` called before queue insertion. Event survives queue drop.
- **Testable Assertion:** Code audit: `persist_surprise_event()` precedes `enqueue_for_discovery()`. Integration test: kill queue after persist, verify event in DB.
- **Enforcing Subsystem:** SurpriseEngine.
- **Violation Consequence:** Queue failure causes surprise event loss; downstream discovery engine has no input.
- **Lineage:** **New in v3.0** (Phase 3 surprise_engine INV-S7).

### INV-S8 -- No Mutation of Snap Decisions
- **Statement:** SurpriseEngine reads `SnapDecisionRecord`; no write path to `snap_decision_log`.
- **Testable Assertion:** Code audit: SurpriseEngine has no INSERT/UPDATE on `snap_decision_log`.
- **Enforcing Subsystem:** SurpriseEngine (read-only consumer).
- **Violation Consequence:** Surprise evaluation corrupts snap provenance trail, violating INV-10.
- **Lineage:** **New in v3.0** (Phase 3 surprise_engine INV-S8).

---

## Category 12: Bridge Detection (NEW)

### INV-BD-1 -- No Independent DB Edge Loading
- **Statement:** Bridge detection never loads edges from DB independently. `analyze_component()` accepts `component_edges` parameter only.
- **Testable Assertion:** Code audit: `BridgeDetector` has no direct SQL query for edges.
- **Enforcing Subsystem:** BridgeDetector API contract.
- **Violation Consequence:** Bridge detection uses stale or inconsistent edge data, producing phantom bridges.
- **Lineage:** **New in v3.0** (Phase 3 bridge_detection BD-INV-1).

### INV-BD-2 -- Bridge Detection Tenant Scoped
- **Statement:** All DB operations in bridge detection are tenant-scoped.
- **Testable Assertion:** Every query includes `tenant_id = :tenant_id`.
- **Enforcing Subsystem:** BridgeDetector, query construction.
- **Violation Consequence:** Cross-tenant bridge discovery. Reinforces INV-7.
- **Lineage:** **New in v3.0** (Phase 3 bridge_detection BD-INV-2).

### INV-BD-3 -- Discovery Record Idempotency
- **Statement:** Bridge discovery record is idempotent for stable topology. Enforced by `UNIQUE (tenant_id, bridge_fragment_id, component_fingerprint)`.
- **Testable Assertion:** Duplicate insert with same fingerprint raises UNIQUE violation.
- **Enforcing Subsystem:** PostgreSQL UNIQUE constraint on `bridge_discovery`.
- **Violation Consequence:** Duplicate bridge discovery records inflate bridge significance metrics.
- **Lineage:** **New in v3.0** (Phase 3 bridge_detection BD-INV-3).

### INV-BD-4 -- Betweenness Centrality Normalized
- **Statement:** `betweenness_centrality` is normalized to `[0.0, 1.0]`. Division by `(V-1)(V-2)/2` in Brandes algorithm; clamped to 0.0 if V < 3.
- **Testable Assertion:** For every `bridge_discovery` row, `0.0 <= betweenness_centrality <= 1.0`.
- **Enforcing Subsystem:** BridgeDetector Brandes implementation.
- **Violation Consequence:** Unnormalized centrality breaks threshold comparisons across different-sized components.
- **Lineage:** **New in v3.0** (Phase 3 bridge_detection BD-INV-4).

---

## Category 13: Hypothesis Engine (NEW)

### INV-H1 -- Hypothesis Confidence Bounded
- **Statement:** Hypothesis confidence in `[0.0, 1.0]`. Enforced by `clamp()` on every confidence update and CHECK constraint in schema.
- **Testable Assertion:** `SELECT count(*) FROM hypothesis WHERE confidence < 0.0 OR confidence > 1.0 = 0`. Attempt INSERT with confidence 1.5 fails.
- **Enforcing Subsystem:** HypothesisEngine, PostgreSQL CHECK constraint.
- **Violation Consequence:** Confidence values outside range break UI display, threshold logic, and meta-memory calculations.
- **Lineage:** **New in v3.0** (Phase 5 hypothesis_engine INV-H1).

### INV-H2 -- No Backward Hypothesis Transitions
- **Statement:** Hypothesis status transitions are forward-only. `evaluate_transitions()` only allows forward transitions. CHECK constraint prevents direct UPDATE to prior status.
- **Testable Assertion:** For every status change in `status_history`, the new status ordinal > old status ordinal.
- **Enforcing Subsystem:** HypothesisEngine `evaluate_transitions()`, PostgreSQL CHECK constraint.
- **Violation Consequence:** Confirmed hypotheses revert to tentative, undermining operator trust.
- **Lineage:** **New in v3.0** (Phase 5 hypothesis_engine INV-H2).

### INV-H3 -- Hypothesis Tenant Isolation
- **Statement:** `tenant_id` in all table PKs/indexes; all queries filtered by tenant.
- **Testable Assertion:** Schema audit: `tenant_id` in PK for all hypothesis tables. Query audit: all queries include tenant filter.
- **Enforcing Subsystem:** HypothesisEngine, PostgreSQL schema. Reinforces INV-7.
- **Violation Consequence:** Cross-tenant hypothesis leakage.
- **Lineage:** **New in v3.0** (Phase 5 hypothesis_engine INV-H3).

### INV-H4 -- Hypothesis Generation Provenance
- **Statement:** Every hypothesis has generation provenance: `generation_trigger`, `generation_method` are NOT NULL.
- **Testable Assertion:** `SELECT count(*) FROM hypothesis WHERE generation_trigger IS NULL OR generation_method IS NULL = 0`.
- **Enforcing Subsystem:** HypothesisEngine, NOT NULL constraints.
- **Violation Consequence:** Cannot trace why a hypothesis was generated; forensic analysis blocked.
- **Lineage:** **New in v3.0** (Phase 5 hypothesis_engine INV-H4).

### INV-H5 -- Evidence Linked to Hypothesis
- **Statement:** Every evidence record linked to a hypothesis via `hypothesis_id` FK NOT NULL.
- **Testable Assertion:** FK constraint enforced at DB level. No orphaned evidence rows.
- **Enforcing Subsystem:** PostgreSQL FK constraint on `hypothesis_evidence`.
- **Violation Consequence:** Orphaned evidence records; hypothesis confidence computation uses wrong evidence set.
- **Lineage:** **New in v3.0** (Phase 5 hypothesis_engine INV-H5).

### INV-H6 -- No Duplicate Evidence Sources
- **Statement:** No duplicate evidence from same source. UNIQUE index on `(hypothesis_id, source_id, evidence_type)`.
- **Testable Assertion:** Duplicate insert fails with UNIQUE violation.
- **Enforcing Subsystem:** PostgreSQL UNIQUE index.
- **Violation Consequence:** Same evidence counted multiple times inflates hypothesis confidence.
- **Lineage:** **New in v3.0** (Phase 5 hypothesis_engine INV-H6).

### INV-H7 -- TSLAM Unavailability Tolerance
- **Statement:** TSLAM unavailability does not block hypothesis creation. Template fallback guarantees hypothesis creation even without TSLAM.
- **Testable Assertion:** Integration test: disable TSLAM, trigger hypothesis generation, verify hypothesis created with `generation_method='TEMPLATE_FALLBACK'`.
- **Enforcing Subsystem:** HypothesisEngine template fallback path.
- **Violation Consequence:** TSLAM outage blocks all hypothesis generation, defeating the purpose of abeyance memory.
- **Lineage:** **New in v3.0** (Phase 5 hypothesis_engine INV-H7).

### INV-H8 -- All Status Transitions Logged
- **Statement:** `status_history` JSONB updated on every transition in `evaluate_transitions()`.
- **Testable Assertion:** For every hypothesis with N status changes, `len(status_history) == N`.
- **Enforcing Subsystem:** HypothesisEngine `evaluate_transitions()`.
- **Violation Consequence:** Status transition history lost; cannot audit hypothesis lifecycle.
- **Lineage:** **New in v3.0** (Phase 5 hypothesis_engine INV-H8).

### INV-H9 -- All Confidence Changes Logged
- **Statement:** `confidence_history` JSONB updated on every evidence attachment and decay tick.
- **Testable Assertion:** For every confidence-changing event, a corresponding entry exists in `confidence_history`.
- **Enforcing Subsystem:** HypothesisEngine.
- **Violation Consequence:** Confidence audit trail lost; cannot explain why a hypothesis was promoted or demoted.
- **Lineage:** **New in v3.0** (Phase 5 hypothesis_engine INV-H9).

### INV-H10 -- Generation Queue Persistence
- **Statement:** `hypothesis_generation_queue` table persists pending requests. Worker recovers on startup.
- **Testable Assertion:** Kill worker mid-generation, restart, verify pending request is reprocessed.
- **Enforcing Subsystem:** HypothesisEngine queue, PostgreSQL persistence.
- **Violation Consequence:** Process crash loses pending generation requests; hypotheses never created for qualifying clusters.
- **Lineage:** **New in v3.0** (Phase 5 hypothesis_engine INV-H10).

---

## Category 14: Meta-Memory (NEW)

### INV-MM-1 -- Allocation Sums to Unity
- **Statement:** Allocation sums to 1.0 across all areas for an active tenant. Re-normalization step in bias algorithm enforces this.
- **Testable Assertion:** `abs(SUM(allocation_final) - 1.0) < 1e-9` for each active tenant in `meta_memory_bias`.
- **Enforcing Subsystem:** MetaMemoryEngine bias algorithm.
- **Violation Consequence:** Resources over- or under-allocated; some areas starved, others bloated.
- **Lineage:** **New in v3.0** (Phase 5 meta_memory INV-MM-1).

### INV-MM-2 -- Minimum Floor Guarantee
- **Statement:** No area allocation below `min_floor`. `max(min_floor, allocation_raw)` in bias algorithm.
- **Testable Assertion:** For every row in `meta_memory_bias`, `allocation_final >= min_floor`.
- **Enforcing Subsystem:** MetaMemoryEngine bias algorithm.
- **Violation Consequence:** An area with floor=0 receives no resources; system cannot detect problems in that area.
- **Lineage:** **New in v3.0** (Phase 5 meta_memory INV-MM-2).

### INV-MM-3 -- Inactive When Insufficient Outcomes
- **Statement:** Meta-memory is fully inactive when outcome threshold not met. `activation_status = 'INACTIVE'`; no rows in `meta_memory_bias` for INACTIVE tenants.
- **Testable Assertion:** For tenants with < threshold labeled outcomes, `meta_memory_tenant_state.activation_status = 'INACTIVE'` and `SELECT count(*) FROM meta_memory_bias WHERE tenant_id = :tid = 0`.
- **Enforcing Subsystem:** MetaMemoryEngine activation gate.
- **Violation Consequence:** Meta-memory operates on insufficient data, producing noise-driven allocation.
- **Lineage:** **New in v3.0** (Phase 5 meta_memory INV-MM-3).

### INV-MM-4 -- Volume Not a Productivity Proxy
- **Statement:** Volume is never used as a productivity proxy. The algorithm only reads from `snap_outcome_feedback` (labeled outcomes), not from `snap_decision_record` alone.
- **Testable Assertion:** Code audit: no query from `snap_decision_record` without join to outcome labels in meta-memory code paths.
- **Enforcing Subsystem:** MetaMemoryEngine.
- **Violation Consequence:** High-volume areas that produce many low-quality snaps get rewarded with more resources, creating a positive feedback loop.
- **Lineage:** **New in v3.0** (Phase 5 meta_memory INV-MM-4).

### INV-MM-5 -- Smoothed Productivity Bounded
- **Statement:** `P_smoothed` in `[0.0, 1.0]`. CHECK constraint on `meta_memory_productivity.p_smoothed`.
- **Testable Assertion:** INSERT with `p_smoothed = 1.5` fails with CHECK violation.
- **Enforcing Subsystem:** PostgreSQL CHECK constraint.
- **Violation Consequence:** Unbounded productivity scores corrupt allocation calculation.
- **Lineage:** **New in v3.0** (Phase 5 meta_memory INV-MM-5).

### INV-MM-6 -- Non-Negative Allocation
- **Statement:** All allocation values are non-negative and sum to 1.0. CHECK constraints on `meta_memory_bias.allocation_final`.
- **Testable Assertion:** `allocation_final >= 0` for all rows. Sum = 1.0 per tenant.
- **Enforcing Subsystem:** PostgreSQL CHECK constraints, normalization in algorithm.
- **Violation Consequence:** Negative allocation is meaningless and causes undefined behaviour in resource distribution.
- **Lineage:** **New in v3.0** (Phase 5 meta_memory INV-MM-6).

### INV-MM-7 -- UNLOCATED Region Excluded
- **Statement:** UNLOCATED region excluded from bias calculation normalization set. Scored but not included in the normalization denominator.
- **Testable Assertion:** UNLOCATED area has `allocation_final` but is not in the set used to compute normalization factor.
- **Enforcing Subsystem:** MetaMemoryEngine Section 8.2 Step 4.
- **Violation Consequence:** UNLOCATED fragments (which cannot be improved by topology awareness) steal allocation from locatable areas.
- **Lineage:** **New in v3.0** (Phase 5 meta_memory INV-MM-7).

---

## Category 15: Causal Direction (NEW)

### INV-20 -- Positive Mean Lag
- **Statement:** Every `causal_candidate` row has `mean_lag_seconds > 0` (direction orientation enforced at application layer).
- **Testable Assertion:** `SELECT count(*) FROM causal_candidate WHERE mean_lag_seconds <= 0 = 0`.
- **Enforcing Subsystem:** CausalDirectionEngine, application-layer validation.
- **Violation Consequence:** Zero or negative lag means cause and effect are simultaneous or reversed, making the direction claim meaningless.
- **Lineage:** **New in v3.0** (Phase 5 causal_direction INV-20).

### INV-21 -- Minimum Sample Size
- **Statement:** Every `causal_candidate` row has `sample_size >= N_min` (N_min=15).
- **Testable Assertion:** `SELECT count(*) FROM causal_candidate WHERE sample_size < 15 = 0`.
- **Enforcing Subsystem:** CausalDirectionEngine, application-layer validation.
- **Violation Consequence:** Causal claims on < 15 observations are statistically meaningless.
- **Lineage:** **New in v3.0** (Phase 5 causal_direction INV-21).

### INV-22 -- Evidence Pair FK Integrity
- **Statement:** Every `causal_evidence_pair` row references a valid `causal_candidate.id` (FK with CASCADE).
- **Testable Assertion:** FK constraint enforced at DB level. No orphaned evidence pairs.
- **Enforcing Subsystem:** PostgreSQL FK constraint.
- **Violation Consequence:** Orphaned evidence pairs; candidate deletion leaves dangling references.
- **Lineage:** **New in v3.0** (Phase 5 causal_direction INV-22).

### INV-23 -- No Self-Causation
- **Statement:** `entity_a_id != entity_b_id`. CHECK constraint prevents an entity from being its own causal candidate.
- **Testable Assertion:** INSERT with `entity_a_id = entity_b_id` fails with CHECK violation.
- **Enforcing Subsystem:** PostgreSQL CHECK constraint.
- **Violation Consequence:** Self-referential causal loops with perfect temporal correlation pollute the causal graph.
- **Lineage:** **New in v3.0** (Phase 5 causal_direction INV-23).

### INV-24 -- Single Active Candidate Per Pair
- **Statement:** At most one `is_current = TRUE` record per `(tenant_id, entity_a_id, entity_b_id)` at any time. Enforced by supersession protocol; optional unique partial index.
- **Testable Assertion:** `SELECT tenant_id, entity_a_id, entity_b_id, count(*) FROM causal_candidate WHERE is_current = TRUE GROUP BY 1,2,3 HAVING count(*) > 1` returns 0 rows.
- **Enforcing Subsystem:** CausalDirectionEngine supersession protocol.
- **Violation Consequence:** Conflicting causal claims for the same entity pair; UI shows contradictory information.
- **Lineage:** **New in v3.0** (Phase 5 causal_direction INV-24).

### INV-25 -- Candidates Not Facts
- **Statement:** Temporal precedence findings are labelled as causal candidates, never as causal facts. The `confidence_label` encodes statistical strength, not probability of causation.
- **Testable Assertion:** No column named `is_causal_fact` or `causation_confirmed` exists. `confidence_label` values are statistical terms (e.g., STRONG, MODERATE, WEAK).
- **Enforcing Subsystem:** CausalDirectionEngine, schema design.
- **Violation Consequence:** System overclaims causation from correlation, leading to incorrect operator actions.
- **Lineage:** **New in v3.0** (Phase 5 causal_direction INV-25).

---

## Category 16: Evolutionary Patterns (NEW)

### INV-EV1 -- Fitness Bounded
- **Statement:** `f(I)` in `[0.0, 1.0]` for all individuals. Each component in `[0.0, 1.0]`; weights sum to 1.0.
- **Testable Assertion:** For every `pattern_individual` row, `0.0 <= fitness_score <= 1.0`.
- **Enforcing Subsystem:** EvolutionaryPatternEngine fitness computation.
- **Violation Consequence:** Fitness values outside range break selection and ranking algorithms.
- **Lineage:** **New in v3.0** (Phase 5 evolutionary_patterns INV-EV1).

### INV-EV2 -- Population Cap Enforced
- **Statement:** `|population| <= POP_CAP` at end of every generation cycle.
- **Testable Assertion:** `SELECT count(*) FROM pattern_individual WHERE tenant_id = :tid AND is_active = TRUE <= POP_CAP`.
- **Enforcing Subsystem:** EvolutionaryPatternEngine selection logic.
- **Violation Consequence:** Unbounded population growth; O(n^2) evaluation cost.
- **Lineage:** **New in v3.0** (Phase 5 evolutionary_patterns INV-EV2).

### INV-EV3 -- Archive Immutability
- **Statement:** Archived individuals are never deleted. All culls write to `pattern_individual_archive`.
- **Testable Assertion:** No DELETE on `pattern_individual_archive`. Row count is monotonically non-decreasing.
- **Enforcing Subsystem:** EvolutionaryPatternEngine cull logic.
- **Violation Consequence:** Historical pattern lineage lost; cannot trace evolutionary path of current patterns.
- **Lineage:** **New in v3.0** (Phase 5 evolutionary_patterns INV-EV3).

### INV-EV4 -- Genotype Uniqueness in Active Population
- **Statement:** No individual with a genotype already in the active population is admitted.
- **Testable Assertion:** UNIQUE constraint or application-level check on genotype hash for active individuals.
- **Enforcing Subsystem:** EvolutionaryPatternEngine admission gate.
- **Violation Consequence:** Duplicate genotypes waste population slots and bias selection.
- **Lineage:** **New in v3.0** (Phase 5 evolutionary_patterns INV-EV4).

### INV-EV5 -- Archive Genotype Block
- **Statement:** No individual with a genotype in the archive is admitted via mutation or recombination.
- **Testable Assertion:** Mutation/recombination output genotype checked against archive before admission.
- **Enforcing Subsystem:** EvolutionaryPatternEngine admission gate.
- **Violation Consequence:** Previously-culled ineffective patterns re-enter population, wasting evaluation cycles.
- **Lineage:** **New in v3.0** (Phase 5 evolutionary_patterns INV-EV5).

### INV-EV6 -- Recombination Child Specificity
- **Statement:** Recombination child specificity >= 1. Discard child if `specificity == 0` before admission.
- **Testable Assertion:** No `pattern_individual` with `specificity = 0` in active population.
- **Enforcing Subsystem:** EvolutionaryPatternEngine recombination logic.
- **Violation Consequence:** Zero-specificity pattern matches everything, providing no discriminative value.
- **Lineage:** **New in v3.0** (Phase 5 evolutionary_patterns INV-EV6).

### INV-EV7 -- Atomic Fitness Computation
- **Statement:** All four fitness components computed before fitness score is written. No partial writes.
- **Testable Assertion:** Code audit: fitness score assignment occurs after all four component computations.
- **Enforcing Subsystem:** EvolutionaryPatternEngine generation cycle.
- **Violation Consequence:** Partial fitness scores produce incorrect selection decisions.
- **Lineage:** **New in v3.0** (Phase 5 evolutionary_patterns INV-EV7).

### INV-EV8 -- Generation Skip on Insufficient Prerequisites
- **Statement:** Generation cycle skipped (not degraded) if >= 2 prerequisites are INSUFFICIENT.
- **Testable Assertion:** When >= 2 prerequisites report INSUFFICIENT, `generation_status = 'SKIPPED'`.
- **Enforcing Subsystem:** EvolutionaryPatternEngine prerequisite check.
- **Violation Consequence:** Running evolution on insufficient data produces random patterns that pollute the population.
- **Lineage:** **New in v3.0** (Phase 5 evolutionary_patterns INV-EV8).

### INV-EV9 -- Evolutionary Pattern Tenant Isolation
- **Statement:** `tenant_id` in WHERE clause for all queries; leading column in all PKs and indexes.
- **Testable Assertion:** Schema and query audit.
- **Enforcing Subsystem:** EvolutionaryPatternEngine. Reinforces INV-7.
- **Violation Consequence:** Cross-tenant pattern contamination.
- **Lineage:** **New in v3.0** (Phase 5 evolutionary_patterns INV-EV9).

### INV-EV10 -- Fitness Trajectory Append-Only
- **Statement:** `fitness_trajectory` is append-only per individual. No in-place modification of historical fitness values.
- **Testable Assertion:** No UPDATE on `fitness_trajectory` column that reduces array length.
- **Enforcing Subsystem:** EvolutionaryPatternEngine.
- **Violation Consequence:** Historical fitness trend analysis produces incorrect results.
- **Lineage:** **New in v3.0** (Phase 5 evolutionary_patterns INV-EV10).

### INV-EV11 -- Elite Protection
- **Statement:** Elite individuals (fitness >= ELITE_THRESHOLD) are never culled in the same generation they achieved elite status.
- **Testable Assertion:** No individual with `fitness >= ELITE_THRESHOLD` and `elite_since = current_generation` appears in cull list.
- **Enforcing Subsystem:** EvolutionaryPatternEngine selection algorithm.
- **Violation Consequence:** Newly-elite individuals culled before they can influence the next generation; evolution loses its best discoveries.
- **Lineage:** **New in v3.0** (Phase 5 evolutionary_patterns INV-EV11).

---

## Category 17: Counterfactual Simulation (NEW)

### INV-CF-1 -- Production Tables Read-Only
- **Statement:** No production table is modified during simulation. `abeyance_fragment`, `snap_decision_log`, `entity_sequence_log`, `transition_matrix` are read-only during counterfactual runs.
- **Testable Assertion:** Simulation DB session has no UPDATE/DELETE grants on production tables.
- **Enforcing Subsystem:** CounterfactualSimulator, read-only DB session.
- **Violation Consequence:** Simulation side-effects corrupt production state.
- **Lineage:** **New in v3.0** (Phase 5 counterfactual_simulation INV-CF-1).

### INV-CF-2 -- Forward Replay Window
- **Statement:** Replay window is always forward from `F_c.event_timestamp`. `T_start = F_c.event_timestamp`, `T_end > T_start`.
- **Testable Assertion:** For every simulation, `T_end > T_start >= F_c.event_timestamp`.
- **Enforcing Subsystem:** CounterfactualSimulator queue entry creation.
- **Violation Consequence:** Backward replay window produces time-travel artifacts in causal analysis.
- **Lineage:** **New in v3.0** (Phase 5 counterfactual_simulation INV-CF-2).

### INV-CF-3 -- Pair Count Bounded
- **Statement:** `replayed_pair_count <= max_pairs_per_candidate`. Hard truncation before scoring phase.
- **Testable Assertion:** For every simulation result, `replayed_pair_count <= max_pairs_per_candidate`.
- **Enforcing Subsystem:** CounterfactualSimulator.
- **Violation Consequence:** Unbounded pair replay causes simulation to run for hours on high-connectivity fragments.
- **Lineage:** **New in v3.0** (Phase 5 counterfactual_simulation INV-CF-3).

### INV-CF-4 -- Scoring Determinism
- **Statement:** Baseline score read from `snap_decision_log` equals what `score_pair_v3` would produce for the same inputs.
- **Testable Assertion:** For a sample of historical snaps, `abs(stored_score - recomputed_score) < 1e-6`.
- **Enforcing Subsystem:** SnapEngine `score_pair_v3()` determinism.
- **Violation Consequence:** Counterfactual delta is contaminated by scoring non-determinism, not by the removed fragment's actual impact.
- **Lineage:** **New in v3.0** (Phase 5 counterfactual_simulation INV-CF-4).

### INV-CF-5 -- Impact Scores Bounded
- **Statement:** `causal_impact_score`, `causal_impact_positive`, `causal_impact_negative` all in `[0.0, 1.0]`.
- **Testable Assertion:** CHECK constraints on `counterfactual_simulation_result` columns.
- **Enforcing Subsystem:** CounterfactualSimulator, PostgreSQL CHECK constraints.
- **Violation Consequence:** Unbounded impact scores break ranking and prioritization logic.
- **Lineage:** **New in v3.0** (Phase 5 counterfactual_simulation INV-CF-5).

### INV-CF-6 -- Pair Delta FK Integrity
- **Statement:** Every `counterfactual_pair_delta` row traces to exactly one `counterfactual_simulation_result` (FK with CASCADE).
- **Testable Assertion:** FK constraint enforced at DB level.
- **Enforcing Subsystem:** PostgreSQL FK constraint.
- **Violation Consequence:** Orphaned delta rows after result deletion.
- **Lineage:** **New in v3.0** (Phase 5 counterfactual_simulation INV-CF-6).

### INV-CF-7 -- Atomic Candidate Processing
- **Statement:** Batch job processes candidates atomically via `SELECT FOR UPDATE SKIP LOCKED`. No candidate processed by two concurrent job instances.
- **Testable Assertion:** Run two concurrent job instances; verify no candidate appears in both execution logs.
- **Enforcing Subsystem:** PostgreSQL row-level locking.
- **Violation Consequence:** Duplicate simulation results; wasted compute; potential data corruption from concurrent writes.
- **Lineage:** **New in v3.0** (Phase 5 counterfactual_simulation INV-CF-7).

### INV-CF-8 -- Job Duration Bounded
- **Statement:** Job duration bounded to 4 hours. Wall-clock check between candidates.
- **Testable Assertion:** Job logs show termination within 4 hours + epsilon.
- **Enforcing Subsystem:** CounterfactualSimulator wall-clock check.
- **Violation Consequence:** Runaway simulation job consumes compute indefinitely.
- **Lineage:** **New in v3.0** (Phase 5 counterfactual_simulation INV-CF-8).

---

## Category 18: Expectation Violation (NEW)

### INV-V1 -- Severity Bounded
- **Statement:** Severity value in `[0.0, 20.0]` bits. `min(-log2(...), SEVERITY_CAP)` + Laplace smoothing prevents `-log2(0)`.
- **Testable Assertion:** For every `expectation_violation` row, `0.0 <= severity_bits <= 20.0`.
- **Enforcing Subsystem:** ExpectationViolationDetector.
- **Violation Consequence:** Infinite severity corrupts priority queues and alerting thresholds.
- **Lineage:** **New in v3.0** (Phase 5 expectation_violation INV-V1).

### INV-V2 -- Minimum Matrix Confidence
- **Statement:** No violation evaluation on matrices with `total_from_count < 20`. Confidence gate rejects INSUFFICIENT and LOW_CONFIDENCE.
- **Testable Assertion:** No `expectation_violation` row references a matrix with `total_from_count < 20`.
- **Enforcing Subsystem:** ExpectationViolationDetector confidence gate.
- **Violation Consequence:** Violations detected against sparse matrices are noise, not signal.
- **Lineage:** **New in v3.0** (Phase 5 expectation_violation INV-V2).

### INV-V3 -- Laplace Smoothing Positive
- **Statement:** Laplace-smoothed probability is always > 0. `alpha=1` ensures numerator >= 1.
- **Testable Assertion:** `P_smoothed(to | from) > 0` for all state pairs.
- **Enforcing Subsystem:** ExpectationViolationDetector.
- **Violation Consequence:** Zero probability causes `-log2(0) = infinity`.
- **Lineage:** **New in v3.0** (Phase 5 expectation_violation INV-V3).

### INV-V4 -- Matrix Version Captured
- **Statement:** Every violation record contains the `matrix_version` used at evaluation time. Set at read time, stored immutably.
- **Testable Assertion:** `SELECT count(*) FROM expectation_violation WHERE matrix_version IS NULL = 0`.
- **Enforcing Subsystem:** ExpectationViolationDetector.
- **Violation Consequence:** Cannot determine which matrix version produced a violation; forensic replay impossible.
- **Lineage:** **New in v3.0** (Phase 5 expectation_violation INV-V4).

### INV-V5 -- Violation Tenant Isolation
- **Statement:** `tenant_id` present and leading in all indexes; all queries scoped by tenant.
- **Testable Assertion:** Schema and query audit.
- **Enforcing Subsystem:** ExpectationViolationDetector. Reinforces INV-7.
- **Violation Consequence:** Cross-tenant violation leakage.
- **Lineage:** **New in v3.0** (Phase 5 expectation_violation INV-V5).

### INV-V6 -- Read-Only Matrix Consumer
- **Statement:** Violation detector never mutates `transition_matrix`. Read-only consumer of matrix data.
- **Testable Assertion:** Code audit: no INSERT/UPDATE/DELETE on `transition_matrix` in violation detector code paths.
- **Enforcing Subsystem:** ExpectationViolationDetector (read-only consumer).
- **Violation Consequence:** Violation detection corrupts the transition matrices it depends on.
- **Lineage:** **New in v3.0** (Phase 5 expectation_violation INV-V6).

### INV-V7 -- Persist Before Enqueue
- **Statement:** All violation records persisted before enqueue. `persist_violation()` called before `enqueue_for_discovery()`.
- **Testable Assertion:** Code audit: persist call precedes enqueue call. Integration test: kill queue after persist, verify violation in DB.
- **Enforcing Subsystem:** ExpectationViolationDetector.
- **Violation Consequence:** Queue failure causes violation loss.
- **Lineage:** **New in v3.0** (Phase 5 expectation_violation INV-V7).

---

## Category 19: Pattern Compression (NEW)

### INV-C1 -- Compression Gain Bounded
- **Statement:** `compression_gain` in `[0.0, 1.0]`. Both component ratios are in `[0.0, 1.0]` by construction.
- **Testable Assertion:** For every compression result, `0.0 <= compression_gain <= 1.0`.
- **Enforcing Subsystem:** PatternCompressionEngine.
- **Violation Consequence:** Compression gain > 1.0 is meaningless; < 0.0 implies data expansion.
- **Lineage:** **New in v3.0** (Phase 5 pattern_compression INV-C1).

### INV-C2 -- Minimum Rule Coverage
- **Statement:** Every rule covers at least `MIN_COVERAGE` patterns. Candidate filter in greedy selection.
- **Testable Assertion:** For every `compression_rule`, `coverage_count >= MIN_COVERAGE`.
- **Enforcing Subsystem:** PatternCompressionEngine candidate filter.
- **Violation Consequence:** Rules covering 1-2 patterns are overfitting noise.
- **Lineage:** **New in v3.0** (Phase 5 pattern_compression INV-C2).

### INV-C3 -- Rule Count Bounded
- **Statement:** Rule count R <= `MAX_RULES`. Outer loop bound in greedy selection.
- **Testable Assertion:** For every compression run, `len(rules) <= MAX_RULES`.
- **Enforcing Subsystem:** PatternCompressionEngine greedy loop.
- **Violation Consequence:** Unbounded rule count; compression output is as complex as the input.
- **Lineage:** **New in v3.0** (Phase 5 pattern_compression INV-C3).

### INV-C4 -- Population Cap
- **Statement:** Population capped at 5000 patterns. LIMIT in population query.
- **Testable Assertion:** Population query includes `LIMIT 5000`.
- **Enforcing Subsystem:** PatternCompressionEngine population query.
- **Violation Consequence:** Compression algorithm runs on unbounded input; O(n*R) becomes prohibitive.
- **Lineage:** **New in v3.0** (Phase 5 pattern_compression INV-C4).

### INV-C5 -- Minimum Population Guard
- **Statement:** No discovery emitted for N < `MIN_POPULATION_SIZE`.
- **Testable Assertion:** Compression engine returns empty result when population < threshold.
- **Enforcing Subsystem:** PatternCompressionEngine population guard.
- **Violation Consequence:** Compression on tiny populations produces meaningless rules.
- **Lineage:** **New in v3.0** (Phase 5 pattern_compression INV-C5).

### INV-C6 -- Read-Only Snap Consumer
- **Statement:** Compression reads snap decisions; never writes them.
- **Testable Assertion:** Code audit: no write path to `snap_decision_log` in compression code.
- **Enforcing Subsystem:** PatternCompressionEngine (read-only consumer).
- **Violation Consequence:** Compression corrupts snap provenance.
- **Lineage:** **New in v3.0** (Phase 5 pattern_compression INV-C6).

### INV-C9 -- Compression Tenant Isolation
- **Statement:** `tenant_id` in all WHERE clauses and primary keys.
- **Testable Assertion:** Schema and query audit.
- **Enforcing Subsystem:** PatternCompressionEngine. Reinforces INV-7.
- **Violation Consequence:** Cross-tenant pattern compression contamination.
- **Lineage:** **New in v3.0** (Phase 5 pattern_compression INV-C9).

---

## Category 20: Cold Storage (Preserved)

### INV-COLD-1 -- Cold Storage Tenant Isolation
- **Statement:** `tenant_id` on every DB query and every Parquet path construction. `tenant_id` sanitised via `_sanitise_tenant_id()` before any filesystem access.
- **Testable Assertion:** No Parquet path constructed without sanitised `tenant_id` prefix. Path traversal injection test on `tenant_id` fails.
- **Enforcing Subsystem:** ColdStorageManager `_sanitise_tenant_id()`. Reinforces INV-7.
- **Violation Consequence:** Path traversal; cross-tenant Parquet file access.
- **Lineage:** v2.0 cold storage design, confirmed in Phase 1.

### INV-COLD-2 -- Cold Storage Mask Tracking
- **Statement:** `mask_semantic`, `mask_topological`, `mask_operational` tracked in cold storage. Search paths exclude masked rows from ANN index traversal.
- **Testable Assertion:** Cold storage query includes mask filter on ANN search paths.
- **Enforcing Subsystem:** ColdStorageManager. Reinforces INV-11.
- **Violation Consequence:** ANN search returns results from masked (invalid) embeddings.
- **Lineage:** Phase 1 cold_storage INV-11 reference.

---

## Supersession Table

The following v2.0 items are superseded by v3.0 invariants with justification:

| v2.0 ID | v3.0 Replacement | Justification |
|----------|-------------------|---------------|
| ALG-2.5-1 (Embedding Validity Semantics) | INV-11 (updated), INV-12-EMB, INV-14 | JSONB mask replaced with per-column booleans; DB-level CHECK constraints added. The new invariants are strictly stronger. |
| RES-3.4-1 (Queue Saturation) | INV-BP-1 | Promoted from resource constraint to hard invariant. Statement unchanged. |
| ALG-2.1-1 (Bounded Relevance Boost) | Merged into INV-2 | Boost cap is now part of the monotonic decay invariant statement. |
| ALG-2.2-2 (Temporal Modifier Constraint) | Merged into INV-3 | Temporal modifier bounds are part of the bounded scoring arithmetic invariant. |
| ALG-2.4-1 (Cluster Scoring Accuracy) | INV-8 (unchanged) | The LME replacement is an implementation detail. The invariant (scores in `[0.0, 1.0]`) is unchanged. |

All v2.0 resource constraints (RES-3.x) are preserved within INV-6 and INV-9 with their specific numeric bounds.
All v2.0 provenance constraints (PROV-4.x) are preserved within INV-10 and INV-12.
All v2.0 algorithmic constraints (ALG-2.x) not listed in the supersession table are preserved within their corresponding invariant.

---

## Summary Statistics

| Category | Count |
|----------|-------|
| Fragment Lifecycle (Cat 1) | 3 |
| Scoring and Arithmetic (Cat 2) | 4 |
| Embedding Validity (Cat 3) | 5 |
| Scoring Weight Integrity (Cat 4) | 4 |
| Tenant Isolation (Cat 5) | 1 |
| Resource Bounds (Cat 6) | 2 |
| Provenance (Cat 7) | 2 |
| Back-Pressure / Ops (Cat 8) | 2 |
| Telemetry Aligner (Cat 9) | 4 |
| Negative Evidence (Cat 10) | 2 |
| Surprise Engine (Cat 11) | 8 |
| Bridge Detection (Cat 12) | 4 |
| Hypothesis Engine (Cat 13) | 10 |
| Meta-Memory (Cat 14) | 7 |
| Causal Direction (Cat 15) | 6 |
| Evolutionary Patterns (Cat 16) | 11 |
| Counterfactual Simulation (Cat 17) | 8 |
| Expectation Violation (Cat 18) | 7 |
| Pattern Compression (Cat 19) | 7 |
| Cold Storage (Cat 20) | 2 |
| **TOTAL** | **99** |

**Lineage Breakdown:**
- Preserved from v2.0 unchanged: 11
- Updated from v2.0: 1 (INV-11)
- Superseded with justification: 5 (see supersession table)
- New in v3.0: 82

**Enforcing Subsystem Coverage:**
Every subsystem introduced in Phases 1-5 has at least one dedicated invariant. Every state transition in the system (fragment lifecycle, hypothesis lifecycle, evolutionary generation cycle, causal candidate supersession) is covered by at least one invariant governing its validity.

---

*Document produced by Phase 6 invariant merge. All v2.0 invariants accounted for. All Phase 1-5 INV- declarations incorporated.*
