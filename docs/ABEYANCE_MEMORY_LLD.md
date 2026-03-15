# Abeyance Memory — Low-Level Design & Implementation Specification

**Version:** 2.0 (Remediated)
**Date:** 2026-03-15
**Status:** Authoritative — Post-Forensic Audit Remediation
**Classification:** Product Confidential
**Parent Document:** PRODUCT_SPEC.md §4
**Supersedes:** Abeyance Memory LLD v1.0 (2026-03-09)
**Audit Reference:** docs/ABEYANCE_MEMORY_FORENSIC_AUDIT.md

> This document specifies the complete remediated architecture for Abeyance Memory following the forensic architectural audit. Every change is traceable to a specific audit finding with explicit evidence.

---

## Table of Contents

1. [Executive Triage Summary](#1-executive-triage-summary)
2. [Core Algorithmic Decisions & Justifications](#2-core-algorithmic-decisions--justifications)
3. [Scalability & Resource Model](#3-scalability--resource-model)
4. [Observability & Provenance Architecture](#4-observability--provenance-architecture)
5. [Audit Remediation Traceability Matrix](#5-audit-remediation-traceability-matrix)
6. [Failure Modes & Recovery Procedures](#6-failure-modes--recovery-procedures)
7. [Hard Invariants](#7-hard-invariants-system-rejection-criteria)
8. [Architecture Overview](#8-architecture-overview)
9. [The Fragment Model](#9-the-fragment-model)
10. [The Enrichment Chain](#10-the-enrichment-chain)
11. [The Snap Engine](#11-the-snap-engine)
12. [The Accumulation Graph](#12-the-accumulation-graph)
13. [The Decay Engine](#13-the-decay-engine)
14. [The Shadow Topology](#14-the-shadow-topology)
15. [Value Attribution](#15-value-attribution)
16. [Software Architecture](#16-software-architecture)

---

## 1. Executive Triage Summary

### Audit Outcome

The forensic audit (2026-03-15) found Abeyance Memory to be **architecturally sound in design, critically flawed in implementation**. The audit rated the system at "55% real capability, 45% conceptual scaffolding" with specific findings in algorithmic non-determinism, unbounded growth, observability gaps, and tenant isolation failures.

### Remediation Scope

13 hard invariants were defined as system rejection criteria. All 10 major components were evaluated:
- **2 Preserved** (Value Attribution, Incident Reconstruction)
- **5 Repaired** (Decay Engine, Enrichment Chain, Snap Engine, Shadow Topology, Event Bus)
- **3 Replaced** (Fragment Model, Accumulation Graph, Cold Storage)

### Critical Changes from v1.0

| Area | v1.0 (Flawed) | v2.0 (Remediated) | Audit Finding |
|------|--------------|-------------------|---------------|
| Fragment Model | Split-brain (DecisionTraceORM + AbeyanceFragmentORM) | Single canonical model with state machine | §3.1 |
| Near-miss boost | Unbounded 1.15^n (grows to 16.4 at n=20) | Capped at 1.5 total (1.0 + min(n,10) * 0.05) | §2.2 |
| Temporal weight | [0.01, 2.0] — could override evidence | [0.5, 1.0] — can only attenuate | §4.2 |
| Cluster scoring | Noisy-OR (0.949 on 5 weak signals) | Log-Mean-Exp with correlation discount (0.282 on same) | §4.1 |
| Multiple comparisons | 5 chances to cross threshold, no correction | Sidak correction (threshold 0.75 → 0.887 for k=5) | §4.3 |
| Embeddings | 67% hash noise (SHA256 → random vectors) | LLM embeddings with validity mask | §2.3 |
| Operational fingerprint | All fields stubbed to defaults | None for missing data; 0.0 similarity on stubs | §3.2 |
| Entity extraction | LLM call never made (no-op) | Real LLM call with regex fallback | §3.3 |
| Snap score | Computed and discarded | Full breakdown persisted to snap_decision_record | §7.1 |
| Decay trail | Scores overwritten in place | Append-only fragment_history | §7.2 |
| Cluster membership | Transient, lost after snap | Persisted to cluster_snapshot | §7.3 |
| Shadow BFS | Explosive CTE, no cycle guard | Cycle-guarded BFS with visited set | §3.4 |
| Tenant isolation | Missing on 3 code paths | tenant_id on every query, every table | §9.1-§9.4 |
| Redis dependency | Silent event loss | Write-ahead to PostgreSQL; Redis is notification only | §6.1 |
| GIN indexes | Missing (specified but not created) | Created on failure_mode_tags and extracted_entities | §5.1 |
| Baseline divergences | Fabricated (resolved_count * 2) | Requires real deployment baseline | §10 table |

---

## 2. Core Algorithmic Decisions & Justifications

### 2.1 Decay Formula (Remediated)

```
decay_score(t) = base_relevance * boost_factor * exp(-age_days / tau)

boost_factor = 1.0 + min(near_miss_count, 10) * 0.05
             in [1.0, 1.5]  (hard-capped)
```

**Justification**: Audit §2.2 showed the original 1.15^n boost grew unboundedly (4.05 at n=10, 16.4 at n=20), creating a positive feedback loop on noise. The remediated formula caps total boost at 50%, preserving the design intent (near-misses slow decay) without noise amplification.

**Monotonicity (INV-2)**: exp(-age/tau) is strictly decreasing. boost_factor is monotonically non-decreasing (near_miss_count never decreases). Under constant conditions (no new near-misses), the only time-varying component is exp(-age/tau), guaranteeing monotonic decrease.

### 2.2 Snap Scoring (Remediated)

```
raw_composite = w_sem * sim + w_topo * prox + w_entity * jacc + w_oper * oper
              in [0.0, 1.0]  (weights sum to 1.0, each component in [0.0, 1.0])

temporal_modifier = 0.5 + 0.5 * temporal_factor
                  in [0.5, 1.0]  (cannot amplify, only attenuate)

snap_score = raw_composite * temporal_modifier
           in [0.0, 1.0]
```

**Justification**: Audit §4.2 showed the original temporal_weight in [0.01, 2.0] could force snaps via temporal proximity alone (0.4 * 2.0 = 0.8 > 0.75). Capping at 1.0 means temporal alignment can never cause a snap that the evidence doesn't support.

**Temporal Factor Computation**:
```
age_factor = exp(-age_days / tau)                           in [0, 1]
change_bonus = 0.3 * shared_change_proximity               in [0, 0.3]
diurnal = (1 + cos_sim(tod_a, tod_b)) / 2                 in [0, 1]

temporal_factor = clamp(age_factor * (1 + change_bonus) * diurnal, 0.0, 1.0)
```

### 2.3 Multiple Comparisons Correction (New)

When evaluating under K failure mode profiles, the Sidak correction adjusts thresholds:

```
adjusted_threshold = 1 - (1 - base_threshold)^(1/K)

K=1: threshold = 0.75  (unchanged)
K=5: threshold = 0.887 (significantly harder to cross)
```

**Justification**: Audit §4.3 identified that evaluating under all 5 profiles gives 5 chances to cross the threshold, inflating false positive rates. Sidak correction restores the intended false positive rate.

### 2.4 Cluster Scoring (Replaced)

**Removed**: Noisy-OR `P = 1 - prod(1 - s_i)`

**Replaced with**: Log-Mean-Exp with correlation discount

```
cluster_score = LME(edge_scores, temperature=0.3)
LME(scores, tau) = tau * log(mean(exp(score_i / tau)))

density = 2 * |edges| / (|nodes| * (|nodes| - 1))
correlation_discount = max(0.5, 1.0 - 0.5 * density)
adjusted_score = cluster_score * correlation_discount
```

**Properties**:
- tau → 0: converges to max(scores) — only strongest edge matters
- tau → inf: converges to mean(scores) — all edges equal
- At tau = 0.3: strong edges dominate, weak contribute, no independence assumption

**Verification with LLD v1.0 example** (5 edges: 0.50, 0.45, 0.42, 0.48, 0.38; 4 nodes):
- Noisy-OR: 0.949 (wildly overconfident)
- LME(tau=0.3): ~0.483
- density = 0.833, discount = 0.583
- adjusted = 0.282 (correctly conservative)

### 2.5 Embedding Architecture (Remediated)

**Removed**: Hash embeddings (SHA256 → random vectors) for topological and operational sub-vectors.

**Replaced with**: LLM embeddings with explicit validity mask.

```
embedding_mask = [semantic_valid, topo_valid, temporal_valid, operational_valid]
```

When a sub-vector cannot be computed (LLM unavailable), it is zero-filled and mask[i]=False. The temporal sub-vector is always valid (pure numerical computation from sinusoidal encoding).

**Justification**: Audit §2.3: "cosine similarity between two hash embeddings is mathematically meaningless."

---

## 3. Scalability & Resource Model

### 3.1 Target Operating Conditions

| Parameter | Target |
|-----------|--------|
| Fragments per tenant | 5-50 million |
| Ingestion rate | 100-10,000 events/minute |
| Active fragments (ACTIVE + NEAR_MISS) | < 500K per tenant |
| Concurrent tenants | 10-100 |
| Fragment max lifetime | 730 days (INV-6) |
| Fragment max idle | 90 days (INV-6) |
| Raw content max size | 64KB (INV-6) |

### 3.2 Resource Bounds (INV-9)

| Resource | Bound | Enforcement |
|----------|-------|-------------|
| Accumulation edges per fragment | 20 | Weakest-edge eviction |
| Cluster size | 50 | Pruning by edge strength |
| BFS expansion result | 500 entities | Hard cap |
| Redis stream length | 10,000 per stream | MAXLEN |
| Snap candidates per evaluation | 200 | LIMIT clause |
| Decay batch size | 10,000 per run | LIMIT clause |

### 3.3 Indexing Strategy

| Index | Type | Column(s) |
|-------|------|-----------|
| Fragment retrieval | B-tree | tenant_id, snap_status |
| Fragment decay ordering | B-tree (partial) | tenant_id, current_decay_score (WHERE status IN ACTIVE, NEAR_MISS) |
| Failure mode tags | GIN (jsonb_path_ops) | failure_mode_tags |
| Extracted entities | GIN (jsonb_path_ops) | extracted_entities |
| Entity refs | B-tree | entity_id, tenant_id |
| Shadow relationship from | B-tree | from_entity_id, tenant_id |
| Shadow relationship to | B-tree | to_entity_id, tenant_id |
| Accumulation edge pair | B-tree (unique) | tenant_id, fragment_a_id, fragment_b_id |
| Enriched embedding | IVFFlat | enriched_embedding (vector_cosine_ops) |

### 3.4 Back-Pressure

```
HIGH_WATER_MARK (500 pending) → HTTP 429
CRITICAL_WATER_MARK (2000 pending) → Circuit breaker OPEN for 30 seconds
```

### 3.5 Background Maintenance Jobs

| Job | Schedule | Batch Limit |
|-----|----------|-------------|
| Decay pass | Every 6 hours | 10K fragments |
| Edge pruning | Every 6 hours | Remove where both fragments decay < 0.2 |
| Cold storage archival | Daily | 5K fragments |
| Stale fragment expiration | Daily | 10K fragments |
| Orphan cleanup | Daily | Entity refs, edges referencing non-existent fragments |
| IVFFlat index rebuild | Weekly | If fragment count changed > 20% |

---

## 4. Observability & Provenance Architecture

### 4.1 Provenance Tables (INV-10: Append-Only)

| Table | Purpose | Key Fields |
|-------|---------|-----------|
| `fragment_history` | Every fragment state change | fragment_id, event_type, old_state, new_state, event_detail |
| `snap_decision_record` | Full scoring breakdown | component_scores, weights_used, final_score, threshold, decision, multiple_comparisons_k |
| `cluster_snapshot` | Cluster evaluation record | member_fragment_ids, edges, cluster_score, correlation_discount, adjusted_score |

### 4.2 Operator Forensic Queries

| Question | Query Path |
|----------|-----------|
| Why did fragment F decay by delta X? | `fragment_history WHERE fragment_id=F AND event_type='DECAY_UPDATE'` |
| Why did fragments form cluster C? | `cluster_snapshot WHERE id=C` |
| Why did snap S trigger at time T? | `snap_decision_record WHERE evaluated_at=T` |
| What evidence chain produced discovery D? | `hypothesis_id → snap_decision_record → fragment_history` |

### 4.3 Write-Ahead Pattern (INV-12)

```
1. Persist state to PostgreSQL
2. Commit transaction
3. Best-effort Redis notification
4. If Redis fails → log warning, state safe in PostgreSQL
5. Consumers recover by querying PostgreSQL for events > last_processed_timestamp
```

---

## 5. Audit Remediation Traceability Matrix

| Audit Finding | Sev | Remediation | Component | Invariant |
|--------------|-----|-------------|-----------|-----------|
| §2.2 Unbounded relevance boost | Crit | Capped at 1.5 (additive 0.05/near-miss, max 10) | DecayEngine | INV-2, INV-8 |
| §2.3 Hash embeddings (67% noise) | Sev | LLM embeddings with validity mask | EnrichmentChain | INV-11 |
| §3.1 Split-brain fragment model | Crit | Unified AbeyanceFragmentORM; DecisionTraceORM deprecated | Models | INV-1 |
| §3.2 Stubbed operational fingerprint | Sev | None for missing data; 0.0 similarity on stubs | EnrichmentChain | INV-11 |
| §3.3 LLM entity extraction no-op | Sev | Real LLM call with regex fallback | EnrichmentChain | — |
| §3.4 Shadow Topology CTE explosion | Sev | Cycle-guarded BFS, visited set, cap 500 | ShadowTopology | INV-9 |
| §4.1 Noisy-OR overconfidence | Crit | LME with correlation discount | AccumulationGraph | INV-8 |
| §4.2 Temporal weight overrides evidence | Mod | Temporal modifier capped [0.5, 1.0] | SnapEngine | INV-3, INV-8 |
| §4.3 Multiple comparisons inflation | Mod | Sidak correction | SnapEngine | INV-13 |
| §5.1 Missing GIN indexes | Crit | Created on failure_mode_tags, extracted_entities | Models | — |
| §5.3 Recursive CTE no cycle guard | Sev | Python union-find | AccumulationGraph | INV-4 |
| §6.1 Silent Redis event loss | Crit | Write-ahead to PostgreSQL | Events | INV-12 |
| §7.1 Snap score not persisted | Crit | Full breakdown to snap_decision_record | SnapEngine | INV-10 |
| §7.2 No decay audit trail | Sev | Append-only fragment_history | DecayEngine | INV-10 |
| §7.3 Cluster unobservable | Sev | ClusterSnapshot persisted | AccumulationGraph | INV-10 |
| §9.1 Tenant path traversal | Crit | tenant_id on all queries | All | INV-7 |
| §9.2 No tenant on edge queries | Sev | Tenant-scoped uniqueness | AccumulationGraph | INV-7 |
| §9.3 Shadow entity fetch unfiltered | Mod | Tenant filter on entity fetch | ShadowTopology | INV-7 |
| §10 Fabricated baseline | Mod | Requires real deployment baseline | ValueAttribution | — |

---

## 6. Failure Modes & Recovery Procedures

### 6.1 Complete Redis Loss

- **Impact**: Notification delay. No data loss.
- **Behavior**: Degraded-persistent mode. All state in PostgreSQL (INV-12).
- **Recovery**: Consumers query PostgreSQL for events > last_processed_timestamp.

### 6.2 Vector Index Corruption

- **Detection**: Periodic recall check (100-sample brute-force comparison). Alert if recall < 0.9.
- **Recovery**: Drop → exact search fallback → REINDEX CONCURRENTLY → validate → resume.

### 6.3 Duplicate Ingestion

- **Detection**: UNIQUE constraint on (tenant_id, dedup_key).
- **Behavior**: ON CONFLICT DO NOTHING. Different content logged as warning.

### 6.4 Partial Storage Loss

- **Detection**: Daily referential integrity check.
- **Recovery**: Orphaned edges deleted. Orphaned snap refs marked EVIDENCE_LOST.

### 6.5 Clustering Oscillation

- **Prevention**: INV-4 (edge updates only increase scores).
- **Detection**: Same fragments evaluated > 3x/24h with score variance > 0.1.
- **Response**: Freeze cluster edges. Unfreeze on new fragment join.

### 6.6 Full State Rebuild

- **Procedure**: Replay fragment_history → restore states → rebuild edges → rebuild indexes.
- **Time**: O(n) events. ~30 minutes for 1M events.

---

## 7. Hard Invariants (System Rejection Criteria)

| # | Invariant |
|---|-----------|
| INV-1 | Fragment lifecycle is a deterministic state machine (INGESTED → ACTIVE → NEAR_MISS → SNAPPED/STALE → EXPIRED → COLD) |
| INV-2 | Decay is strictly monotonic decreasing under constant conditions |
| INV-3 | All scoring arithmetic uses bounded domains |
| INV-4 | Cluster membership is monotonic convergent |
| INV-5 | Fragment joins (snaps) are irreversible except via explicit operator action |
| INV-6 | Every fragment has hard bounds: 730d lifetime, 64KB content, 90d idle |
| INV-7 | Tenant ID immutably bound at ingestion, verified at every cross-boundary operation |
| INV-8 | No scoring function produces output outside [0.0, 1.0] |
| INV-9 | Total resource growth per tenant is O(n) with fragment count |
| INV-10 | All provenance trails are append-only and tamper-evident |
| INV-11 | Every similarity computation uses mathematically meaningful vectors |
| INV-12 | Deterministic full state rebuild from PostgreSQL alone |
| INV-13 | Multiple comparisons correction applied across failure mode profiles |

---

## 8. Architecture Overview

### Abeyance Memory Within the PedkAI Stack

Abeyance Memory lives in **Layer 2 (Living Context Graph)** of PedkAI's 5-layer architecture. It receives data from Layer 1 (Omniscient Data Fabric) and feeds hypotheses to Layer 3 (Intelligence Engines).

### Internal Data Flow

```
Raw Evidence → Enrichment Chain (4 steps) → Fragment Store
                                            ↓
                                       Snap Engine (3 stages)
                                      ↙        ↓          ↘
                               SNAP      NEAR_MISS     AFFINITY
                                ↓            ↓              ↓
                          Hypothesis    Boost Decay    Accumulation
                          Lifecycle     (capped)       Graph (LME)
                                ↓                          ↓
                          Shadow Topology         Cluster Evaluation
                          Enrichment              (correlation discount)
                                ↓
                          Value Attribution
                          Ledger
```

### Key Design Principles

1. **PostgreSQL is the sole source of truth** (INV-12). Redis is a notification layer.
2. **Every scoring operation is bounded** (INV-3, INV-8). No operation can produce outputs outside its declared range.
3. **Every decision is auditable** (INV-10). Provenance tables record full scoring breakdowns.
4. **Tenant isolation is enforced everywhere** (INV-7). No query omits tenant_id.
5. **Growth is bounded** (INV-9). Every resource has explicit limits and eviction policies.

---

## 9. The Fragment Model

### Lifecycle State Machine (INV-1)

```
INGESTED ──→ ACTIVE ──→ NEAR_MISS ──→ SNAPPED (terminal)
                │              │
                ├──→ STALE ────┤
                               ↓
                           EXPIRED ──→ COLD (terminal)
```

Valid transitions are enforced at the application layer via `VALID_TRANSITIONS` dict.

### Source Type Characteristics (unchanged from v1.0)

| Source Type | Base Relevance | Decay tau (days) |
|-------------|:-:|:-:|
| TICKET_TEXT ("could not reproduce") | 0.95 | 270 |
| TICKET_TEXT ("no fault found") | 0.90 | 270 |
| TICKET_TEXT (resolved) | 0.60 | 120 |
| ALARM (self-cleared) | 0.70 | 90 |
| CHANGE_RECORD | 0.80 | 365 |
| TELEMETRY_EVENT | 0.60 | 60 |
| CLI_OUTPUT | 0.70 | 180 |
| CMDB_DELTA | 0.70 | 90 |

### Deduplication (New)

Fragments are deduplicated on `(tenant_id, dedup_key)` where:
```
dedup_key = SHA256(tenant_id : source_type : source_ref : event_timestamp)[:64]
```

---

## 10. The Enrichment Chain

### Step 1: Entity Resolution

- **Primary**: LLM structured extraction (real call, not no-op)
- **Fallback**: Regex patterns for structured sources (alarms, telemetry)
- **Supplement**: Explicit entity refs from caller
- **Topology expansion**: 2-hop via Shadow Topology BFS (cycle-guarded)

### Step 2: Operational Fingerprinting

Returns `None` for unavailable fields (not stub defaults). This ensures operational similarity correctly returns 0.0 when comparing fragments with no real operational data.

### Step 3: Failure Mode Classification

Rule-based heuristics matching content keywords against Dark Graph divergence taxonomy. Unchanged from v1.0.

### Step 4: Temporal-Semantic Embedding

1536-dim = 512 semantic + 384 topological + 256 temporal + 384 operational.

- **Semantic**: LLM embedding of content + entity names
- **Topological**: LLM embedding of neighbourhood description (NOT hash)
- **Temporal**: Numerical sinusoidal encoding (always valid)
- **Operational**: LLM embedding of failure modes + fingerprint (NOT hash)
- **Mask**: `[sem_valid, topo_valid, temporal_valid=True, oper_valid]`

---

## 11. The Snap Engine

### Stage 1: Targeted Retrieval

Entity-overlap-based structured query using GIN-indexed JSONB columns and fragment_entity_ref table. Returns up to 200 candidates ordered by decay score.

### Stage 2: Evidence Scoring

Per failure-mode-profile weighted scoring. Weights sum to 1.0. Each component clamped to [0.0, 1.0]. Temporal modifier in [0.5, 1.0].

### Stage 3: Snap Decision

Sidak-corrected thresholds applied. Full scoring breakdown persisted to snap_decision_record.

### Weight Profiles (unchanged from v1.0)

| Failure Mode | w_sem | w_topo | w_entity | w_oper |
|-------------|:-----:|:------:|:--------:|:------:|
| DARK_EDGE | 0.20 | 0.35 | 0.25 | 0.20 |
| DARK_NODE | 0.30 | 0.15 | 0.35 | 0.20 |
| IDENTITY_MUTATION | 0.15 | 0.20 | 0.45 | 0.20 |
| PHANTOM_CI | 0.25 | 0.20 | 0.30 | 0.25 |
| DARK_ATTRIBUTE | 0.30 | 0.15 | 0.25 | 0.30 |

---

## 12. The Accumulation Graph

### Connected Component Detection

Python-side union-find (not recursive CTE). O(n * alpha(n)) where alpha is the inverse Ackermann function.

### Cluster Scoring

Log-Mean-Exp with correlation discount. See §2.4 for full specification.

### Resource Bounds

- MAX_EDGES_PER_FRAGMENT = 20 (weakest-edge eviction)
- MAX_CLUSTER_SIZE = 50 (pruning by edge strength)
- MIN_CLUSTER_SIZE = 3 (below this, no evaluation)

---

## 13. The Decay Engine

### Formula

See §2.1. boost_factor in [1.0, 1.5]. Output clamped to [0.0, 1.0].

### Execution

- Every 6 hours, batch of up to 10K fragments per tenant
- Monotonicity enforced: new_score = min(computed_score, old_score)
- Idle timeout: 90 days without evaluation → forced expiration (INV-6)
- Hard lifetime: 730 days → forced expiration (INV-6)
- Every update logged to fragment_history (INV-10)

---

## 14. The Shadow Topology

### Cycle-Guarded BFS

- Visited set prevents revisiting nodes
- Directed walk with CASE expression
- Tenant filter on all entity fetches
- MAX_BFS_RESULT = 500 entities
- MAX_HOPS = 3

### CMDB Export

Sanitised export strips evidence_summary, confidence, fragment refs. Reference tag format: `PEDKAI-{tenant[:8]}-{rel[:8]}`.

---

## 15. Value Attribution

Unchanged from v1.0 except:
- Baseline divergences no longer fabricated — requires real deployment measurement
- Reports `INSUFFICIENT_BASELINE` status when baseline unavailable

---

## 16. Software Architecture

### File Structure

```
backend/app/
├── models/
│   └── abeyance_orm.py          # Unified ORM models + provenance tables
├── schemas/
│   └── abeyance.py              # Pydantic schemas (unchanged)
└── services/
    └── abeyance/
        ├── __init__.py           # Factory + exports
        ├── events.py             # ProvenanceLogger + RedisNotifier
        ├── enrichment_chain.py   # 4-step pipeline, real embeddings
        ├── snap_engine.py        # 3-stage evaluation, Sidak correction
        ├── accumulation_graph.py # LME scoring, union-find
        ├── decay_engine.py       # Bounded decay, audit trail
        ├── shadow_topology.py    # Cycle-guarded BFS
        ├── value_attribution.py  # Discovery ledger
        ├── incident_reconstruction.py  # Forensic timeline
        └── maintenance.py        # Bounded background jobs
```

### Service Dependencies

```
EnrichmentChain
  ├── ProvenanceLogger
  ├── LLMService (optional)
  └── ShadowTopologyService

SnapEngine
  ├── ProvenanceLogger
  └── RedisNotifier

AccumulationGraph
  ├── ProvenanceLogger
  └── RedisNotifier

DecayEngine
  ├── ProvenanceLogger
  └── RedisNotifier

MaintenanceService
  ├── DecayEngine
  ├── AccumulationGraph
  └── ProvenanceLogger
```

### Factory

```python
services = create_abeyance_services(
    redis_client=redis,
    llm_service=llm,
)
enrichment = services["enrichment"]
snap_engine = services["snap_engine"]
```

---

*Abeyance Memory v2.0 — Remediated per Forensic Audit*
*"The institutional memory your NOC has always needed and never had."*
