# Pass 2 — Architecture Viability & Phased Roadmap

## 1. Executive Summary

Pedkai's backend has genuine engineering substance — RBAC, pgvector, tenant isolation, policy engine, LLM adapter, and TMF-aligned schemas. This is not a demo shell. However, it operates as a **request-response CRUD application** when the demo promises an **event-driven autonomous operations platform**. The absence of a data ingestion pipeline, an event bus, and two headline capabilities (Sleeping Cell, Causal AI) means the architecture cannot evolve incrementally into the demo vision; it requires targeted redesign of the data plane while preserving the existing service layer. The gap is not code quality — it is **architectural category**. Pedkai is a decision-support API that must become an event-driven intelligence platform. Four phases over 16 weeks can close this gap if Phase 1 (data plane) is prioritised ruthlessly.

---

## 2. Architecture Viability

### 2.1 Systemic Risks

| # | Risk | Evidence (Pass 1) | Impact |
|---|---|---|---|
| SR-1 | **No data ingestion pipeline** | All 12 capabilities require manual API calls to function. No Kafka consumer, no SNMP/NETCONF collector, no syslog receiver. | Without inbound data flow, Pedkai cannot detect, correlate, or prevent anything autonomously. This is the single most critical gap. |
| SR-2 | **Cloud-locked AI with no fallback** | `EmbeddingService` and `LLMAdapter` require `GEMINI_API_KEY`. Decision Memory and SITREP generation are inoperative without it. | Telco operators with on-prem mandates or sovereignty constraints cannot deploy. A network outage — the exact scenario Pedkai monitors — kills its own AI layer. |
| SR-3 | **Absent entity metadata store** | `network_entities` table was dropped; topology stores only relationships via `EntityRelationshipORM`. Alarm correlation queries a missing table. | Topology graph, RCA, impact tree, and emergency service detection are structurally broken. Incidents.py line 82 queries a non-existent table. |
| SR-4 | **Demo-code divergence on autonomy** | Demos show autonomous execution (Netconf rollback, BBU restart). `AutonomousShieldService` explicitly states "NEVER executes actions" and generates change requests only. | The product narrative promises autonomous protection; the code enforces human-only execution. This is a positioning conflict, not a bug, but it requires deliberate product decision. |
| SR-5 | **SSE session leak** | `sse.py` holds DB sessions indefinitely per connected client with no timeout, heartbeat, or connection limit. | Under 50+ concurrent NOC operators, this exhausts the database connection pool and crashes the backend. |
| SR-6 | **No time-series storage or analysis** | Drift detection uses single-point comparison (`current_value` vs `baseline_value`). No time-series database, no windowed aggregations, no trend analysis. | Sleeping Cell (Z-score), Causal AI (Granger), and predictive drift all require historical time-series data that has nowhere to be stored or queried. |
| SR-7 | **Frontend monolith blocks NOC usability** | `page.tsx` exceeds 500 lines. No routing, no lazy loading, no state management. All features rendered in a single component. | NOC operators cannot navigate between topology, incidents, and alarm views. Dashboard is unusable for real-time operations beyond demo walkthroughs. |

### 2.2 Architectural Bottlenecks

| # | Bottleneck | Constraint |
|---|---|---|
| AB-1 | **Synchronous request-response architecture** | Every capability (correlation, RCA, drift detection, SITREP) executes inline within an HTTP request handler. No background workers, no task queues, no event-driven processing. LLM calls block the API thread for 2-10 seconds. |
| AB-2 | **Single-database coupling** | PostgreSQL serves as OLTP store, vector database (pgvector), topology graph store, and implicit time-series store. No read replicas, no query routing, no connection pooling beyond SQLAlchemy defaults. Production topology queries (recursive CTE with 5-hop BFS) will contend with OLTP writes. |
| AB-3 | **Missing orchestration layer** | No service that connects alarm ingestion → correlation → RCA → SITREP → notification into an automated pipeline. Each capability is a standalone API endpoint that must be called manually in sequence. The "lifecycle" exists as a state machine but has no trigger. |
| AB-4 | **Stateless alarm processing** | `AlarmCorrelationService.correlate_alarms()` accepts a list of alarms as input and processes them in-memory. No alarm buffer, no sliding window, no deduplication state. Each API call is independent — the system has no memory of previously seen alarms. |

### 2.3 Verdict

> **B. Borderline — requires targeted redesign.**

The service layer (business logic, schemas, security, policy engine) is sound and reusable. The **data plane** is absent. The application has no way to receive, buffer, or stream network events and no background processing to chain capabilities into automated workflows. This is not a code quality problem — the existing services are well-structured with proper separation of concerns, tenant isolation, and TMF alignment. The redesign is surgical: introduce an event-driven data plane beneath the existing service layer, add a time-series store alongside PostgreSQL, and build an orchestration service that wires the existing capabilities into automated pipelines. The service layer survives intact; the plumbing changes.

---

## 3. Alternative Architecture

### Direction A — Event-Driven Overlay (Recommended)

Introduce Kafka (or NATS/Redis Streams for lighter footprint) as the event backbone. Existing services become **consumers** triggered by events rather than HTTP requests. Add a lightweight orchestrator (e.g., Temporal or a custom state machine) that chains: `alarm_ingested → correlate → rca → sitrep → notify`.

| Dimension | Assessment |
|---|---|
| **Effort** | Medium. Existing service classes are reused as-is. New code: ingestion adapters, Kafka consumer framework, orchestrator, time-series adapter. ~4-6 weeks for an experienced engineer. |
| **Risk** | Low-Medium. Services are already stateless and async-capable (SQLAlchemy async sessions). Main risk is operational complexity of running Kafka/NATS in addition to PostgreSQL. |
| **Time-to-value** | Phase 1 delivers working alarm ingestion in 3-4 weeks. Each subsequent phase adds observable capability. |

### Direction B — Serverless / FaaS Pipeline

Replace the monolithic FastAPI backend with cloud functions (Lambda/Cloud Run) triggered by Pub/Sub events. Each capability becomes an independent function.

| Dimension | Assessment |
|---|---|
| **Effort** | High. Requires decomposing the monolith, managing cold starts, handling state across functions, and re-implementing the policy engine as a shared library. |
| **Risk** | High. Cloud-locked by design. Contradicts sovereignty requirements. Cold starts unacceptable for real-time NOC operations. |
| **Time-to-value** | Slower than Direction A. No incremental path — requires big-bang rewrite of the API layer. |

> **Recommendation: Direction A.** It preserves 100% of existing service code, adds the missing data plane, and enables incremental delivery.

---

## 4. Phased Roadmap

### Phase 1 — Foundations (Weeks 1–4)

**Objectives**
- Establish the event-driven data plane that all downstream capabilities depend on
- Restore the broken entity metadata store and fix structural data model gaps

**Key Initiatives**
1. Create `NetworkEntityORM` table with columns: `id`, `tenant_id`, `entity_type`, `name`, `geo`, `revenue_weight`, `sla_tier`, `last_seen_at`. Migrate existing topology relationships to reference it. Fix `incidents.py:82` dead query.
2. Introduce a message bus (NATS JetStream or Redis Streams for MVP; Kafka for production). Create `AlarmIngestedEvent` schema. Build a generic ingestion adapter with SNMP trap receiver and REST webhook endpoints.
3. Add a background worker framework (e.g., `arq` on Redis or `asyncio` task queue). Move LLM calls, embedding generation, and alarm correlation off the HTTP request path.
4. Implement connection pooling, SSE session timeout (30s heartbeat, 5min max), and read/write session separation.
5. Add a time-series table (`kpi_samples`: `entity_id`, `metric_name`, `value`, `timestamp`) with hypertable partitioning (TimescaleDB extension or simple date-partitioned table).

**Primary Risk**  
Introducing a message bus adds operational complexity. Mitigate by starting with Redis Streams (already familiar technology; zero new infrastructure if Redis is available) and graduating to Kafka only when throughput exceeds 10k events/sec.

**Success Criteria**  
- `NetworkEntityORM` populated with ≥100 entities across 3 types; `incidents.py` entity lookup returns valid results
- Alarm ingestion adapter receives a webhook POST and publishes to the event bus within 200ms
- LLM SITREP generation completes without blocking API thread (background task with SSE notification on completion)
- SSE connections auto-close after 5 minutes of inactivity; connection pool never exceeds 80% utilisation under 50 concurrent clients

---

### Phase 2 — Capability Alignment (Weeks 5–8)

**Objectives**
- Wire existing services into automated event-driven pipelines
- Close the gap between demo narratives and observable backend behaviour

**Key Initiatives**
1. Build the **Incident Orchestrator**: event listener that chains `alarm_ingested → AlarmCorrelationService.correlate_alarms() → auto-create incident → trigger RCA → generate SITREP → notify operator`. This is the missing "AB-3" orchestration layer.
2. Implement **Sleeping Cell Detector**: a scheduled job (every 5 min) that queries `kpi_samples` for entities with zero traffic where `entity_type ∈ {CELL, SECTOR}` and `last_kpi_age > 15 min`. Compute Z-score against 7-day baseline. Emit `SleepingCellDetectedEvent` when Z < −3σ.
3. Refactor the frontend: decompose `page.tsx` into routed pages (`/topology`, `/incidents`, `/alarms`, `/scorecard`). Introduce lightweight state management (Zustand or React Context). Target: no single component exceeds 200 lines.
4. Integrate real BSS billing data path: ensure `get_impacted_customers()` returns actual `revenue_at_risk` from `BillingAccountORM` instead of policy-parameter proxies. Add "unpriced customer" flag where billing data is unavailable.
5. Fix consent enforcement: ensure `trigger_proactive_care()` calls `ProactiveCommsService.draft_communication()` which checks `consent_proactive_comms` before any channel dispatch.

**Primary Risk**  
Orchestrator complexity. A naive implementation creates tight coupling between services. Mitigate by using an event-driven choreography pattern (each service emits events; downstream services subscribe) rather than a centralised orchestrator. This also enables independent scaling.

**Success Criteria**  
- End-to-end automated flow: POST a raw alarm → incident auto-created with severity, RCA tree, and SITREP within 30 seconds — zero manual API calls
- Sleeping Cell Detector generates at least 1 true-positive detection against seeded test data with deliberately silenced cells
- Frontend loads in <2s on 3G throttle; `page.tsx` removed; all routes navigable
- Proactive comms blocked for customers with `consent_proactive_comms = false` — verified by integration test

---

### Phase 3 — Differentiation (Weeks 9–12)

**Objectives**
- Deliver the "only Pedkai can do this" capabilities that justify the product's existence
- Establish auditable, explainable AI that passes regulatory scrutiny

**Key Initiatives**
1. Implement **Causal AI Engine**: integrate `statsmodels.tsa.stattools.grangercausalitytests` over `kpi_samples` time-series. For each incident cluster, test pairwise Granger causality between the root-cause entity's KPIs and downstream entity KPIs. Store results as `CausalEvidenceORM` (cause, effect, p_value, lag, test_stat). Feed into `LLMService.generate_sitrep()` via existing `causal_evidence` parameter.
2. Build **on-prem embedding fallback**: integrate `sentence-transformers/all-MiniLM-L6-v2` (22M params, runs on CPU) as fallback when `GEMINI_API_KEY` is unset. Ensure `find_similar()` works identically with either embedding source. Add embedding-provider metadata to decision traces.
3. Implement **SLA breach countdown**: compute `predicted_breach_time` from drift trajectory and SLA thresholds stored in `BillingAccountORM.sla_tier`. Expose via SSE as a real-time countdown. Display on NOC dashboard.
4. Add **Decision Memory bulk-embedding pipeline**: background job that iterates all `DecisionTraceORM` records with null embeddings and populates them. Backfill-safe (idempotent, resumable).
5. Calibrate LLM confidence scoring: replace heuristic formula with a lookup table validated against 50+ operator-scored SITREP outputs. Publish methodology as `/docs/confidence_methodology.md`.

**Primary Risk**  
Granger causality requires sufficient time-series history (minimum 30 data points per entity pair). If KPI ingestion volume is low during early deployment, the engine will produce inconclusive results. Mitigate by seeding with historical OSS exports and setting a minimum-sample-size gate before running tests.

**Success Criteria**  
- Causal AI produces valid Granger results (p < 0.05) for at least 3 known cause-effect pairs in test data (e.g., `PRB_utilization` Granger-causes `DL_throughput_drop`)
- Decision Memory operational without cloud API key — verified by running similarity search with local embeddings on air-gapped test environment
- SLA breach countdown visible on dashboard and accurate to ±5 minutes for a simulated drift scenario
- LLM confidence scores correlate with operator feedback scores at r > 0.6 over validation set

---

### Phase 4 — Autonomous Evolution (Weeks 13–16)

**Objectives**
- Enable controlled autonomous actions with safety rails and rollback
- Deliver measurable ROI metrics that justify continued investment

**Key Initiatives**
1. Implement **Controlled Autonomous Execution**: add a `execution_mode` enum (`RECOMMEND_ONLY`, `AUTO_WITH_APPROVAL`, `FULLY_AUTONOMOUS`) to `PolicyEngine`. In `AUTO_WITH_APPROVAL` mode, Pedkai executes the change request automatically but requires post-execution human confirmation within 15 minutes (auto-rollback if unconfirmed). `FULLY_AUTONOMOUS` requires explicit board-level policy override.
2. Build **Netconf/YANG adapter** for Juniper/Nokia/Ericsson: enable actual network configuration changes (policy revert, PRB reallocation, cell restart) gated by `PolicyEngine.evaluate()`. Log every action to `DecisionTraceORM` with full rollback plan.
3. Implement **ROI Dashboard**: aggregate `ValueProtected` calculations into a daily/weekly/monthly view. Compare MTTR in Pedkai-monitored zones vs control zones. Surface confidence intervals prominently. Require board sign-off before publishing externally.
4. Add **Digital Twin simulation**: before executing any autonomous action, simulate the change against a shadow topology graph. Compare predicted KPI impact vs actual. Feed delta back into drift model calibration.
5. Implement **operator feedback loop**: after each SITREP and autonomous action, prompt the NOC operator for a 1-5 rating. Use ratings to (a) adjust Decision Memory boost weights, (b) calibrate confidence scoring, (c) identify policy gaps.

**Primary Risk**  
Autonomous network changes carry catastrophic downside risk. A misconfigured rollback or an incorrect RCA could cause a wider outage than the one being fixed. Mitigate with: mandatory shadow simulation, 15-minute confirmation window, blast-radius limits (max 1 entity per autonomous action), and a hardware kill-switch that disables autonomous mode instantly.

**Success Criteria**  
- At least 1 end-to-end autonomous interception in staging: drift detected → change request generated → simulated → executed → confirmed → metrics restored — with full audit trail in `DecisionTraceORM`
- ROI dashboard shows cumulative value protected with confidence intervals; methodology document reviewed and signed off by product owner
- Operator feedback loop active with ≥20 rated SITREPs; feedback-score correlation with confidence exceeds r > 0.5
- Zero unintended network changes during the entire Phase 4 testing window
