# Abeyance Memory – Expert Feedback Review & Design Iteration v2

**Prepared:** 2026-03-12  
**Source LLD:** [ABEYANCE_MEMORY_LLD.md](file:///Users/himanshu/Projects/Pedkai/ABEYANCE_MEMORY_LLD.md)  
**Source Implementation Plan:** [abeyance_memory_implementation_plan.md](file:///Users/himanshu/Projects/Pedkai/abeyance_memory_implementation_plan.md)  
**Source Feedback:** [Abeyance Memory Feedback.md](file:///Users/himanshu/Downloads/Abeyance%20Memory%20Feedback.md)

---

## 1. Executive Summary

- **The expert feedback identifies real, actionable gaps** in both the LLD and Implementation Plan. The most critical findings involve: missing enrichment-state tracking, absence of human governance gates, near-miss runaway reinforcement risk, and the Implementation Plan's oversimplification of the Accumulation Graph and retrieval pipeline. These must be fixed before any implementation begins.
- **Several "architectural flaw" claims are overstated or miscategorised.** The feedback's initial critique of pgvector as a "vector database reintroduction" fundamentally misreads the LLD, which already specifies context-first targeted retrieval (§9, Stage 1) with vector similarity as **last-stage ranking**. The reviewer later acknowledged this, but the corrected version still carries residual bias. Similarly, the proposal to replace the Snap Engine with a probabilistic conditional-probability model is intellectually interesting but represents a **complete redesign** that is infeasible for v1 and unsupported by available training data.
- **High-value improvement ideas extracted from the feedback:** enrichment-state machine with persisted intermediate states; snap-cycle detection and score-capping; lazy decay computation; fragment deduplication via content hashing; topology snapshot versioning; a formal `DiscoveryReviewQueue` for human governance; and the Two-Speed Intelligence concept that separates immediate operational value (Incident Reconstruction) from long-horizon learning.
- **Recommended direction:** Incorporate 14 targeted LLD amendments (detailed in §3), reject the wholesale probabilistic-memory redesign for v1 but acknowledge it as a v2+ research direction, and restructure the Implementation Plan to reflect the corrected architecture.

---

## 2. Critical Assessment of Expert Feedback

### Table A — Implementation Plan Gaps/Risks

| # | Feedback Point | Key Quote/Excerpt | Assessment | Priority | Reasoning |
|:-:|---|---|:-:|:-:|---|
| A1 | **Vector DB retrieval order** — Blueprint describes `ivfflat` as primary lookup | *"Snap candidate retrieval becomes embedding-first instead of context-first"* | **Partially Agree** | High | The *Blueprint* does list the ivfflat index prominently, creating the impression of embedding-first retrieval. However, the **LLD §9 Stage 1** already specifies structured SQL query (tenant, decay, entity overlap, failure modes) as the candidate generator — vector similarity is Stage 2 scoring. The Plan should mirror this order explicitly, but the LLD itself is already correct. |
| A2 | **Enrichment as stateless DTO** — Blueprint treats enrichment as producing a single `EnrichedFragment` DTO | *"LLD describes state mutation per stage, while blueprint describes stateless transformation. This breaks enrichment auditability, stage recovery, enrichment reprocessing"* | **Agree** | Critical | The LLD's enrichment chain (§6) is strictly sequential: Resolve → Fingerprint → Classify → Embed. If Step 2 fails, Step 3 operates on incomplete data. The Implementation Plan must enforce persisted intermediate states. |
| A3 | **Shadow Topology export sanitisation** — Blueprint only defines `CMDB_EXPORT_LOG` | *"No component exists enforcing shadow_data → sanitisation → CMDB"* | **Partially Agree** | High | The LLD §8 specifies sanitisation logic and the `export_to_cmdb()` method (§14, line 1654-1672) explicitly strips evidence chains. The *Blueprint* understates this — it should mandate a `SanitisationLayer` as a distinct service boundary, but the LLD itself does specify the sanitisation contract. |
| A4 | **Accumulation Graph reduced to CTE + count** — Blueprint loses temporal gating, decay weighting, entity coherence | *"Converts a probabilistic inference engine into a graph density detector"* | **Agree** | High | The Blueprint's `HAVING count(*) >= 3` is a necessary but insufficient condition. LLD §10 specifies Noisy-OR/Dempster-Shafer cluster scoring and a cluster snap threshold of 0.70. The Plan must include these scoring mechanisms, not just connected-component detection. |
| A5 | **Cold storage fragments excluded from snap** — Blueprint never reinserts cold fragments into candidate set | *"Cold fragments can never participate in accumulation graphs"* | **Agree** | High | LLD §12 explicitly defines cold fragment participation through a two-stage metadata-match + embedding-comparison process with a `COLD_SNAP` bonus. The Blueprint must include this retrieval path. |
| A6 | **Missing human validation gates** | *"System could autonomously publish incorrect topology changes"* | **Agree** | Critical | The LLD's Hypothesis Lifecycle (§4 diagram) shows `CANDIDATE → CORROBORATED → ACCEPTED` but does **not** specify an analyst gate. This is a gap in both the LLD and the Plan. A `DiscoveryReviewQueue` is required. |
| A7 | **Infinite snap loop risk** — No loop guard for mutual near-miss boosting | *"Score inflation can create self-reinforcing clusters"* | **Agree** | Critical | The 1.15× near-miss boost (LLD §11) with no cap creates unbounded score inflation. Must add: `max_near_miss_count` cap, cycle detection in snap pairs, and an absolute score ceiling. |
| A8 | **Decay Engine race condition** — Async decay vs. concurrent snap reads | *"Non-deterministic snap outcomes"* | **Partially Agree** | Medium | PostgreSQL MVCC provides snapshot isolation for concurrent reads, so casual race conditions are unlikely. However, adding a `decay_version` or `last_decay_at` column for audit reproducibility is good practice. Low-risk change. |
| A9 | **Fragment explosion at scale** | *"10M+ fragments, O(n²) snap comparisons"* | **Partially Agree** | Medium | The LLD already limits targeted retrieval to 200 candidates (§9, line 848) and uses GIN + ivfflat indexes. Fragment pruning and semantic deduplication are valid additions but not a crisis — the Stage 1 query is already bounded. |
| A10 | **Kafka replay duplication** | *"No idempotency keys exist"* | **Agree** | High | No deduplication mechanism exists in either document. Must add a content-hash + source-ref uniqueness constraint. |

### Table B — LLD Weaknesses

| # | Feedback Point | Key Quote/Excerpt | Assessment | Priority | Reasoning |
|:-:|---|---|:-:|:-:|---|
| B1 | **Snap score mixes incompatible statistical scales** | *"Signals cannot be linearly combined without normalization models"* | **Partially Agree** | High | Valid concern. All four scoring components (cosine sim, topo proximity, Jaccard overlap, operational similarity) are already normalised to [0, 1] by the LLD's definitions (cosine similarity, inverted hop distance, Jaccard, cosine of fingerprint vectors). The temporal_weight multiplier is also [0, 1]. However, the LLD does not **explicitly document** this normalisation guarantee. Adding a formal normalisation specification is appropriate. |
| B2 | **Decay conflicts with long-horizon discovery** | *"Decay must be context dependent, not global"* | **Partially Agree** | Medium | The LLD already implements context-dependent decay via source-type-specific τ values (§5 table) and near-miss boosting, plus the Cold Storage tier (§12) for 180+ day fragments. The feedback's suggestion for a multi-tier memory model is already architecturally present but could be formalised into a clearer "memory stratification" section. |
| B3 | **Fragment granularity undefined** | *"Fragment size controls the entire behavior of the memory graph"* | **Agree** | High | The LLD defines source types but never specifies how a multi-comment ITSM ticket should be fragmented. Must add a formal fragmentation strategy section. |
| B4 | **Shadow Topology assumes static network graph** | *"Topology relationships can change hourly"* | **Partially Agree** | Medium | Telecom CMDB topology is snapshot-based and changes on the order of days/weeks, not hourly (traffic rerouting doesn't change the physical/logical topology). However, versioned topology snapshots would improve snap reproducibility. Add topology_version to fragments. |
| B5 | **Accumulation Graph confuses correlation with causation** | *"Co-occurrence is extremely common"* | **Partially Agree** | Medium | The LLD explicitly defers causal inference to PRODUCT_SPEC §8 (line 63). Abeyance Memory's purpose is to surface *hypotheses* that humans then validate. The Hypothesis Lifecycle's `CANDIDATE → CORROBORATED → ACCEPTED` pipeline plus the proposed `DiscoveryReviewQueue` mitigates this. The system is designed to be a hypothesis generator, not a causal reasoner. |
| B6 | **Discovery logic ignores negative evidence** | *"Without negative evidence, discovery becomes confirmation bias"* | **Agree** | High | This is a genuine gap. The Noisy-OR fusion (§10) only aggregates supporting evidence. Must add a negative-evidence tracking mechanism: count how often entity co-occurrence occurs *without* corroborating symptoms, and factor this into cluster scoring. |
| B7 | **Graph growth unbounded** | *"100M fragments, billions of edges"* | **Partially Agree** | Medium | Fragment expiration at decay < 0.1 (§11) and affinity edge cleanup already bound graph growth. However, explicit edge-pruning policy and cluster-freezing mechanism should be documented. |
| B8 | **Near-miss boost risks runaway reinforcement** | *"Creates a positive feedback loop"* | **Agree** | Critical | See A7 above. Must add saturation limits. |
| B9 | **LLM classification treated as deterministic** | *"A model update may silently change failure classifications"* | **Partially Agree** | Medium | PedkAI's sovereignty guardrails and LLMService abstraction already version-lock models per deployment. However, adding `llm_model_version` to fragment metadata and a classification-drift monitoring metric is good practice. |
| B10 | **Human governance not integrated** | *"Human validation must be integrated as a first-class system component"* | **Agree** | Critical | See A6. Must add to LLD. |

### Table C — High-Value Improvement Ideas

| # | Idea | Source in Feedback | Technical Value | Trade-offs | Assessment |
|:-:|---|---|---|---|:-:|
| C1 | **Two-Speed Intelligence** — Day-1 "Operational Context Engine" + long-horizon learning | Lines 3652–3894 | **Extremely High.** Solves the commercialisation problem: operators get instant value from event-timeline reconstruction and blast-radius queries; learning accumulates in background. | Requires careful separation of synchronous (index-lookup) and asynchronous (snap/accumulation) pipelines. | **Accept — incorporate into LLD §1 and §16 as a guiding principle.** |
| C2 | **Incident Reconstruction** as the day-1 killer feature | Lines 3902–4098 | **High.** Leverages existing fragment store + topology + time indexes. No ML/learning required. Operators universally need this. | Must not distract from the core Abeyance Memory snap engine as a Phase 1 building block. Already partially covered by the SITREP generation in Layer 4. | **Accept — add to LLD as a new §12.5 "Instant Incident Reconstruction" section and add corresponding tasks to Phase 1.** |
| C3 | **Enrichment state machine** with persisted intermediate states | Lines 95–139 | **High.** Enables retry, audit trail, and partial-enrichment detection. | Minor schema change: add `enrichment_state` enum to `AbeyanceFragmentORM`. Slight increase in write operations. | **Accept.** |
| C4 | **Lazy decay computation** at query time vs. daily batch | Lines 515–537 | **Medium.** Eliminates daily full-table scan. | Increases query complexity; every read must compute `base_relevance × 1.15^near_miss × exp(-age/τ)`. Hot-path performance may suffer. | **Accept as optimisation option, keep daily batch as default for v1.** Lazy decay can be a Phase 5 optimisation. |
| C5 | **Fragment deduplication** via content hash | Lines 398–421 | **High.** Prevents Kafka replay creating duplicate fragments. Simple to implement. | Minimal trade-off. SHA-256(source_type + source_ref + timestamp + raw_content) as uniqueness constraint. | **Accept.** |
| C6 | **Topology snapshot versioning** | Lines 444–457, 1361–1396 | **Medium-High.** Improves snap reproducibility. | Requires versioned Shadow Topology snapshots and fragment-to-topology-version linkage. Storage overhead modest. | **Accept — add `topology_snapshot_version` to fragment schema.** |
| C7 | **Probabilistic hypothesis memory** replacing snap scoring | Lines 1637–2370 | **Intellectually compelling but premature for v1.** Claims that probabilistic conditional memory (`P(B|A, Context)`) is simpler and more accurate. | Requires production event-chain data that doesn't exist yet. The feedback itself identifies hypothesis explosion as an unsolved scaling problem. Eliminates the snap engine, accumulation graph, and decay engine — effectively a complete redesign. V1 cannot be built this way. | **Reject for v1. Flag as v2+ research direction.** |
| C8 | **Candidate Generation → Statistical Promotion** pattern for hypothesis control | Lines 3021–3322 | **High for future phases.** Two-stage funnel: ephemeral candidate counters → promotion threshold → persistent hypothesis. Solves hypothesis explosion. | Only useful if/when the probabilistic memory model (C7) is adopted. | **Accept as design input for v2 roadmap.** |
| C9 | **Event-centric indexing** (time × topology × event-type) for instant reconstruction | Lines 4339–4507 | **Medium.** Proposes replacing fragment comparison with pre-indexed multi-dimensional lookups. | The LLD's existing GIN indexes + entity-ref table + timestamp queries already provide this capability. The suggestion reframes existing architecture rather than proposing something new. | **Acknowledge — already present in LLD §14 indexes. No change needed.** |
| C10 | **Negative evidence tracking** in Noisy-OR scoring | Lines 1431–1457 | **High.** Prevents confirmation bias in accumulation graph. | Requires tracking non-occurrence: when entities co-appear but do NOT produce symptoms. Adds complexity to cluster scoring. | **Accept — add to LLD §10.** |

---

## 3. Proposed Updates to the LLD

### 3.1 §1 Purpose & Scope — Add Two-Speed Intelligence Principle

**Location:** After line 66, before "These systems interact with Abeyance Memory"

**New content:**

```markdown
### Two-Speed Intelligence Design Principle

Abeyance Memory operates as a two-speed system:

1. **Immediate Operational Intelligence (Day 1):** Fragment storage, 
   enrichment, and multi-dimensional indexing (time × topology × event-type)
   enable instant incident reconstruction, blast-radius queries, and 
   cross-domain event-timeline generation. This requires no learning 
   period — it works from the moment data is ingested.

2. **Long-Horizon Learning Intelligence (Months–Years):** The snap engine,
   accumulation graph, and decay engine continuously discover hidden 
   relationships. This intelligence compounds over time, building the 
   Shadow Topology flywheel and the competitive moat.

Both layers share the same fragment store and enrichment chain. The 
immediate layer is the product's commercial entry point; the learning 
layer is the moat builder. Implementation phases must deliver the 
immediate layer first.
```

**Rationale:** Feedback lines 3652–3654 correctly identify that the LLD conflates these two timelines. Separating them explicitly resolves the "how do you make it successful quickly?" question without compromising the long-term architecture.

---

### 3.2 §5 Fragment Model — Add Enrichment State, Dedup Hash, and Topology Version

**Location:** Within the `ABEYANCE_FRAGMENT` ER diagram (line 263–284)

**New fields to add:**

```markdown
enum enrichment_state "RAW | RESOLVED | FINGERPRINTED | CLASSIFIED | EMBEDDED"
text content_hash "SHA-256(source_type + source_ref + event_timestamp + raw_content) — UNIQUE per tenant"
int topology_snapshot_version "Version of Shadow Topology used during enrichment"
text llm_model_version "Model version used for entity extraction and embedding"
uuid parent_fragment_id "FK → abeyance_fragment.fragment_id. NULL for primary fragments. Set for sub-fragments (e.g., resolution notes extracted from TICKET_TEXT). Both parent and child share the same source_ref."
```

**Also add a UNIQUE constraint note:**

```markdown
> **Deduplication invariant**: `(tenant_id, content_hash)` is UNIQUE. 
> If a fragment with the same hash already exists, the ingestion pipeline 
> discards the duplicate. This prevents Kafka replay scenarios from 
> creating false snaps through duplicate fragments.
```

**Rationale:** Addresses feedback items A2 (enrichment state), A10 (deduplication), B4 (topology versioning), and B9 (LLM version tracking).

---

### 3.3 §5 Fragment Model — Add Fragmentation Strategy

**Location:** New subsection after "Source Type Characteristics" table (after line 314)

**New content:**

```markdown
### Fragmentation Strategy

Each source type has a defined fragmentation rule. This determines how 
raw evidence is divided into atomic fragments:

| Source Type | Fragmentation Rule | Rationale |
|---|---|---|
| `TICKET_TEXT` | One fragment per ticket. Resolution notes are **always** extracted as a separate sub-fragment linked to the parent via `parent_fragment_id = <original ticket fragment UUID>`. Both fragments share the same `source_ref` (ticket ID). | Tickets are natural units of investigation. Resolution notes contain distinct diagnostic knowledge (fix actions, root cause confirmation) that must be independently retrievable while maintaining traceability to the originating ticket. |
| `ALARM` | One fragment per alarm event (raise or clear). | Alarms are inherently atomic. |
| `TELEMETRY_EVENT` | One fragment per detected anomaly (not per data point). Anomaly detection occurs upstream in Layer 1. | Raw telemetry volume is too high; only statistically significant deviations become fragments. |
| `CHANGE_RECORD` | One fragment per change ticket. | Changes are atomic operational events. |
| `CLI_OUTPUT` | One fragment per pasted CLI block within a ticket. | CLI output blocks are self-contained diagnostic snapshots. |
| `CMDB_DELTA` | One fragment per detected attribute change or relationship change. | Each delta is a single structural event. |

> **Anti-pattern**: Never fragment at the sentence level. Sentence-level 
> fragmentation creates O(n²) fragment growth and produces spurious 
> affinity edges from partial vocabulary overlap.
```

**Rationale:** Addresses feedback item B3. Fragment granularity directly controls system behaviour.

---

### 3.4 §6 Enrichment Chain — Add State Machine Specification

**Location:** Replace the simple flow diagram (lines 324–341) with enriched version

**New content to add after the existing flow diagram:**

```markdown
### Enrichment State Machine

Each fragment transitions through explicit enrichment states. No state 
may be skipped. If a step fails, the fragment remains at its current 
state and is queued for retry.

| State | Transition | Trigger | Failure Behaviour |
|---|---|---|---|
| `RAW` → `RESOLVED` | Entity Resolution completes | Step 1 output | Retry with exponential backoff. After 3 failures, mark as `ENRICHMENT_FAILED` with state = `RAW`. |
| `RESOLVED` → `FINGERPRINTED` | Operational Fingerprinting completes | Step 2 output | Retry. If external sources (ITSM, KPI) are unavailable, create fingerprint with `partial: true` flag and proceed. |
| `FINGERPRINTED` → `CLASSIFIED` | Failure Mode Classification completes | Step 3 output | Deterministic — should not fail. If rules produce no tags, set `failure_mode_tags = {"tags": [], "unclassified": true}`. |
| `CLASSIFIED` → `EMBEDDED` | Both embeddings computed | Step 4 output | Retry LLM embedding call. If persistent failure, compute raw embedding only and set `enriched_embedding = null`. Fragment enters abeyance with reduced snap eligibility. |

Fragments with `enrichment_state != EMBEDDED` are excluded from snap 
evaluation. A background worker retries failed enrichments hourly.
```

**Rationale:** Addresses feedback item A2. Prevents corrupted fragments from entering the snap pipeline.

---

### 3.5 §9 Snap Engine — Add Score Normalisation Specification and Loop Guards

**Location:** After the scoring formula (line 866) and after Stage 3 thresholds (line 914)

**New content — normalisation guarantee:**

```markdown
### Signal Normalisation Guarantee

All scoring components are normalised to [0, 1] before weighted combination:

| Signal | Normalisation | Range |
|---|---|---|
| `cosine_sim(enriched)` | Cosine similarity output | [-1, 1] → clamp to [0, 1] |
| `topological_proximity` | `min(1.0, 1.0 / shortest_path_hops)`. Direct connection = 1.0, 2 hops = 0.5, no path = 0.0 | [0, 1] |
| `entity_overlap_jaccard` | Standard Jaccard index | [0, 1] |
| `operational_context_sim` | Cosine similarity of fingerprint vectors | [-1, 1] → clamp to [0, 1] |
| `temporal_weight` | Product of three [0, 1] factors: decay × change bonus × diurnal alignment | [0, 1] |

> **Invariant**: `snap_score ∈ [0, 1]` for all inputs. Any implementation 
> producing scores outside this range has a normalisation bug.
```

**New content — loop guards (after line 914):**

```markdown
### Snap Loop Protection

The following safeguards prevent runaway reinforcement in the snap engine:

1. **Near-miss count cap**: `max_near_miss_count = 10`. Beyond this, 
   additional near-misses do not boost relevance. At cap: 
   `effective_boost = 1.15^10 ≈ 4.05×`.

2. **Absolute decay score ceiling**: `max_current_decay_score = 5.0`. 
   Regardless of near-miss boosts, no fragment's computed decay score 
   may exceed this value.

3. **Snap cycle detection**: When fragment F_new snaps to F_stored, 
   record the directed pair `(F_new, F_stored)` in the snap history. 
   If F_stored has already snapped to F_new (directly or transitively 
   within the same hypothesis), suppress the snap and log a cycle warning.

4. **Maximum fragment degree**: A fragment may participate in at most 
   `max_snap_degree = 15` snap relationships. Beyond this, new snaps 
   involving this fragment are evaluated but not executed — they create 
   affinity edges instead. This prevents "hub" fragments from 
   distorting the accumulation graph.
```

**Rationale:** Addresses feedback items B1 (normalisation) and A7/B8 (loop protection). These are Critical-priority fixes.

---

### 3.6 §10 Accumulation Graph — Add Entity Coherence, Temporal Gating, and Negative Evidence

**Location:** After the cluster detection algorithm (line 996)

**New content:**

```markdown
### Cluster Quality Filters

Connected components detected by the recursive CTE must pass additional 
quality filters before cluster scoring:

1. **Temporal span limit**: All fragments in the cluster must have 
   `event_timestamp` within a 90-day window. Clusters spanning longer 
   periods are split at the largest temporal gap.

2. **Entity coherence**: At least 50% of the fragments in the cluster 
   must share at least one entity in their `topological_neighbourhood`. 
   Clusters of fragments from completely disjoint network regions are 
   rejected as coincidental.

3. **Failure mode consistency**: The cluster's fragments must include 
   at least 2 fragments with compatible `failure_mode_tags`. A cluster 
   of fragments with entirely unrelated failure modes is deprioritised 
   (scoring weight reduced by 0.5×).

### Negative Evidence in Cluster Scoring

To prevent confirmation bias, cluster scoring must account for 
counter-evidence:

- For each entity pair (E_a, E_b) in a cluster, track the 
  **non-occurrence count**: the number of times E_a appeared in a 
  fragment without E_b appearing in any temporally proximate fragment 
  (within τ_base days).
- Adjusted Noisy-OR: 
  `P_adjusted = P_noisy_or × (co_occurrence_count / (co_occurrence_count + non_occurrence_count))`
- This ensures that entities which frequently appear independently 
  do not produce inflated cluster scores.
```

**Rationale:** Addresses feedback items A4 (accumulation graph oversimplification) and B6 (negative evidence tracking).

---

### 3.7 §4 Architecture Overview — Add Discovery Review Queue

**Location:** Add to the Architecture Overview diagram (line 175-176) and add a new subsection

**New mermaid node** in the architecture diagram:

```
HL -->|"Discovery"| DRQ[Discovery Review Queue<br/>Analyst Validation]
DRQ -->|"Approved"| ST
DRQ -->|"Approved"| VA
```

**New subsection after §13 or as §13.5:**

```markdown
### Human Governance — Discovery Review Queue

All discoveries that would modify the Shadow Topology or trigger CMDB 
exports must pass through the Discovery Review Queue:

| Discovery Confidence | Routing |
|---|---|
| ≥ 0.90 | Auto-approved for Shadow Topology enrichment. Analyst notified. CMDB export still requires explicit approval. |
| 0.75 – 0.89 | Queued for analyst review. No topology or CMDB action until approved. |
| 0.60 – 0.74 | Low-confidence alert. Analyst can investigate or dismiss. No automatic action. |
| < 0.60 | Logged only. No notification. |

**Queue Schema:**

| Field | Type | Purpose |
|---|---|---|
| `review_id` | UUID PK | Unique review request |
| `hypothesis_id` | UUID FK | The hypothesis under review |
| `confidence` | float | Evidence fusion confidence |
| `auto_approved` | boolean | True if confidence ≥ 0.90 |
| `analyst_decision` | enum | PENDING / APPROVED / REJECTED / DEFERRED |
| `analyst_id` | text | Who reviewed |
| `decision_at` | timestamp | When reviewed |
| `decision_rationale` | text | Why approved/rejected |

> **Design principle**: Abeyance Memory is a hypothesis generator, not 
> an autonomous topology mutator. Discoveries are suggestions until a 
> human confirms them. This is a telecom-grade reliability requirement.
```

**Rationale:** Addresses feedback items A6 and B10. Critical for production deployment in telecom environments.

---

### 3.8 §12 Long-Horizon Retrieval — Add Cold Fragment Snap Participation

**Location:** Strengthen existing §12 content (lines 1122-1131)

**New explicit mechanism:**

```markdown
### Cold Fragment Snap Participation (Explicit)

Cold fragments participate in snap evaluation via a two-stage gated process:

1. **Stage 1 — Metadata match (in PostgreSQL):** The cold fragment metadata 
   table (entity IDs, failure mode tags, tenant ID) is queried during 
   Stage 1 targeted retrieval alongside hot/warm fragments. Cold metadata 
   rows carry a `storage_tier = 'COLD'` flag.

2. **Stage 2 — On-demand retrieval:** If a cold metadata row passes the 
   entity/failure-mode filter, retrieve the compressed embedding from 
   Parquet/S3. Compute snap score against the new fragment.

3. **Cold snap bonus:** If a cold fragment snaps (score ≥ 0.75), the 
   resulting hypothesis receives a `COLD_SNAP` tag and elevated 
   significance. The hypothesis is routed to the Discovery Review Queue 
   with explicit commentary: "Evidence separated by N months connected — 
   high-value long-horizon discovery."

4. **Cold fragment reinsertion:** On cold snap, the cold fragment is 
   promoted back to the warm tier for 30 days to enable further 
   accumulation graph participation. After 30 days without additional 
   snaps, it returns to cold.

> **Performance guard**: At most 50 cold fragment embeddings are retrieved 
> per snap evaluation cycle. If metadata matching produces more than 50 
> cold candidates, rank by entity overlap and retrieve top 50.
```

**Rationale:** Addresses feedback item A5. The LLD already describes this but the Implementation Plan omitted it entirely.

---

### 3.9 §14 Database Indexes — Add Dedup and State Indexes

**Location:** After existing index definitions (line 1739)

```sql
-- Fragment deduplication
CREATE UNIQUE INDEX idx_fragment_dedup 
    ON abeyance_fragment(tenant_id, content_hash);

-- Enrichment state processing
CREATE INDEX idx_fragment_enrichment_state 
    ON abeyance_fragment(enrichment_state) 
    WHERE enrichment_state != 'EMBEDDED';

-- Cold fragment metadata
CREATE INDEX idx_fragment_cold_metadata 
    ON abeyance_fragment(tenant_id, snap_status) 
    WHERE snap_status = 'COLD';
```

---

### 3.10 Add New Section: §12.5 Instant Incident Reconstruction

**Location:** New section between §12 and §13

> [!IMPORTANT]
> **MANDATORY FEATURE — Must ship before any client demo.** Cross-service
> propagation path inference (Option B) is required. Phased delivery:
> Phase 1a delivers time-ordered retrieval; Phase 1b adds propagation
> path inference once Shadow Topology is operational. Both phases must
> complete before client-facing deployment.

````markdown
## 12.5 Instant Incident Reconstruction

### Purpose

Incident Reconstruction is Abeyance Memory's Day-1 value delivery 
mechanism and the primary commercial entry point. It requires no 
learning period — it works from the moment fragments are ingested.

### How It Works

Given an incident trigger (time window + seed entity/service + topology radius):

1. **Time-window query**: Retrieve all fragments with `event_timestamp` 
   within the specified window (default: seed event ±15 minutes).
2. **Topology-radius filter**: Filter to fragments whose entities are 
   within N hops (default: 3) of the seed entity in the Shadow Topology.
3. **Sort by time**: Order surviving fragments chronologically.
4. **Propagation path inference** *(mandatory)*: Using the Shadow 
   Topology, construct the shortest topological path connecting 
   consecutive fragments. Output includes the physical/logical path 
   showing how the fault cascaded through the network.
5. **Output**: A structured incident timeline showing the probable 
   cascade: root event → intermediate events → customer-visible impact,
   including the network propagation path between each step.

### Phased Delivery

| Sub-Phase | Deliverable | Dependency | Status |
|---|---|---|---|
| **Phase 1a** | Time-ordered fragment retrieval + topology-radius filter | Fragment schema (T-AM-14) | URGENT |
| **Phase 1b** | Cross-service propagation path inference | Shadow Topology 2-hop API (T-AM-03) | URGENT — blocks client demos |

Phase 1a provides a working API endpoint that returns flat 
time-ordered events. Phase 1b upgrades the same endpoint to include 
`propagation_path` in the response. The API contract supports both: 
Phase 1a returns `"propagation_path": null`; Phase 1b populates it.

### Performance Target

< 500ms for a 3-hop, 30-minute window query against 1M fragments
(including propagation path computation).

### API Endpoint

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/v1/abeyance/incident-reconstruction` | POST | Generate incident timeline with propagation path |

### Input Schema

```json
{
  "seed_entity_id": "uuid",
  "time_window_start": "ISO-8601",
  "time_window_end": "ISO-8601",
  "topology_radius_hops": 3,
  "include_service_impact": true
}
```

### Output Schema (Phase 1b)

```json
{
  "incident_timeline": [
    {
      "timestamp": "2026-03-10T09:14:52Z",
      "event_type": "fiber_alarm",
      "entity": "OLT-882",
      "entity_id": "uuid",
      "fragment_id": "uuid"
    }
  ],
  "propagation_path": [
    {
      "from_entity": "OLT-882",
      "to_entity": "Router-342",
      "relationship_type": "fiber_segment",
      "relationship_id": "N-441",
      "hops": 1
    }
  ],
  "affected_services": ["Broadband Auth"],
  "blast_radius": {
    "devices": 4,
    "services": 2,
    "regions": ["North"]
  }
}
```

### Why This Is Not a Snap

Incident Reconstruction is a **query**, not a discovery. It does not 
create hypotheses, modify the accumulation graph, or affect fragment 
scores. It simply retrieves and orders existing fragments. The snap 
engine discovers hidden relationships autonomously; Incident 
Reconstruction answers an operator's explicit question.
````

**Rationale:** Addresses feedback item C2. This is the day-1 commercial entry point. Cross-service propagation path inference is mandatory before client demos (user decision 2026-03-12).

---

## 4. Impact on the Implementation Plan

### Mapping Table — LLD Changes to Implementation Plan Tasks

| LLD Change | Affected Plan Tasks | Required Action |
|---|---|---|
| **Two-Speed Intelligence principle (§1)** | Overall Phase ordering | Restructure: Phase 1 must deliver Incident Reconstruction alongside foundational schema. |
| **Enrichment state machine (§6)** | T-AM-15, T-AM-16, T-AM-17, T-AM-18, T-AM-19, T-AM-20, T-AM-21 (all Phase 2) | Add `enrichment_state` transitions to each step. Add retry worker. New task: **T-AM-42**: Enrichment retry background worker. |
| **Fragment dedup hash (§5)** | T-AM-14 (Fragment ORM) | Add `content_hash` field and UNIQUE constraint. Minor schema change. |
| **Topology version (§5)** | T-AM-14, T-AM-01 | Add `topology_snapshot_version` to fragment schema and Shadow Topology versioning mechanism. New task: **T-AM-43**: Shadow Topology version-stamping. |
| **LLM model version (§5)** | T-AM-15 | Add `llm_model_version` to fragment schema. Trivial field addition. |
| **Fragmentation strategy (§5)** | T-AM-15 (Entity Resolution) | Blueprint Step 2 must implement per-source-type fragmentation rules before enrichment. |
| **Score normalisation spec (§9)** | T-AM-24 (Evidence Scoring) | Explicit clamping logic in `_score_pair()`. Test assertion: all scores ∈ [0, 1]. |
| **Snap loop guards (§9)** | T-AM-26, T-AM-38 | Add `max_near_miss_count`, `max_decay_score`, cycle detection, `max_snap_degree`. New task: **T-AM-44**: Snap loop guard implementation + tests. |
| **Cluster quality filters (§10)** | T-AM-28, T-AM-29 | Add temporal span limit, entity coherence check, failure mode consistency filter to cluster evaluation. |
| **Negative evidence (§10)** | T-AM-29 | Add non-occurrence tracking. Modify Noisy-OR formula. New task: **T-AM-45**: Negative evidence counter + adjusted Noisy-OR. |
| **Discovery Review Queue (§4/§13.5)** | New Phase | New tasks: **T-AM-46**: DiscoveryReviewQueue schema + API. **T-AM-47**: Analyst approval workflow integration. Must gate Phase 6 (CMDB export) behind this. |
| **Cold fragment snap (§12)** | T-AM-33 | Ensure cold fragment metadata is included in targeted retrieval. Add cold-to-warm promotion logic. |
| **Incident Reconstruction (§12.5)** | New Phase 1 deliverable — **URGENT, blocks client demos** | New tasks: **T-AM-48**: Incident Reconstruction query engine (Phase 1a: time-ordered retrieval). **T-AM-49**: `/incident-reconstruction` API endpoint. **T-AM-50**: Cross-service propagation path inference (Phase 1b: requires T-AM-03). |

### Tasks That Remain Stable

The following Implementation Plan tasks are **unchanged** by the LLD amendments:

- T-AM-01 through T-AM-06 (Shadow Topology foundation) — stable
- T-AM-07 through T-AM-13 (Value Attribution) — stable
- T-AM-22 (Temporal encoding math) — stable
- T-AM-23 (Targeted Retrieval SQL) — stable (already context-first)
- T-AM-30, T-AM-31 (Decay computation) — stable for v1 (lazy decay deferred to v2)
- T-AM-32 (Cold storage pipeline) — stable
- T-AM-34 through T-AM-36 (Validation) — stable but test suite must cover new invariants

### Revised Phase Structure

| Phase | Name | Key Deliverables | New/Changed |
|:-:|---|---|---|
| **1a** | Foundation + Basic Incident Reconstruction | Fragment schema (with enrichment state, dedup hash, topology version, parent_fragment_id), Shadow Topology (with versioning), **Incident Reconstruction time-ordered retrieval** | 🆕 Incident Reconstruction Phase 1a |
| **1b** | Propagation Path Inference (**URGENT — blocks client demos**) | Cross-service propagation path using Shadow Topology shortest-path. Upgrades Incident Reconstruction endpoint. | 🆕 Mandatory before any client-facing deployment |
| **2** | Enrichment Chain | 4-step enrichment with **state machine**, retry worker, fragmentation strategy enforcement | 🔄 State machine + retry worker added |
| **3** | Snap Engine | Targeted retrieval, evidence scoring (with **normalisation guarantees**), snap decision (with **loop guards**) | 🔄 Loop guards + normalisation spec added |
| **4** | Accumulation Graph | Affinity edges, cluster detection (with **quality filters + negative evidence**), Evidence Fusion | 🔄 Quality filters + negative evidence added |
| **4.5** | **Human Governance** | Discovery Review Queue, analyst approval workflow | 🆕 Entirely new phase |
| **5** | Decay + Cold Storage | Decay computation, cold storage pipeline (with **cold fragment snap participation**) | 🔄 Cold snap reinsertion added |
| **6** | Value Attribution + CMDB Export | Discovery Ledger, CMDB export (gated by Phase 4.5 review queue), reference tagging, dashboards | 🔄 Now depends on Phase 4.5 |
| **7** | Validation | Ground truth testing, parameter tuning, loop guard testing, negative evidence testing | 🔄 Expanded test scope |

### Timeline Impact

- **Net new tasks**: 9 (T-AM-42 through T-AM-50)
- **Estimated additional effort**: ~30 engineering-days across new tasks
- **Critical path for client demos**: Phase 1a + 1b must complete before any client-facing deployment. Phase 1b depends on Shadow Topology (T-AM-01 through T-AM-03). Estimated: ~17 days from start for Phase 1a+1b.
- **Critical path for Phase 6**: Phase 4.5 (Discovery Review Queue) adds ~10 days before Phase 6. Total timeline extension is modest.
- **Risk reduction**: The loop guards, enrichment state machine, and human governance gates significantly reduce the probability of production failures, which would cause far larger delays than the upfront investment.

---

## 5. Next Steps & Roadmap

### Immediate Actions (Next 48–72 Hours)

| # | Action | Owner | Deliverable | Deadline |
|:-:|---|---|---|---|
| 1 | Review and approve this feedback assessment | Himanshu | Approved/amended feedback review | 2026-03-13 |
| 2 | Produce **ABEYANCE_MEMORY_LLD_v2.md** incorporating all accepted changes from §3 | AI Agent (Antigravity) | Updated LLD document | 2026-03-14 |
| 3 | Produce **abeyance_memory_implementation_plan_v2.md** reflecting revised phases and 8 new tasks | AI Agent (Antigravity) | Updated implementation plan | 2026-03-14 |
| 4 | Add new tasks T-AM-42 through T-AM-49 to the task backlog with dependencies | AI Agent | Task backlog in plan v2 | 2026-03-14 |

### Medium-Term Actions (Next 1–2 Weeks)

| # | Action | Owner | Deliverable |
|:-:|---|---|---|
| 5 | Execute Phase 1 implementation (Fragment schema + Shadow Topology + Incident Reconstruction) | AI Agents + Himanshu review | Working ORM models, migrations, Incident Reconstruction API |
| 6 | Design the Discovery Review Queue UX/workflow | Himanshu (product decision) | Review queue specification |
| 7 | Validate Incident Reconstruction performance against 1M simulated fragments | AI Agent (Validation Agent) | Performance benchmark report |

### Research Directions (v2+ Roadmap)

| Topic | Source | Priority | Notes |
|---|---|---|---|
| Probabilistic hypothesis memory (conditional `P(B\|A, Context)`) | Feedback lines 1637–2370 | v2 Research | Only viable after production snap data exists. Requires resolved hypothesis explosion challenge. |
| Candidate Generation → Statistical Promotion pattern | Feedback lines 3021–3322 | v2 Design | Prerequisite for hypothesis memory. Design the ephemeral candidate counter architecture. |
| Lazy decay (query-time computation) | Feedback lines 515–537 | v2 Optimisation | Benchmark against daily batch at telecom scale before committing. |
| Incremental graph engine replacing recursive CTE | Feedback lines 493–511 | v2 if scaling demands | Monitor CTE performance in Phase 4. Switch to streaming clustering only if CTE exceeds 500ms at production edge counts. |

### Resolved Decisions (2026-03-12)

| # | Question | Decision | Impact |
|:-:|---|---|---|
| 1 | **Discovery Review Queue auto-approval threshold** | **0.90 confirmed.** Discoveries with confidence ≥ 0.90 are auto-approved for Shadow Topology enrichment. CMDB export still requires explicit analyst approval at all confidence levels. | No change to proposed LLD text — already specified at 0.90. |
| 2 | **Incident Reconstruction scope** | **Option B (cross-service propagation path inference) is mandatory.** Must ship before any client demo. Phased delivery accepted: Phase 1a = time-ordered retrieval, Phase 1b = propagation path. Both must complete before client deployment. | New task T-AM-50 added. Phase 1 split into 1a/1b. Marked URGENT on roadmap. |
| 3 | **TICKET_TEXT fragmentation — resolution notes** | **Resolution notes are always extracted as sub-fragments**, linked to the parent ticket fragment via `parent_fragment_id`. Both fragments share the same `source_ref` (ticket ID). | `parent_fragment_id` field added to fragment schema. Fragmentation strategy table updated. |

### Proposed New File Names and Paths

| Document | Path |
|---|---|
| Revised LLD (v2) | `/Users/himanshu/Projects/Pedkai/ABEYANCE_MEMORY_LLD_v2.md` |
| Revised Implementation Plan (v2) | `/Users/himanshu/Projects/Pedkai/abeyance_memory_implementation_plan_v2.md` |
| This feedback review (current document) | `/Users/himanshu/Projects/Pedkai/abeyance_memory_feedback_review_v2.md` |
| Risk Register | `/Users/himanshu/Projects/Pedkai/abeyance_memory_risk_register.md` (to be created during Phase 1) |

---

## 6. Appendix — Rejected Ideas & Rationale

| # | Rejected Idea | Source | Reason for Rejection |
|:-:|---|---|---|
| R1 | **Replace snap engine with probabilistic conditional memory** (`P(B\|A)` model) | Feedback lines 1637–2370 | Complete architectural redesign. Requires production event-chain data that doesn't exist yet. The feedback itself identifies hypothesis explosion as an unsolved problem. Accepted as v2+ research direction, but implementing it now would delay v1 by 6+ months with no guaranteed improvement. |
| R2 | **Replace PostgreSQL recursive CTE with RedisGraph/TigerGraph** | Feedback line 937 | Introduces a new operational dependency. LLD Appendix B explicitly rejects this (line 2001): "No new databases. Operational simplicity." Monitor CTE performance in Phase 4; only migrate if PostgreSQL cannot handle production edge counts. |
| R3 | **Remove vector embeddings entirely** | Feedback line 856 ("NO topology or time encoded, 1536-d semantic vector") | This contradicts the LLD's enriched embedding design (§7), which is the core differentiator. The feedback's corrected version (line 1190+) acknowledges the misreading. |
| R4 | **Fixed snap scoring weights** (0.4/0.3/0.2/0.1) proposed in corrected blueprint | Feedback line 909–912 | The LLD already specifies dynamic weights per failure mode (§9, weight profiles table). Fixed weights would lose failure-mode-specific sensitivity. |
| R5 | **Treat Abeyance Memory as "not needed for Day 1"** | Feedback lines 3897–3900 ("Never sell Abeyance Memory") | The product strategy insight is valid (sell "Instant Operational Context" first), but "not needed" conflates marketing with architecture. The fragment store *is* Abeyance Memory — Incident Reconstruction uses the same infrastructure. The branding advice is accepted; the architectural dismissal is rejected. |
| R6 | **Event-centric indexing replacing fragment comparison** | Feedback lines 4339–4507 | Already present in the LLD. The existing GIN indexes on `failure_mode_tags`, `fragment_entity_ref.entity_id`, and partial indexes on `snap_status`/`decay_score` provide the time × topology × event-type indexing described. No new architecture needed. |

---

Prepared by **Principal Software Architect (Antigravity AI Agent)**. Ready for immediate implementation of v2 LLD and revised plan.
