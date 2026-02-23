# Pass 3 — Adversarial Review

---

## Section 1 — Critical Flaws

### CF-1. The 16-week timeline is fiction.

Phase 1 alone contains five infrastructure initiatives (entity store, message bus, background workers, connection management, time-series table) that each require schema migration, integration testing, operational runbook, and deployment pipeline changes. For a team that has never operated a message bus in this codebase, 4 weeks is the time to *evaluate* NATS vs Redis Streams, not deliver production-grade alarm ingestion with SNMP trap receivers. An SNMP trap receiver alone is a non-trivial systems programming task — libsnmp bindings, MIB compilation, trap-to-structured-event mapping per vendor. The roadmap treats this as a sub-bullet.

**Realistic estimate:** Phase 1 is 8–10 weeks. The entire roadmap is 9–12 months, not 16 weeks.

---

### CF-2. Pass 2 missed two existing services and therefore under-scoped.

`RLEvaluatorService` (`rl_evaluator.py`, 191 lines) implements a closed-loop reward system that auto-scores decisions based on KPI improvement and policy compliance. `drift_calibration.py` (112 lines) tracks drift detection false-positive rates and recommends threshold adjustments. Neither was mentioned in Pass 1's capability matrix nor Pass 2's roadmap. Both are partially implemented and directly relevant to Phase 3 and Phase 4 deliverables. If the auditor missed observable code, what else was missed?

**Impact:** The roadmap proposes building capabilities (confidence calibration, feedback loop) that partially already exist. Work will be duplicated or the existing implementations will be discovered mid-flight and create merge conflicts.

---

### CF-3. The "event-driven overlay" assumes services are stateless. They are not.

Pass 2 claims "services are already stateless and async-capable." This is wrong. `AlarmCorrelationService.__init__` takes an `AsyncSession` — it's bound to a request-scoped database session. Moving it to an event consumer means refactoring every service to accept a session factory instead of a session instance, changing all callers, and re-testing every code path. `PolicyEngine` is a **module-level singleton** (`policy_engine = PolicyEngine()`) that loads YAML at import time — it has process-level state. The "100% of existing service code survives" claim will not hold under real refactoring.

**Impact:** The effort estimate for Direction A is materially understated. Session lifecycle management in event consumers is a recurring source of bugs (leaked sessions, stale reads, transaction isolation violations).

---

### CF-4. Granger causality is the wrong tool for telco RCA.

Granger causality tests assume stationary time series, linear relationships, and bivariate analysis. Telco KPI data is non-stationary (traffic follows diurnal/weekly patterns), relationships are non-linear (congestion is a threshold effect, not proportional), and causal chains are multivariate (A + B together cause C, but neither alone does). The roadmap proposes pairwise Granger tests with a minimum of 30 data points — this is statistically meaningless for 5-minute KPI samples (30 points = 2.5 hours of history, insufficient to capture diurnal patterns).

Furthermore, no telco operator will accept "Granger-causes with p < 0.05" as root-cause evidence in an SLA dispute or regulatory filing. The demo's use of Granger causality is impressive theatre but not a defensible analytical method for this domain.

**Alternative:** Transfer entropy, Bayesian networks, or simply expert-defined causal models validated against historical outage data. These are more defensible and do not require stationarity.

---

### CF-5. No operator will give you BSS billing data.

The roadmap casually proposes "integrate real BSS billing data" in Phase 2 as a line item. In every major telco I have worked with, BSS systems (Amdocs, CSG, Netcracker) are the most tightly controlled data sources in the enterprise. Getting read access to billing data requires: (a) a formal data access request through the CISO, (b) PII impact assessment, (c) data minimisation review under GDPR/DPA, (d) network segmentation to prevent billing data from leaking into operational systems, and (e) 3–6 months of procurement and legal review. The roadmap allocates zero time for this and treats it as a coding task.

**Impact:** Revenue-at-risk calculations will remain synthetic/proxy values for 12+ months after deployment. The ROI dashboard in Phase 4 will be based on counterfactual estimates, not measured revenue impact. This is a credibility risk with C-level stakeholders.

---

### CF-6. The Netconf/YANG adapter in Phase 4 is a separate product.

Building a multi-vendor Netconf/YANG adapter for Juniper, Nokia, *and* Ericsson that can safely modify live network configuration is not a 4-week sub-task. Each vendor has different YANG models, different transaction semantics (candidate vs running config), different rollback mechanisms, and different authentication schemes. Nokia SR OS uses MD-CLI with model-driven Netconf; Juniper uses Junos structured XML; Ericsson uses a proprietary CLI-over-Netconf hybrid. Testing requires lab access to each vendor's equipment.

This is 6–12 months of dedicated network automation engineering. Presenting it as bullet 2 of Phase 4 reveals a fundamental misunderstanding of the integration challenge.

---

### CF-7. The "Digital Twin" is hand-waved.

Phase 4 proposes "simulate the change against a shadow topology graph" as a single initiative. A Digital Twin that can predict the KPI impact of a configuration change requires: (a) a validated performance model per network element type, (b) traffic engineering models, (c) propagation delay models, (d) failure mode simulation. This is an entire product category (Nokia AVA, Juniper Paragon Planner, VIAVI NITRO). No implementation guidance, no model architecture, no training data strategy is provided.

**Impact:** Either this becomes a topology-graph constraint check (useful but not a "Digital Twin") or it becomes a multi-year R&D project. The roadmap does not distinguish between these outcomes.

---

### CF-8. Zero attention to multi-tenancy at the event layer.

The existing CRUD API has tenant isolation (enforced via `tenant_id` in queries). The proposed event bus has none. If NATS or Kafka is introduced, every event must carry a tenant_id, every consumer must filter by tenant, every topic/subject must be namespaced per tenant, and message ordering must be preserved per-tenant. The roadmap mentions the message bus 5 times and tenant isolation 0 times in the context of events.

In a SaaS deployment where multiple operators share infrastructure, a tenant isolation failure at the event layer means Operator A sees Operator B's alarms. This is a regulatory and contractual catastrophe.

---

### CF-9. The on-prem embedding fallback creates a silent accuracy cliff.

Phase 3 proposes `all-MiniLM-L6-v2` (384-dim, 22M params) as fallback for Gemini `text-embedding-004` (768-dim, undisclosed params). These produce fundamentally different embedding spaces. Decision Memory similarity scores are not comparable across providers. A decision embedded with Gemini at similarity 0.92 might score 0.61 with MiniLM — or 0.98. There is no calibration, no cross-provider normalisation, and no mechanism to re-embed existing decisions when switching providers.

**Impact:** An operator who starts with Gemini and later moves to on-prem (data sovereignty requirement) will find that Decision Memory returns completely different results. Past feedback scores become meaningless. The system appears to "forget" its training.

---

## Section 2 — Failure Scenarios

### FS-1. The 02:00 AM Fibre Cut

A major fibre cut generates 2,400 alarms across 47 sites in 90 seconds. The alarm ingestion webhook receives all 2,400 POSTs. The `AlarmCorrelationService.correlate_alarms()` method runs an O(n²) nested loop (line 39-115 of `alarm_correlation.py`: for each alarm, iterate all other alarms). With 2,400 alarms, this is 5.76 million comparisons. Because the roadmap moves correlation to a background worker but doesn't change the algorithm, this takes 45+ seconds on a single worker. Meanwhile, 2,400 `AlarmIngestedEvent` messages queue up. The orchestrator creates 2,400 separate incidents before correlation completes. NOC operators see a wall of duplicate incidents. The system they were promised would *reduce* noise has amplified it.

**Root cause:** The correlation algorithm was designed for demo payloads (5-10 alarms). No one load-tested it because there was no ingestion pipeline to feed it. The roadmap adds ingestion without fixing the algorithm.

---

### FS-2. The Sovereignty Migration

A European operator deploys Pedkai with Gemini embeddings for 6 months, accumulating 3,000 decision traces with embeddings and 500 operator feedback scores. The operator's CISO then mandates that no data may transit to US-based cloud APIs. The team switches to on-prem MiniLM embeddings (Phase 3, CF-9). All 3,000 decisions must be re-embedded. The bulk-embedding pipeline runs, but MiniLM produces 384-dim vectors while pgvector columns are configured for 768-dim. The migration script crashes. After fixing the schema, all decision traces are re-embedded, but the similarity scores are now in a different distribution. The 500 feedback-boosted scores, calibrated against Gemini-space distances, now promote the wrong decisions. A sleeping cell incident is matched to an unrelated capacity planning decision at 0.89 similarity. The SITREP recommends decommissioning a cell site. The NOC operator follows the recommendation.

**Root cause:** No embedding-provider-aware indexing. No cross-provider normalisation. No validation that the feedback loop remains calibrated after provider change.

---

### FS-3. The Board-Level Audit

After 6 months of operation, the CFO asks for evidence of Pedkai's ROI. The ROI Dashboard (Phase 4) shows "£2.4M in revenue protected." The CFO's team asks for the methodology. `calculate_value_protected()` sums `revenue_at_risk` values from incidents where `outcome == "prevented"`. But `revenue_at_risk` was never sourced from BSS (CF-5) — it comes from policy-parameter proxies that were seeded at deployment time. The "prevented" classification was set by the system based on whether KPIs recovered after the change request was executed — but Pedkai doesn't monitor KPI recovery because there's no time-series ingestion for post-action validation (SR-6). The entire chain is circular: Pedkai recommends an action, assumes it was executed, assumes KPIs recovered, and claims the revenue as protected.

The CFO's audit finds zero independently verifiable data points. The £2.4M figure is retracted. The project loses executive sponsorship.

**Root cause:** The value-protected calculation is a closed loop with no external validation. The `methodology_doc_url` points to `/docs/value_methodology.md` which does not exist in the codebase.

---

## Section 3 — Required Corrections

### RC-1. Triple the timeline or halve the scope.

The 16-week roadmap must become either a 40-week roadmap (realistic for the current scope) or a 16-week roadmap that delivers only Phases 1 and 2. Phases 3 and 4 should be re-scoped as separate funded work packages with their own business cases. Presenting autonomous network execution as a "Phase 4 initiative" to a board is irresponsible — it requires its own risk assessment, insurance review, and regulatory clearance.

### RC-2. Fix the correlation algorithm before adding ingestion.

`correlate_alarms()` must be replaced with an O(n log n) algorithm (entity-indexed clustering, then temporal merge within each entity group) before any real-volume alarm stream is connected. The current O(n²) implementation will collapse under production load. Add a load test to Phase 1 success criteria: "correlation of 5,000 alarms completes in < 5 seconds."

### RC-3. Drop Granger causality. Use domain-expert causal models.

Replace the Causal AI Engine with a library of expert-defined causal templates (e.g., "fibre_cut → gNodeB_alarm → cell_unavailable → customer_impact") validated against historical incident data. These are auditable, explainable, and do not require stationarity assumptions. Reserve statistical causality for a future R&D work package with a dedicated data scientist.

### RC-4. Treat BSS integration as a separate workstream with a 6-month horizon.

Remove "integrate real BSS billing data" from Phase 2. Replace with "define BSS integration API contract and mock adapter." Actual BSS integration requires procurement, legal, and CISO approval that cannot be parallelised with engineering work. The revenue-at-risk calculations must be explicitly labelled as "estimates" in the UI and API responses until BSS data is available.

### RC-5. Mandate embedding-provider isolation from day one.

Decision traces must store `embedding_provider` and `embedding_model` alongside the vector. Similarity searches must filter by provider. If providers change, decisions must be re-embedded and re-indexed in a separate namespace. The feedback loop must be provider-scoped. This is not a Phase 3 concern — it must be a Phase 1 schema design decision.

### RC-6. Add tenant isolation to the event bus architecture.

Every event schema must include `tenant_id`. Every consumer must enforce tenant filtering. Topic/subject naming must include tenant namespace. Add a tenant-isolation integration test to Phase 1: "events published by Tenant A are never received by Tenant B's consumer."

### RC-7. Delete the Netconf/YANG adapter and Digital Twin from Phase 4.

These are separate products, not features. Replace Phase 4 with: (a) operator feedback loop, (b) ROI dashboard with explicit confidence intervals and "estimate" labelling, (c) documentation of the autonomous execution *architecture* (design doc, not implementation), and (d) a formal business case for funding the autonomous execution work package. A CTO will approve a measured recommendation to invest; no CTO will approve a 4-week autonomous-network-modification sprint.

### RC-8. Audit the existing codebase for missed capabilities.

Pass 1 missed `RLEvaluatorService` (191 lines, closed-loop reward scoring) and `drift_calibration.py` (112 lines, FP-rate tracking with threshold adjustment). These are real, implemented capabilities that affect the roadmap. Before executing any phase, perform a complete service inventory with line counts, test coverage, and dependency graphs. The roadmap is built on an incomplete capability matrix.
