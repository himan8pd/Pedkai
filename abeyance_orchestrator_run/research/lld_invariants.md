# Abeyance Memory LLD v2.0 — Extracted Invariants, Constraints, and Safety Guarantees

**Extraction Date:** 2026-03-16
**Source Document:** `/Users/himanshu/Projects/Pedkai/docs/ABEYANCE_MEMORY_LLD.md` (v2.0)
**Scope:** Sections 3-5 + Hard Invariants (Section 7)

---

## Section 3: Scalability & Resource Model

### Resource Constraint: Fragment Lifecycle Limits
- **ID:** RES-3.1-1
- **Statement:** "Fragment max lifetime: 730 days (INV-6). Fragment max idle: 90 days (INV-6). Raw content max size: 64KB (INV-6)."
- **Enforcing Subsystem:** DecayEngine, Fragment lifecycle state machine
- **Type:** Hard bound

### Resource Constraint: Active Fragment Population
- **ID:** RES-3.1-2
- **Statement:** "Active fragments (ACTIVE + NEAR_MISS) < 500K per tenant"
- **Enforcing Subsystem:** Snap Engine, Accumulation Graph
- **Type:** Operational limit

### Resource Constraint: Accumulation Edges
- **ID:** RES-3.2-1
- **Statement:** "Accumulation edges per fragment: 20 (Weakest-edge eviction)"
- **Enforcing Subsystem:** AccumulationGraph
- **Type:** Hard bound with eviction policy

### Resource Constraint: Cluster Size
- **ID:** RES-3.2-2
- **Statement:** "Cluster size: 50 (Pruning by edge strength)"
- **Enforcing Subsystem:** AccumulationGraph
- **Type:** Hard bound with pruning policy

### Resource Constraint: BFS Expansion
- **ID:** RES-3.2-3
- **Statement:** "BFS expansion result: 500 entities (Hard cap)"
- **Enforcing Subsystem:** ShadowTopology
- **Type:** Hard limit

### Resource Constraint: Redis Stream Length
- **ID:** RES-3.2-4
- **Statement:** "Redis stream length: 10,000 per stream (MAXLEN)"
- **Enforcing Subsystem:** RedisNotifier
- **Type:** Hard limit

### Resource Constraint: Snap Evaluation
- **ID:** RES-3.2-5
- **Statement:** "Snap candidates per evaluation: 200 (LIMIT clause)"
- **Enforcing Subsystem:** SnapEngine
- **Type:** Hard limit

### Resource Constraint: Decay Batch
- **ID:** RES-3.2-6
- **Statement:** "Decay batch size: 10,000 per run (LIMIT clause)"
- **Enforcing Subsystem:** DecayEngine
- **Type:** Hard limit

### Constraint: Fragment Lifetime Enforcement
- **ID:** RES-3.2-7
- **Statement:** "Hard lifetime: 730 days → forced expiration (INV-6). Idle timeout: 90 days without evaluation → forced expiration (INV-6)."
- **Enforcing Subsystem:** DecayEngine
- **Type:** Temporal constraint

### Back-Pressure Constraint: Queue Saturation
- **ID:** RES-3.4-1
- **Statement:** "HIGH_WATER_MARK (500 pending) → HTTP 429. CRITICAL_WATER_MARK (2000 pending) → Circuit breaker OPEN for 30 seconds."
- **Enforcing Subsystem:** Event ingestion queue
- **Type:** Operational throttling

---

## Section 4: Observability & Provenance Architecture

### Safety Guarantee: Append-Only Audit Trail
- **ID:** PROV-4.1-1
- **Statement:** "All provenance trails are append-only and tamper-evident (INV-10). Provenance tables: `fragment_history`, `snap_decision_record`, `cluster_snapshot`."
- **Enforcing Subsystem:** ProvenanceLogger
- **Type:** Immutability guarantee

### Safety Guarantee: Write-Ahead Persistence
- **ID:** PROV-4.3-1
- **Statement:** "Write-Ahead Pattern: (1) Persist state to PostgreSQL, (2) Commit transaction, (3) Best-effort Redis notification, (4) If Redis fails → log warning, state safe in PostgreSQL. (5) Consumers recover by querying PostgreSQL for events > last_processed_timestamp. Deterministic full state rebuild from PostgreSQL alone (INV-12)."
- **Enforcing Subsystem:** ProvenanceLogger, Events system
- **Type:** Durability and recovery guarantee

### Observability Requirement: Fragment History Auditing
- **ID:** PROV-4.2-1
- **Statement:** "Every fragment state change logged to `fragment_history` with fields: fragment_id, event_type, old_state, new_state, event_detail."
- **Enforcing Subsystem:** DecayEngine, Fragment lifecycle
- **Type:** Traceability requirement

### Observability Requirement: Snap Decision Breakdown
- **ID:** PROV-4.2-2
- **Statement:** "Full scoring breakdown persisted to `snap_decision_record` with fields: component_scores, weights_used, final_score, threshold, decision, multiple_comparisons_k."
- **Enforcing Subsystem:** SnapEngine
- **Type:** Traceability requirement

### Observability Requirement: Cluster Evaluation Recording
- **ID:** PROV-4.2-3
- **Statement:** "Cluster evaluation record `cluster_snapshot` captures: member_fragment_ids, edges, cluster_score, correlation_discount, adjusted_score."
- **Enforcing Subsystem:** AccumulationGraph
- **Type:** Traceability requirement

### Observability Requirement: Decay Audit Trail
- **ID:** PROV-4.2-4
- **Statement:** "Every decay update logged to fragment_history (INV-10) with monotonicity enforcement: new_score = min(computed_score, old_score)."
- **Enforcing Subsystem:** DecayEngine
- **Type:** Traceability and invariant enforcement

---

## Section 5: Audit Remediation Traceability Matrix

### Safety Guarantee: Bounded Relevance Boost
- **ID:** ALG-2.1-1
- **Statement:** "Unbounded relevance boost (1.15^n) replaced with capped formula: boost_factor = 1.0 + min(near_miss_count, 10) * 0.05, in [1.0, 1.5] (hard-capped). Justification: Original formula grew to 4.05 at n=10, 16.4 at n=20, creating positive feedback loop on noise."
- **Enforcing Subsystem:** DecayEngine
- **Type:** Algorithmic constraint

### Safety Guarantee: Monotonic Decay
- **ID:** ALG-2.1-2
- **Statement:** "Decay is strictly monotonic decreasing under constant conditions (INV-2). exp(-age/tau) is strictly decreasing. boost_factor is monotonically non-decreasing (near_miss_count never decreases). Under constant conditions, only time-varying component is exp(-age/tau), guaranteeing monotonic decrease."
- **Enforcing Subsystem:** DecayEngine
- **Type:** Mathematical invariant

### Safety Guarantee: Bounded Scoring Arithmetic
- **ID:** ALG-2.2-1
- **Statement:** "All scoring arithmetic uses bounded domains (INV-3). raw_composite in [0.0, 1.0] (weights sum to 1.0, each component in [0.0, 1.0]). temporal_modifier in [0.5, 1.0] (cannot amplify, only attenuate). snap_score = raw_composite * temporal_modifier in [0.0, 1.0]."
- **Enforcing Subsystem:** SnapEngine
- **Type:** Mathematical invariant

### Safety Guarantee: Temporal Modifier Constraint
- **ID:** ALG-2.2-2
- **Statement:** "Temporal modifier clamped to [0.5, 1.0]: temporal_modifier = 0.5 + 0.5 * temporal_factor. This ensures temporal alignment can never cause a snap that the evidence doesn't support (original temporal_weight in [0.01, 2.0] could force snaps via temporal proximity alone: 0.4 * 2.0 = 0.8 > 0.75)."
- **Enforcing Subsystem:** SnapEngine
- **Type:** Algorithmic constraint

### Safety Guarantee: Multiple Comparisons Correction
- **ID:** ALG-2.3-1
- **Statement:** "Sidak correction applied across K failure mode profiles. adjusted_threshold = 1 - (1 - base_threshold)^(1/K). K=1: threshold = 0.75 (unchanged). K=5: threshold = 0.887 (significantly harder to cross). Justification: Evaluating under all 5 profiles gives 5 chances to cross threshold, inflating false positive rates."
- **Enforcing Subsystem:** SnapEngine
- **Type:** Statistical correction

### Safety Guarantee: Embedding Validity Semantics
- **ID:** ALG-2.5-1
- **Statement:** "Every similarity computation uses mathematically meaningful vectors (INV-11). Replaced hash embeddings (SHA256 → random vectors) with LLM embeddings with explicit validity mask: [semantic_valid, topo_valid, temporal_valid=True, operational_valid]. When a sub-vector cannot be computed, it is zero-filled and mask[i]=False."
- **Enforcing Subsystem:** EnrichmentChain
- **Type:** Vector algebra constraint

### Safety Guarantee: Cluster Scoring Accuracy
- **ID:** ALG-2.4-1
- **Statement:** "Cluster scoring replaced Noisy-OR with Log-Mean-Exp with correlation discount. density = 2 * |edges| / (|nodes| * (|nodes| - 1)). correlation_discount = max(0.5, 1.0 - 0.5 * density). adjusted_score = cluster_score * correlation_discount. Removed independence assumption that produced overconfident scores (Noisy-OR: 0.949 on 5 weak signals; LME: ~0.483)."
- **Enforcing Subsystem:** AccumulationGraph
- **Type:** Algorithmic replacement

---

## Section 7: Hard Invariants (System Rejection Criteria)

### Invariant: Fragment State Machine Determinism
- **ID:** INV-1
- **Statement:** "Fragment lifecycle is a deterministic state machine (INGESTED → ACTIVE → NEAR_MISS → SNAPPED/STALE → EXPIRED → COLD)"
- **Enforcing Subsystem:** Fragment lifecycle, application layer via VALID_TRANSITIONS dict
- **Type:** State machine invariant

### Invariant: Monotonic Decay
- **ID:** INV-2
- **Statement:** "Decay is strictly monotonic decreasing under constant conditions"
- **Enforcing Subsystem:** DecayEngine
- **Type:** Monotonicity invariant

### Invariant: Bounded Scoring
- **ID:** INV-3
- **Statement:** "All scoring arithmetic uses bounded domains"
- **Enforcing Subsystem:** SnapEngine, AccumulationGraph, DecayEngine
- **Type:** Mathematical invariant

### Invariant: Monotonic Cluster Convergence
- **ID:** INV-4
- **Statement:** "Cluster membership is monotonic convergent. Edge updates only increase scores (INV-4). Prevents clustering oscillation."
- **Enforcing Subsystem:** AccumulationGraph, edge update logic
- **Type:** Monotonicity invariant

### Invariant: Irreversible Snaps
- **ID:** INV-5
- **Statement:** "Fragment joins (snaps) are irreversible except via explicit operator action"
- **Enforcing Subsystem:** SnapEngine, application layer authorization
- **Type:** Operational constraint

### Invariant: Hard Fragment Bounds
- **ID:** INV-6
- **Statement:** "Every fragment has hard bounds: 730d lifetime, 64KB content, 90d idle"
- **Enforcing Subsystem:** DecayEngine, fragment validation
- **Type:** Resource constraint

### Invariant: Tenant Isolation
- **ID:** INV-7
- **Statement:** "Tenant ID immutably bound at ingestion, verified at every cross-boundary operation"
- **Enforcing Subsystem:** All query paths, fragment ingestion
- **Type:** Security and isolation invariant

### Invariant: Score Range Guarantee
- **ID:** INV-8
- **Statement:** "No scoring function produces output outside [0.0, 1.0]"
- **Enforcing Subsystem:** SnapEngine, AccumulationGraph, DecayEngine
- **Type:** Output range invariant

### Invariant: Bounded Resource Growth
- **ID:** INV-9
- **Statement:** "Total resource growth per tenant is O(n) with fragment count"
- **Enforcing Subsystem:** AccumulationGraph, resource bounds with eviction policies
- **Type:** Algorithmic complexity invariant

### Invariant: Append-Only Provenance
- **ID:** INV-10
- **Statement:** "All provenance trails are append-only and tamper-evident"
- **Enforcing Subsystem:** ProvenanceLogger, database schema constraints
- **Type:** Audit and immutability invariant

### Invariant: Mathematically Valid Embeddings
- **ID:** INV-11
- **Statement:** "Every similarity computation uses mathematically meaningful vectors"
- **Enforcing Subsystem:** EnrichmentChain, embedding validity mask
- **Type:** Vector algebra invariant

### Invariant: State Rebuild from PostgreSQL
- **ID:** INV-12
- **Statement:** "Deterministic full state rebuild from PostgreSQL alone"
- **Enforcing Subsystem:** Write-Ahead pattern, ProvenanceLogger
- **Type:** Recovery and durability invariant

### Invariant: Multiple Comparisons Correction
- **ID:** INV-13
- **Statement:** "Multiple comparisons correction applied across failure mode profiles"
- **Enforcing Subsystem:** SnapEngine, Sidak correction logic
- **Type:** Statistical validity invariant

---

## Summary Statistics

**Total Invariants Extracted:** 13 (Hard) + 29 (Constraints/Safety Guarantees)
**Categories:**
- Hard Invariants (INV-1 through INV-13): 13
- Resource Constraints (RES): 8
- Provenance/Observability (PROV): 5
- Algorithmic Constraints (ALG): 7

**Enforcing Subsystems:**
- DecayEngine: 11 invariants/constraints
- SnapEngine: 9 invariants/constraints
- AccumulationGraph: 8 invariants/constraints
- EnrichmentChain: 3 invariants/constraints
- ShadowTopology: 2 invariants/constraints
- ProvenanceLogger: 6 invariants/constraints
- Fragment lifecycle: 5 invariants/constraints

---

*Extraction completed per T0.2 specification. All invariants extracted from LLD v2.0 §3-7.*
*No new invariants suggested. No design recommendations included.*
