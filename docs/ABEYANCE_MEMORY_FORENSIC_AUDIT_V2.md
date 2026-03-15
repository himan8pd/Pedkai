# FORENSIC ARCHITECTURAL AUDIT: ABEYANCE MEMORY v2.0

**Audit Date:** 2026-03-15
**Audit Status:** Complete
**Classification:** Product Confidential
**Reference Commit:** `0e045e4` (Abeyance Memory codebase remediated after forensic audit)

---

## 1. Executive Verdict

Abeyance Memory v2.0 is a **competently remediated correlation engine** that has been wrapped in language suggesting cognitive capability it does not possess. The v1.0 audit found the system at 55% real capability. The remediation addressed the most egregious mathematical and structural flaws — unbounded boosts, Noisy-OR overconfidence, hash embeddings, missing provenance, tenant leaks — and the fixes are genuine. The bounded arithmetic, write-ahead pattern, and provenance architecture are now defensible.

However, the remediation did not address the system's **fundamental identity crisis**: Abeyance Memory claims to perform "discovery," "reasoning," and "aha moment detection." What it actually performs is **multi-dimensional similarity search with decaying relevance and configurable thresholds**. This is a useful capability. It is not intelligence. The distance between the marketing language and the mechanical reality remains the system's deepest vulnerability — not because the mechanism is bad, but because the promises invite scrutiny the mechanism cannot survive.

**Post-remediation rating: 68% real capability, 32% aspirational scaffolding.**

The 13% improvement from v1.0 is real: the math is fixed, the provenance exists, the boundaries hold. The remaining 32% gap is concentrated in six areas: the unused Shadow Topology integration, the economically catastrophic embedding architecture, the absent operational fingerprinting, the hand-tuned weight profiles with no empirical basis, latent bugs in the enrichment chain, and missing subsystems that the design promises but the code does not deliver.

---

## 2. Conceptual Flaws

### 2.1 "Discovery" Is Similarity Search — **Severity: Moderate**

The entire snap mechanism reduces to:

```
score = weighted_sum(cosine_sim, entity_overlap, topo_proxy, oper_sim) * temporal_attenuation
if score > threshold: declare_snap()
```

This is correlation detection. The system finds that Fragment A is similar to Fragment B across multiple dimensions. It does not reason about *why* they are related. It does not form hypotheses in any meaningful sense — it attaches a `hypothesis_id` UUID to two snapped fragments, which is a label, not a hypothesis. The "aha moment" language in the design document is misleading: the system fires when a cosine similarity crosses a threshold. There is no moment of insight. There is a threshold comparison.

**This is not a fatal flaw.** Correlation detection with multi-dimensional scoring, temporal decay, and provenance tracking is genuinely useful for a NOC. But calling it "cognitive" or "discovery" creates expectations the implementation cannot satisfy.

### 2.2 Dormant Fragment Activation Is Not a Novel Primitive — **Severity: Minor**

The design presents "dormant fragment activation" as if it were a new computational concept. It is not. The mechanism is: (1) store evidence with embeddings, (2) apply exponential decay, (3) when new evidence arrives, run similarity search against the store, (4) if a match exceeds threshold, declare activation. This is a time-weighted nearest-neighbor search. It has been implemented in anomaly detection systems, recommendation engines, and information retrieval systems for decades. The decay-with-corroboration-boost pattern is a variation of TF-IDF aging.

This does not make it useless. It makes the novelty claims unjustified.

### 2.3 The Accumulation Graph Assumes Independence It Cannot Verify — **Severity: Moderate**

The LME scoring with correlation discount is a significant improvement over Noisy-OR. However, the correlation discount formula:

```
density = 2 * |edges| / (|nodes| * (|nodes| - 1))
discount = max(0.5, 1.0 - 0.5 * density)
```

This is a graph-density heuristic, not a correlation measure. Two fragments can be structurally connected (high density) but evidentially independent, or structurally disconnected but causally related. The discount penalizes graph density as a proxy for correlation, which is a reasonable heuristic but not a statistical test. At density 1.0 (complete graph), the discount is 0.5 — still allowing a cluster score of 0.5 * LME, which could cross thresholds on strong-enough edges.

### 2.4 Weight Profiles Are Arbitrary — **Severity: Severe**

The five failure mode weight profiles (DARK_EDGE, DARK_NODE, IDENTITY_MUTATION, PHANTOM_CI, DARK_ATTRIBUTE) assign specific weights to semantic, topological, entity, and operational similarity. These weights are presented as domain knowledge:

```
DARK_EDGE:  w_sem=0.20, w_topo=0.35, w_entity=0.25, w_oper=0.20
DARK_NODE:  w_sem=0.30, w_topo=0.15, w_entity=0.35, w_oper=0.20
```

There is no empirical justification for these values. No A/B testing. No sensitivity analysis. No documentation of how they were derived. If `w_topo` for DARK_EDGE should be 0.35 vs 0.25, the design offers no basis for that decision. These weights are the most consequential parameters in the system — they determine what gets snapped — and they are hand-tuned constants with no validation methodology.

---

## 3. Architectural Weaknesses

### 3.1 Shadow Topology Is Built But Not Used — **Severity: Severe**

`ShadowTopologyService.topological_proximity()` implements proper BFS-based proximity measurement between entity sets. The snap engine does not use it. Instead, `snap_engine.py` approximates topological proximity as:

```python
entity_overlap = len(entities_new & entities_candidate) / max(len(entities_new | entities_candidate), 1)
topo_proximity = entity_overlap * 0.8
```

This is Jaccard similarity multiplied by 0.8, passed off as "topological proximity." The Shadow Topology exists, has cycle-guarded BFS, has tenant isolation, and is completely bypassed by the component that would benefit most from it. The `w_topo` weight in snap scoring is weighting a Jaccard heuristic, not actual topological distance.

This means the topological dimension of snap scoring — which receives up to 35% of the weight in DARK_EDGE profiles — is a degraded approximation of a capability the system already implements but does not invoke.

### 3.2 Enrichment Chain Topology Expansion Is Dead Code — **Severity: Critical**

In `enrichment_chain.py`, the topology expansion during enrichment passes an empty entity list:

```python
entity_identifiers = [ref.entity_identifier for ref in entity_refs]  # built but unused
neighbourhood = await self._shadow_topology.get_neighbourhood(
    session=session,
    tenant_id=tenant_id,
    entity_ids=[],  # <-- ALWAYS EMPTY
    max_hops=2,
)
```

The `entity_identifiers` list is constructed from resolved entity refs but never passed to `get_neighbourhood()`. This means every fragment's topological neighbourhood is empty. The topological sub-vector of the enriched embedding (384 of 1536 dimensions) is computed from an empty neighbourhood description. This is 25% of the embedding vector carrying no signal.

Combined with finding 3.1, the topological dimension of Abeyance Memory is essentially non-functional despite being architecturally present.

### 3.3 Telemetry Aligner Still Uses Hash Embeddings — **Severity: Severe**

`telemetry_aligner.py` falls back to `_hash_embedding()` — SHA256-seeded random vectors — when the embedding service is unavailable or when running in an async context where blocking is not possible:

```python
if loop.is_running():
    logger.warning("async embedding service can't block; using fallback embedding")
    return self._hash_embedding(text)
```

The v2.0 design document explicitly states (§2.5): "Removed: Hash embeddings (SHA256 → random vectors)." The audit found this to be "mathematically meaningless." Yet the telemetry aligner — the multi-modal bridge between telemetry anomalies and text fragments — retains this exact mechanism as a fallback. In an async FastAPI server (which is the production runtime), this fallback will activate on every call because `loop.is_running()` will always be True.

This means telemetry-sourced fragments will have 64-dimensional hash embeddings while text-sourced fragments will have 1536-dimensional LLM embeddings. These vectors are incomparable. Cross-modal similarity search — the stated purpose of the telemetry aligner — is broken.

### 3.4 Dual Cold Storage Paths Create Maintenance Burden — **Severity: Moderate**

`cold_storage.py` implements two completely independent storage backends:
1. PostgreSQL + pgvector (primary)
2. Local Parquet files (fallback)

These two paths have different schemas, different search semantics, different embedding dimensionalities (1536 for DB, 64 for Parquet via telemetry aligner hash), and no synchronization mechanism. A fragment archived to Parquet is invisible to DB search and vice versa. The Parquet path has a silent `except Exception: continue` that swallows all errors during loading. The design document specifies Parquet as "degraded fallback" but does not define when or how the system switches between paths, or how to reconcile state.

### 3.5 Deprecated Module Still Importable — **Severity: Minor**

`abeyance_decay.py` emits a `DeprecationWarning` at module import time (line 31-36, top-level), meaning any import — including test discovery — triggers a warning. The module exists solely for backward compatibility with `test_abeyance_decay.py`, which tests the *deprecated* decay formula, not the remediated one. This creates a situation where the test suite validates dead code while the live implementation (`decay_engine.py`) has its own test coverage in `test_abeyance_remediated.py`. The deprecated tests should be removed, not preserved.

---

## 4. Algorithmic Risks

### 4.1 Temporal Modifier Diurnal Component Is Fragile — **Severity: Moderate**

The temporal modifier includes a diurnal alignment factor:

```
diurnal = (1 + cos_sim(tod_a, tod_b)) / 2    in [0, 1]
```

This compares time-of-day between two fragments. Two events at the same time of day get `diurnal=1.0`, events 12 hours apart get `diurnal=0.0`. This assumes that failure correlation is strongest at matching times of day. For traffic-driven failures this is plausible. For hardware failures, configuration errors, or vendor defects, it is noise. The diurnal factor multiplies into the temporal modifier, which attenuates the raw composite score. A midnight hardware fault will be penalized when compared to a noon hardware fault of identical nature. The failure mode weight profiles do not modulate diurnal sensitivity.

### 4.2 Entity Extraction Determines Snap Quality — Single Point of Failure — **Severity: Severe**

The snap engine's Stage 1 (targeted retrieval) uses entity overlap to find candidates. If entity extraction fails or produces incomplete results, candidate retrieval returns nothing, and no snap evaluation occurs regardless of semantic similarity. The enrichment chain's entity extraction has two paths:

1. LLM structured extraction (primary)
2. Regex patterns (fallback)

The regex patterns are telecom-specific (cell IDs like `eNB_\d+`, site patterns like `SITE-[A-Z]{3}-\d+`). For evidence that does not match these patterns and where the LLM call fails, no entities are extracted, and the fragment becomes invisible to snap evaluation. The fragment will decay to zero without ever being evaluated against any candidate. This is a silent failure mode where potentially valuable evidence is permanently lost.

### 4.3 Sidak Correction Assumes Profile Independence — **Severity: Minor**

The Sidak correction adjusts thresholds assuming independent tests:

```
adjusted = 1 - (1 - base)^(1/K)
```

The five failure mode profiles are not independent — they share the same embedding components and entity overlaps, just with different weights. Sidak correction is conservative under positive dependence (Sidak, 1967), so the adjusted thresholds will be slightly stricter than necessary. This is the safe direction of error — it may miss some valid snaps rather than producing false positives. Acceptable but worth noting.

### 4.4 No Negative Evidence Mechanism — **Severity: Moderate**

The system can corroborate fragments (near-miss boost) and snap them (threshold crossing). It has no mechanism to *anti-corroborate* — to record that a fragment was investigated and found irrelevant. The decay function is the only mechanism for reducing fragment relevance, and it is time-based, not evidence-based. An operator who investigates a fragment and determines it is noise cannot accelerate its decay or mark it as "investigated, not relevant." The only escape is waiting for natural decay or manual status transition via operator action (INV-5 allows explicit operator action on SNAPPED fragments, but there is no API endpoint for operator-driven reclassification of ACTIVE fragments).

---

## 5. Scalability Threats

### 5.1 LLM Embedding Cost at Scale — **Severity: Critical**

The enrichment chain makes up to 4 LLM calls per fragment ingestion:
1. Entity extraction (LLM structured extraction)
2. Semantic embedding (content + entities)
3. Topological embedding (neighbourhood description)
4. Operational embedding (failure modes + fingerprint)

At the specified ingestion rate of 10,000 events/minute:
- 40,000 LLM calls/minute
- 2,400,000 LLM calls/hour
- 57,600,000 LLM calls/day

Even at $0.001 per embedding call (which is optimistic for structured extraction + embedding), this is **$57,600/day or $1.7M/month** in LLM API costs alone. This makes the system economically non-viable at the upper end of its own specified operating range. The design document specifies this rate as a target operating condition (§3.1) without acknowledging the cost implications.

### 5.2 Accumulation Graph Loads All Edges — **Severity: Severe**

`accumulation_graph.py`'s `detect_and_evaluate_clusters()` executes:

```python
stmt = select(AccumulationEdgeORM).where(
    AccumulationEdgeORM.tenant_id == tenant_id
)
edges = (await session.execute(stmt)).scalars().all()
```

This loads ALL accumulation edges for a tenant into memory. With 500K active fragments per tenant (§3.1 target) and up to 20 edges per fragment, this is up to 10 million edges loaded into Python memory for union-find processing. At ~200 bytes per edge ORM object, that is ~2GB of memory for a single cluster detection pass. This runs every time the `/accumulation-graph/clusters` endpoint is called or during maintenance.

### 5.3 Maintenance Edge Pruning Is O(n) Queries — **Severity: Severe**

`maintenance.py`'s `prune_stale_edges()` executes 2 SELECT queries per edge to check fragment scores:

```python
for edge in edges:
    frag_a = await session.execute(select(AbeyanceFragmentORM).where(...))
    frag_b = await session.execute(select(AbeyanceFragmentORM).where(...))
```

For a batch of 10,000 edges, this is 20,000 individual SELECT queries. This should be a single JOIN query. The current implementation will take minutes where a JOIN would take milliseconds.

### 5.4 IVFFlat Index Scaling — **Severity: Moderate**

The cold storage uses IVFFlat with `lists=100`. IVFFlat recall degrades as data grows unless the list count scales with `sqrt(n)`. At 5 million cold fragments per tenant, the optimal list count is ~2,236, not 100. The weekly rebuild job (§3.5) adjusts for count changes >20% but does not dynamically adjust the list parameter. This means cold storage ANN search recall will silently degrade as the archive grows.

### 5.5 No Connection Pooling for LLM Service — **Severity: Moderate**

The enrichment chain calls `self._llm_service.generate_embedding()` synchronously within an async context. There is no connection pooling, rate limiting, or circuit breaker on LLM calls. A burst of 200 concurrent fragment ingestions (the snap candidate limit) would fire 800 concurrent LLM calls. Most LLM providers will rate-limit or reject these, causing cascading fallback to hash embeddings or None embeddings, which then silently degrade all downstream scoring.

---

## 6. Failure Mode Analysis

### 6.1 LLM Service Outage — **Severity: Severe**

If the LLM service is unavailable:
- Entity extraction falls back to regex (partial, telecom-only)
- Semantic embedding: zero-filled, mask[0]=False
- Topological embedding: zero-filled, mask[1]=False
- Operational embedding: zero-filled, mask[3]=False

Result: 75% of the enriched embedding is zeros. Only the temporal sub-vector (256/1536 = 16.7%) carries signal. Cosine similarity between two fragments enriched during an LLM outage will be driven entirely by temporal proximity. Combined with the temporal modifier (which also emphasizes time alignment), the system degenerates to "things that happened at similar times are correlated." This will produce a flood of false snaps during any LLM outage.

The embedding mask exists to address this, but the snap engine does not consult it. `_cosine_similarity()` in `snap_engine.py` computes similarity on the full enriched embedding vector without checking `embedding_mask`. The mask is stored but never read.

### 6.2 Embedding Mask Is Stored But Not Used — **Severity: Critical**

This warrants its own finding. The v2.0 design specifies (§2.5):

> `embedding_mask = [semantic_valid, topo_valid, temporal_valid, operational_valid]`

The enrichment chain correctly computes and stores this mask. But no downstream consumer reads it. The snap engine computes cosine similarity on the full 1536-dim vector regardless of which sub-vectors are valid. Two fragments with `mask=[False, False, True, False]` (only temporal valid) will produce a cosine similarity score that the snap engine treats identically to two fragments with `mask=[True, True, True, True]` (all valid).

This means INV-11 ("Every similarity computation uses mathematically meaningful vectors") is **violated in practice** despite being satisfied at the storage layer. The mask exists. Nobody reads it.

### 6.3 Parquet Cold Storage Silent Error Swallowing — **Severity: Moderate**

```python
except Exception:
    continue
```

Line 303 of `cold_storage.py`. If a Parquet file is corrupted, has an incompatible schema, or contains malformed data, the error is silently swallowed and the file is skipped. No log message. No counter. No alert. The operator has no way to know that cold storage search results are incomplete due to corrupted archives.

### 6.4 Race Condition in Edge Eviction — **Severity: Moderate**

`accumulation_graph.py`'s `_enforce_edge_limit()` counts edges, finds the weakest, and deletes it in separate queries without row-level locking. Under concurrent snap evaluations for the same fragment, two processes could both count 20 edges, both decide to evict, and both delete edges — resulting in 18 edges instead of 20. This is a benign failure (under the limit) but indicates missing concurrency control.

### 6.5 No Idempotency on Snap Application — **Severity: Moderate**

`_apply_snap()` transitions both fragments to SNAPPED and creates a shared `hypothesis_id`. If the process crashes after transitioning fragment A but before transitioning fragment B, fragment A is SNAPPED with a hypothesis_id that references a non-SNAPPED fragment B. The write-ahead pattern ensures the state change is logged, but recovery requires detecting orphaned hypothesis_ids — a scenario not covered by the failure mode documentation (§6).

---

## 7. Observability Gaps

### 7.1 No Operational Metrics — **Severity: Severe**

The provenance tables provide forensic observability (explaining *why* something happened after the fact). But there are no operational metrics:
- No counters for fragments ingested/decayed/snapped per unit time
- No histograms of snap scores
- No gauge for active fragment count per tenant
- No latency tracking for enrichment chain, snap evaluation, or cluster detection
- No error rate tracking for LLM calls

An operator cannot answer "is the system healthy right now?" only "what happened to fragment X?" These are different questions. The system has forensic observability but not operational observability.

### 7.2 No Alerting on Anomalous Snap Rates — **Severity: Moderate**

If the snap threshold is miscalibrated or an LLM degradation causes embedding drift, the snap rate could spike (false positives) or drop to zero (false negatives). There is no mechanism to detect either condition. The system will silently produce bad results without any operator notification.

### 7.3 Maintenance Job Results Are Fire-and-Forget — **Severity: Moderate**

The maintenance endpoint returns counts (`{"decay": {"updated": 5000, "expired": 200}, ...}`), but these results are not persisted anywhere. There is no maintenance job history table. An operator cannot answer "when did the last decay pass run?" or "how many fragments have been expired this week?" without querying `fragment_history` and aggregating manually.

---

## 8. Economic Sustainability

### 8.1 Embedding Cost Dominates — **Severity: Critical**

As detailed in §5.1, the per-fragment embedding cost makes the system economically non-viable at scale. At the lower end of the operating range (100 events/minute), costs are manageable (~$576/day). At the upper end (10,000 events/minute), costs are catastrophic ($57,600/day). The design does not specify a cost model, embedding caching strategy, or tiered enrichment approach.

**Mitigations not present in the design:**
- Batch embedding (amortize per-call overhead)
- Embedding cache (identical content produces identical embeddings)
- Tiered enrichment (quick regex-only for low-confidence sources, full LLM for high-confidence)
- Local embedding models (eliminate API costs entirely)

### 8.2 Cold Storage Growth Is Unbounded in Practice — **Severity: Moderate**

Fragments expire after 730 days and move to cold storage. Cold storage has no expiration policy. At 10,000 events/minute sustained for 2 years, cold storage will contain ~10.5 billion fragments. The IVFFlat index on this volume, even with proper list tuning, will require significant memory and rebuild time.

---

## 9. Security Risks

### 9.1 Parquet Path Traversal — **Severity: Severe**

`cold_storage.py` constructs filesystem paths from tenant_id:

```python
def cold_storage_path(self, tenant_id: str, year: int, month: int) -> Path:
    return self.base_path / str(tenant_id) / str(year) / f"{month:02d}" / "fragments.parquet"
```

If `tenant_id` contains `../../../etc/`, the path resolves outside the intended directory. There is no sanitization of `tenant_id` before path construction. Similarly, `_load_tenant_fragments()` uses `search_root = self.base_path / str(tenant_id)` followed by `rglob("*.parquet")`, which would traverse the escaped directory.

The DB-backed primary path does not have this vulnerability (tenant_id is a query parameter, not a filesystem path). But the Parquet fallback is exploitable.

### 9.2 Embedding Vectors as Information Leakage — **Severity: Moderate**

Enriched embeddings encode content, entities, topology, and operational context into a 1536-dimensional vector. While embeddings are not directly invertible, research has demonstrated that LLM embeddings can be partially inverted to recover input text. The cold storage and fragment API expose raw embedding vectors. In a multi-tenant environment, if tenant isolation fails at any layer (application bug, SQL injection, direct DB access), embedding vectors from one tenant could be used to infer information about another tenant's operational context.

### 9.3 CMDB Export Sanitization Is Incomplete — **Severity: Minor**

`shadow_topology.py`'s `export_to_cmdb()` strips `evidence_summary` and `confidence` but retains `entity_identifier`, `entity_type`, `attributes`, `relationship_type`, and entity UUIDs. An entity's `attributes` (JSONB) could contain sensitive operational data that was merged during `get_or_create_entity()`. The sanitization filter is an allowlist of fields to *remove*, not a safelist of fields to *include*, making it fragile against future attribute additions.

---

## 10. Overall System Credibility

### The Core Question: Intelligence or Correlation?

Abeyance Memory performs **structured, multi-dimensional, time-weighted correlation detection with provenance tracking**. This is a legitimate and useful capability for a NOC platform. The implementation, post-remediation, is mathematically defensible in its core scoring mechanisms. The bounded arithmetic, write-ahead logging, and tenant isolation demonstrate engineering discipline.

What the system does **not** do:
- **Reason** about causal relationships (it measures similarity, not causation)
- **Discover** hidden structure (it finds statistical neighbors, not explanations)
- **Learn** from outcomes (the RLHF feedback endpoints exist on DecisionTrace, not on Abeyance fragments — the snap engine cannot improve its thresholds from operator feedback)
- **Reconstruct** incidents (the reconstruction service assembles a chronological timeline from provenance records — it does not infer missing events or causal chains)

### What Works

1. **Decay engine**: Mathematically sound, bounded, monotonic, auditable.
2. **Provenance architecture**: Append-only tables with full scoring breakdowns. Genuine forensic capability.
3. **Write-ahead pattern**: PostgreSQL-first, Redis-as-notification. Correct distributed systems thinking.
4. **Bounded resource model**: Hard limits on edges, clusters, batches, BFS expansion. The system will not run away.
5. **Tenant isolation**: Consistently enforced at every query in the remediated code.
6. **LME cluster scoring**: Mathematically superior to Noisy-OR, with correlation discount.
7. **Sidak correction**: Correct application of multiple comparison adjustment.

### What Does Not Work

1. **Topological dimension**: Built but disconnected. ~25% of the embedding and a key scoring weight contribute nothing.
2. **Embedding mask**: Stored but never consumed. INV-11 is violated at the scoring layer.
3. **Telemetry alignment**: Falls back to hash embeddings in production async context. Cross-modal search is broken.
4. **Operational fingerprinting**: Returns None for all fields because ITSM/KPI integrations are not wired. The operational similarity component of snap scoring is always 0.0.
5. **Weight profiles**: Arbitrary, untested, and unvalidated.
6. **Economic model**: Non-viable at the upper end of specified operating range.

---

## 11. Final Judgement

### 1. Is Abeyance Memory a defensible architecture?

**Conditionally yes.** The *design* is defensible — bounded scoring, provenance tracking, tenant isolation, write-ahead durability, and explicit resource limits demonstrate that the architect understood production systems engineering. The *implementation* has significant gaps (dead topology integration, unused embedding masks, broken telemetry alignment, N+1 queries) that undermine the design's promises. The architecture is defensible if the implementation catches up to the specification.

### 2. Could this system survive production scale?

**Not at the upper end of its specified range.** At 100 events/minute with a single tenant, the system would function. At 10,000 events/minute with 100 tenants, it would collapse under LLM costs, memory pressure from full-tenant edge loading, N+1 query performance, and IVFFlat index degradation. The scaling model needs a fundamental rethink around embedding economics and batch processing.

### 3. Would you approve this design as a principal engineer?

**I would approve the design with a mandatory pre-production remediation list:**

- Fix the enrichment chain topology expansion bug (Critical, line 124: pass `entity_identifiers` not `[]`)
- Make snap engine consume `embedding_mask` (Critical, otherwise INV-11 is theater)
- Replace telemetry aligner hash fallback with async-compatible LLM embedding (Severe)
- Wire shadow topology proximity into snap scoring to replace the Jaccard*0.8 proxy (Severe)
- Add batch/cached embedding strategy with cost ceiling (Critical for economic viability)
- Fix maintenance N+1 queries (Severe)
- Add operational metrics (counters, histograms, gauges) alongside provenance (Severe)
- Sanitize tenant_id in Parquet path construction (Severe, security)
- Remove or properly isolate the deprecated `abeyance_decay.py` and its tests (Minor)

I would **not** approve the system for production without these nine items resolved.

### 4. What percentage of the system is real capability vs conceptual illusion?

| Component | Real Capability | Assessment |
|-----------|:-:|---|
| Decay Engine | 95% | Sound math, bounded, auditable. Missing only operator-driven override. |
| Provenance Architecture | 90% | Comprehensive forensic capability. Missing operational metrics. |
| Write-Ahead / Durability | 95% | Correct pattern, tested, Redis correctly demoted. |
| Tenant Isolation | 90% | Consistent in DB layer. Parquet path traversal is a gap. |
| Snap Engine | 60% | Core scoring works. Topo dimension is a proxy. Mask ignored. Weights arbitrary. |
| Enrichment Chain | 45% | Entity extraction works. Topology expansion dead. Operational fingerprint empty. Embedding cost unaddressed. |
| Accumulation Graph | 75% | LME is sound. Cluster detection loads all edges. Edge pruning is O(n). |
| Shadow Topology | 30% | Built, tested, cycle-safe, and then *not used* by the one component that needs it. |
| Telemetry Alignment | 15% | Falls back to hash embeddings in production. Cross-modal search broken. |
| Cold Storage | 55% | DB path works. Parquet path has silent errors and security gap. No expiration. |
| Value Attribution | 50% | Correctly refuses fabricated baselines. Cannot compute real baselines yet. |
| Incident Reconstruction | 70% | Timeline assembly works. No causal inference. Post-hoc not real-time. |

**Weighted aggregate: 62% real capability, 38% gap.**

The gap is not uniformly distributed. The core scoring loop (decay + snap + provenance) is solid. The peripheral systems (topology integration, telemetry alignment, operational enrichment, economic viability) are where the implementation fails to deliver on the design's promises. The system is a **credible foundation** with **significant unfinished work** that has been architecturally specified but not yet built.

---

*Audit conducted 2026-03-15. All findings based on code as committed at `0e045e4`. This audit supersedes and extends the findings of the v1.0 forensic audit dated 2026-03-09.*
