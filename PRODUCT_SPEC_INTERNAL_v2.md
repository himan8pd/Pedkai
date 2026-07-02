# Pedkai Internal Product Specification (v2)

## 1. Document Control

- Product: Pedkai
- Version: 2.0
- Date: 2026-05-11
- Audience: Product, Engineering, Architecture, Delivery, Security, Operations
- Classification: Internal Confidential
- Source of truth basis: Current repository implementation
- Supersedes: Prior internal spec revisions and fragmented roadmap notes where conflicting

## 2. Product Definition

Pedkai is an AI-native telco operating system focused on operational reconciliation, incident intelligence, topology-aware impact analysis, and policy-governed autonomous operations.

The product combines:
- A FastAPI backend with domain APIs for decisions, incidents, topology, abeyance memory, reconciliation, policy, and autonomy.
- A Next.js frontend for operations dashboards and operator workflows.
- Optional Kafka-based telemetry ingestion and replay for streaming and historical simulation.
- Multi-tenant data isolation with OAuth2/JWT security and role/scope-based authorization.

## 3. Problem and Value

Pedkai addresses a core operational gap: divergence between documented network intent and observed runtime behavior.

Primary value outcomes:
- Detect hidden and stale topology states (dark graph patterns).
- Reduce investigation latency via topology-aware and memory-assisted reasoning.
- Improve incident handling quality with structured sitrep and action workflows.
- Enable controlled autonomy with safety gates and policy constraints.
- Quantify operational and business value via value attribution and ROI surfaces.

## 4. v2 Scope Boundary

Included in v2:
- Backend platform and API surface currently wired in the application entrypoint.
- Frontend operational routes currently present in the app router.
- Local, production-like, and cloud deployment paths represented by startup scripts and compose files.
- Current model, migration, and test assets in the repository.

Not included in v2 commitments:
- Unimplemented aspirational capabilities from legacy strategy documents.
- Any performance or accuracy guarantees not validated by current tests/benchmarks.

## 5. System Architecture (Implemented)

Pedkai runs as a layered system:

1. Experience Layer
- Next.js frontend for dashboards and workflows.

2. API and Orchestration Layer
- FastAPI app with modular routers.
- Background tasks for event consumption, sleeping-cell scans, autonomous execution, and optional telemetry consumers.

3. Intelligence and Decision Layer
- Decision memory and similarity retrieval.
- Abeyance memory services (fragment ingestion, enrichment, lifecycle).
- Causal/fusion utilities and policy evaluation.
- Reconciliation and divergence analysis.

4. Data Layer
- Main relational store for operational entities, decisions, incidents, policies, and audit artifacts.
- Metrics store for KPI/telemetry time-series correlation workflows.
- Vector storage for semantic retrieval use cases.

5. Integration Layer
- Kafka topics and consumers/producers.
- TMF-aligned API endpoints.
- Adapters and external system touchpoints (for example Netconf and BSS observers).

## 6. Backend Surface (Current)

The FastAPI app wires domain routers in the main entrypoint and includes lifecycle startup/shutdown handling.

Domain groups currently exposed:
- Health and readiness.
- Authentication and user management.
- Decisions.
- TMF642 alarms and TMF628 performance management.
- Capacity planning.
- CX intelligence.
- Topology and impact analysis.
- Incident lifecycle.
- Service impact and alarm correlation.
- Autonomous shield and action interfaces.
- Policies.
- SSE streaming.
- Ingestion.
- Reports and divergence analysis.
- Adapters.
- Operator feedback.
- Alarm ingestion webhook.
- Abeyance memory.
- Shadow topology.
- Sleeping cells.
- Value attribution.

Operational behavior at startup:
- Default tenant/user seeding (idempotent path).
- Event bus initialization.
- Background consumer startup.
- Autonomous action executor startup.
- Optional sleeping cell scheduler.
- Optional telemetry consumers and fragment bridge.

## 7. Core Capability Inventory and Maturity

Legend:
- Implemented: Available in code and surfaced through API/UI paths.
- Partial: Present but with known constraints, limited depth, or pending integration hardening.
- Planned: Not production-realized in current repository baseline.

| Capability | Status | Internal Notes |
|---|---|---|
| Multi-tenant auth and scoped API access | Implemented | OAuth2/JWT and tenant-oriented data model in place. |
| Decision trace lifecycle and feedback capture | Implemented | Decision APIs and feedback storage paths exist. |
| Incident workflow with sitrep/action lifecycle | Implemented | Core lifecycle endpoints and approval states are present. |
| Dark graph/divergence reporting | Implemented | Reconciliation and report endpoints are available. |
| Abeyance memory fragment pipeline | Implemented | Fragment model, APIs, and services are present. |
| Abeyance long-horizon cold retrieval optimization | Partial | Cold storage and long-horizon retrieval need deeper validation/tuning. |
| Autonomous action governance via safety gates | Implemented | Safety-gate framework and executor wiring are present. |
| Fully unattended autonomous remediation at scale | Partial | Human gates/policy guardrails exist; broader runtime confidence still requires staged rollout. |
| TMF alarm/performance endpoint support | Implemented | TMF642 and TMF628 route groups are available. |
| Streaming telemetry ingestion via Kafka | Partial | Consumers and replay tooling exist; deployment-specific hardening remains. |
| Topology-plus-shadow topology convergence logic | Partial | APIs exist; broader scenario validation is still needed. |
| ROI and value attribution scoring surfaces | Implemented | Value-oriented endpoints and dashboards are present. |

## 8. Data and Model Architecture

Primary data domains include:
- Tenant and user identity.
- Network entities and topology relationships.
- KPI and telemetry samples.
- Decision traces and operator feedback.
- Incident lifecycle records.
- Policy definitions and audit metadata.
- Reconciliation/divergence findings.
- Abeyance memory fragments and lifecycle metadata.

Schema and migration posture:
- Alembic migration history is present and active.
- Tenant consistency migrations and abeyance-specific migrations exist.
- Vector-enabled fields are used for semantic retrieval workflows.

## 9. Intelligence and Memory Engine

Pedkai combines multiple intelligence paths:
- Similarity search over decision and fragment memory.
- Causal analysis methods and fusion logic utilities.
- LLM-assisted reasoning services.
- Structured feedback integration to improve decision context quality.

Abeyance memory in v2:
- Treated as a core differentiator.
- Supports fragment ingestion and lifecycle states.
- Supports enrichment and retrieval patterns for delayed context binding.
- Requires ongoing tuning for long-horizon retrieval quality and decay behavior in production settings.

## 10. Frontend Product Surface

Current frontend stack:
- Next.js 16.
- React 19.
- Tailwind CSS v4.
- Leaflet/react-leaflet for topology/geospatial views.
- Framer Motion for interactive UX behavior.

Current page-level product areas include:
- Dashboard.
- Topology.
- Incidents.
- Divergence.
- Sleeping cells.
- Scorecard.
- ROI.
- Settings.
- Admin.
- Feedback.

## 11. Security and Governance

Implemented controls:
- OAuth2 password flow with JWT tokens.
- Scope-based authorization on protected API groups.
- Tenant isolation as a first-class model concern.
- Password hashing and security middleware integration.
- Policy-driven action constraints.
- Safety-gated autonomous action execution.
- PII scrubbing and data governance service components.
- Audit-oriented incident and policy flow instrumentation.

Operational governance principles for v2:
- Human oversight remains mandatory for high-risk operational actions.
- Autonomy is bounded by policy, confidence, blast-radius, windowing, and rate controls.
- Explainability and auditability are required for action-taking paths.

## 12. Deployment and Runtime Modes

Mode A: Local demo/developer
- Entry points: startup_local.sh and startup.sh.
- Primary use: fast local iteration.
- Data profile: local-friendly mode (including SQLite pathing in local script).

Mode B: Production-like local
- Entry point: startup_prod.sh.
- Uses Docker-managed infra (PostgreSQL, TimescaleDB, Kafka) and Alembic migrations.
- Primary use: integration-style local validation.

Mode C: Cloud compose baseline
- Entry point: docker-compose.cloud.yml.
- Runs backend, frontend static build container, Kafka, Ollama, and optional replay service.
- Uses externalized database deployment pattern.

## 13. Observability and Operability

Current observability foundation includes:
- Structured logging.
- Correlation and trace middleware.
- OpenTelemetry instrumentation hooks.
- Health and readiness endpoints.

Operational characteristics:
- Background task startup and graceful shutdown handling are explicitly wired.
- Environment-driven toggles control optional workers and integrations.

## 14. Quality and Testing Posture

Current strengths:
- Broad test assets across unit, integration, validation, load, and security folders.
- Notable emphasis in repository on abeyance, safety-gate, and causal/fusion-related tests.

Known quality risks to track in v2 execution:
- End-to-end validation across dual-database reconciliation paths.
- Full pipeline tests for Kafka-to-memory ingestion bridges.
- Deeper incident lifecycle E2E with approvals and closure.
- Multi-tenant leakage regression coverage across all high-value endpoints.

## 15. Constraints and Assumptions

Technical constraints reflected in current codebase and runtime model:
- Event-driven paths depend on Kafka availability when streaming is enabled.
- Certain advanced paths are controlled by environment flags and may be disabled by deployment profile.
- Action autonomy is intentionally constrained by governance gates.
- Model and retrieval quality depend on tenant data quality and historical depth.

Operating assumptions for customer deployments:
- Customer can provide enough historical operational telemetry/context for meaningful correlation.
- Tenant and access governance are configured before enabling broader automation features.
- Production rollout uses progressive enablement rather than immediate full autonomy.

## 16. v2 Priorities (Execution Focus)

Priority 1: Reliability hardening
- Add E2E coverage for reconciliation, telemetry ingestion bridge, and incident lifecycle completeness.
- Validate migration outcomes and tenant boundary invariants continuously.

Priority 2: Memory quality and retrieval performance
- Improve long-horizon abeyance retrieval and decay scoring behavior.
- Add benchmark datasets and acceptance thresholds for memory relevance.

Priority 3: Safe autonomy rollout
- Strengthen policy simulation and dry-run pathways.
- Expand operational playbooks for action approval and rollback.

Priority 4: Productization and operational readiness
- Tighten SLO/SLA instrumentation.
- Expand deployment runbooks and incident response procedures.

## 17. Non-Goals for v2

- Replacing incumbent OSS/BSS ecosystems.
- Forcing write-access-first enterprise integrations as a prerequisite for value demonstration.
- Claiming universal zero-touch remediation without tenant-specific governance calibration.

## 18. Internal Source Map

Primary implementation references for this v2 document:
- backend/app/main.py
- backend/app/api/
- backend/app/services/
- backend/app/models/
- backend/alembic/versions/
- frontend/app/
- frontend/package.json
- requirements.txt
- README.md
- docker-compose.yml
- docker-compose.cloud.yml
- startup.sh
- startup_local.sh
- startup_prod.sh
- tests/
- backend/tests/

## 19. Approval

This v2 document is considered implementation-aligned as of 2026-05-11 and should be updated whenever major router, model, deployment, or governance changes land in mainline.
