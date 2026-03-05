# Pedkai: Master Implementation Plan (Full Project Lifecycle)

This document is the single source of truth for the technical implementation of Pedkai across all 14 phases. It chronicles the project's evolution from a data signal fabric to an enterprise-hardened AI-Native Telco Operating System.

---

## 🏗️ Foundation & Signal Fabric (Phases 1-4)

### Phase 1: Data & Signal Fabric
Establish the ground floor:
- **Architecture**: Multi-tenant FastAPI backend with multi-database support (PostgreSQL for metadata, TimescaleDB for KPIs).
- **Ingestion**: Unified pipeline for public datasets (Telelogs, 5G Faults) and synthetic telemetry streaming.

### Phase 2: Context Graph MVP
Design the "Decision Memory" schema:
- **Concept**: Moving from storing "what" happened to "why" it happened via **Decision Traces**.
- **Storage**: PostgreSQL + JSONB + pgvector for semantic retrieval of reasoning chains.

### Phase 3: ANOps Wedge - MTTR Reduction
Initial use case implementation:
- **Anomaly Detection**: KPI-driven triggers (PRB utilization, latency spikes).
- **RCA Engine**: Graph-based reasoning to find root causes of alarms.
- **Explainability**: LLM-powered SITREPs for NOC engineers.

### Phase 4: Foundational Hardening
Transition to "Day 2" operations:
- **Observability**: Structured JSON logging and real health probes (`/health/ready`).
- **Resilience**: Circuit breakers and retry logic for LLM/DB dependencies.
- **QA**: Established `pytest` suite and Locust load testing.

---

## 🧠 Intelligence & Standards (Phases 5-8)

### Phase 5: Deep Intelligence (Causal AI & RLHF)
Moving from correlation to causation:
- **Causal AI**: Integrated **Granger Causality** to verify directional metric influence.
- **RLHF**: Implemented "Operator Feedback" (Upvote/Downvote) to train the similarity search.

### Phase 6: Strategic Review Fixes (Intelligence Hardening)
Refining the causal logic:
- **Mathematics**: Added **Stationarity tests (ADF)** and data differencing to eliminate spurious correlations.
- **Feedback Loop**: Transitioned to a multi-operator junction table for auditability and to prevent score gaming.

### Phase 7: Memory Optimization
Benchmark and tune the retrieval engine:
- **Tuning**: Established "Gold Standard" test sets to find the optimal `min_similarity` for decision recall.

### Phase 8: Market Readiness (TMF Compliance)
Ensuring standards-based interoperability:
- **TMF642 Alarm API**: Standardized alarm management endpoints and dual-correlation IDs.
- **TMF628 Performance API**: Standards-compliant KPI exposure.
- **Alarm Normalizer**: Pluggable architecture to ingest Ericsson (XML) and Nokia (JSON) legacy alarms into the Pedkai fabric.

---

## 🔒 Enterprise Excellence (Phases 9-11)

### Phase 9: Ruthless Executive Review
Comprehensive audit by a 5-member executive committee (Ops, CEO, Strategist, Architect, QA) to identify strategic and operational gaps.

### Phase 10: Executive Rework (Hardening v2)
Addressing the PoC-blockers:
- **Identity**: Real JWT signature verification and hierarchical **RBAC** (Admin, Operator, Viewer).
- **Secrets**: Externalized all credentials with mandatory TLS/SSL for database connections.
- **Orchestration**: Delivered Kubernetes/Helm manifests and Prometheus/OTel tracing.

### Phase 11: Substance Over Shape (Dashboard Integration)
Finalizing the PoC interface:
- **Real Integration**: Wired the Next.js dashboard to functional TMF642 endpoints.
- **Operational UI**: Implemented live alarm feeds and functional "Acknowledge" cycles.

---

## 📈 Expansion & Remediation (Phases 12-14)

### Phase 12: Memory Benchmarking & Piloting
Establishing the math-verified truth set:
- **Benchmark**: Replaced simulation with **Gemini Embedding** + **NumPy Cosine Similarity** tool.
- **Result**: Proved **0.9** as the optimal threshold for high-precision decision matching.

### Phase 13: Wedge 2 - AI-Driven Capacity Planning
Extending to CapEx optimization:
- **Data-Driven Engine**: Queries real TimescaleDB hotspots (PRB > 85%) to recommend site placement.
- **Strategy**: Greedy ROI selection within strict **Budget Constraints**.
- **Dashboard**: Integrated "Regional Densification" visualization into the NOC UI.

### Phase 14: Wedge 3 - Customer Experience Intelligence (Completed)
The final strategic pivot:
- **Correlation**: Successfully implemented server-side logic to link network anomalies (TMF642) with high-risk customers (`churn_risk_score > 0.7`).
- **Automation**: Deployed the "Proactive Care" engine to automatically trigger and log notifications for impacted users.
- **Security**: Secured CX features with dedicated `CX_READ` and `CX_WRITE` RBAC scopes.

---

## 🏛️ AI Control Plane (Phase 15+)

### Phase 15: Strategic Pivot (Pedkai v2.0)
The transition to an active decision-making control plane:
- **BSS Data Layer (15.1)**: Linked the network signal to real-world revenue via `ServicePlanORM` and `BillingAccountORM`.
- **Policy Engine (15.2)**: Implemented a declarative YAML-based "Telco Constitution" to enforce business logic before AI actuation.
- **LLM Integration**: Updated `LLMService` to consumes live BSS context, enabling policy-aware recommendations grounded in financial risk.
