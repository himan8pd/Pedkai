# Pedkai Pivot Execution Plan (Vision V8)

Date: 26 Feb 2026  
Owner: Product Architecture + Platform Engineering

## 1) Pivot Context and What We Keep

Pedkai has pivoted from a broad telco control-plane narrative to a focused AI-Native Operational Reconciliation Engine. The new wedge is **CMDB truth healing** using multi-modal evidence, with telecom as proving ground rather than endpoint.

### Legacy assets retained (high value)

- **Data fabric and ingestion discipline** from `data_fabric/` (normalization, event handling, loaders).
- **Decision and causal services** from `backend/app/services/` (correlation, explainability, policy, drift handling, autonomy safeguards).
- **Policy guardrail foundation** (YAML-based policy engine, safety tests in `tests/integration/`).
- **Operational frontend baseline** in `frontend/app/dashboard/page.tsx` and related components.
- **Demo scenario framework** in `demo/scenarios.py` for deterministic storytelling.

### Legacy assets de-emphasized (for this GTM phase)

- Deep telco-specific protocol breadth as primary story (keep as credibility layer).
- New autonomous actuation claims beyond policy-bounded recommendation and enrichment.

## 2) North-Star Product Definition (Operational Reconciliation Engine)

Pedkai continuously reconciles:

- **Intent layer:** CMDB, change tickets, architecture documents.
- **Reality layer:** telemetry, alarms, event streams.
- **Memory layer:** incident notes, resolutions, historical patterns.

Output is a **Living Context Graph** with confidence-scored dependencies, conflict flags, and operator-ready recommendations.

## 3) Reference Target Architecture

## 3.1 Data Sources

1. CasinoLimit simulation dataset (seed corpus for behavior + topology analogs).  
2. Datagerry CMDB (source of declared CI intent).  
3. Pedkai backend signal streams (TMF alarms, KPI events, incident context).

## 3.2 Integration Spine

1. **Ingestion adapters** (batch + event): parse/normalize source payloads.
2. **Canonical schema mapping**: CI, relation, service impact, evidence lineage.
3. **Reconciliation engine**: detect drift, infer latent edges, compute confidence.
4. **Policy constitution gate**: block unsafe/low-confidence outputs.
5. **Delivery channels**: dashboard insights, ticket enrichment, export APIs.

## 3.3 Current-to-target bridge

- Current seed utility in `generate_cmdb.py` proves Datagerry bootstrap flow (type/object creation + CasinoLimit instance extraction).
- Next step is to convert this to a reusable ingestion module under `data_fabric/` with idempotent checkpoints, metrics, and schema governance.

## 4) CasinoLimit + Datagerry + Pedkai Detailed Implementation

## 4.1 Canonical data contract

Create a versioned contract (`v1alpha`) with these entities:

- `CI` (id, type, attributes, source, timestamp)
- `Edge` (from_ci, to_ci, relation_type, source, confidence)
- `Evidence` (telemetry_ref, ticket_ref, document_ref, checksum)
- `ReconciliationFinding` (finding_type, severity, confidence, remediation_hint)

## 4.2 Pipeline stages

1. **CMDB ingest (Datagerry REST)**
   - Pull object types, objects, and relations incrementally.
   - Persist raw snapshots + parsed canonical records.

2. **CasinoLimit simulation enrichment**
   - Use dataset instances as synthetic environment and event replay base.
   - Map generated hosts/zones to CI categories for deterministic demos.

3. **Reality ingest (events/alarms/telemetry)**
   - Reuse existing event handling from `data_fabric/event_handlers.py` and alarm normalization patterns.

4. **Reconciliation execution**
   - Drift detection: intent vs reality mismatch detection.
   - Latent edge inference: only create inferred relation after cross-source corroboration.
   - Abeyance memory: unresolved clues held with expiry and revisitation triggers.

5. **Policy and trust gating**
   - Enforce confidence threshold + prohibited action classes.
   - Attach full lineage and reason code to every recommendation.

6. **Output publication**
   - Dashboard cards, SITREP narrative, and downstream ticket annotation payload.

## 4.3 Runtime components to deliver

- `cmdb_ingestor` service (batch + delta sync)
- `reconciliation_worker` service (async queue consumer)
- `context_graph_store` adapter (PostgreSQL/JSONB + embeddings)
- `policy_gate` middleware for recommendation eligibility
- `demo_orchestrator` profile for deterministic replay

## 4.4 Security and production controls

- RBAC scope checks on all write paths.
- Signed audit trails for inferred edges and operator overrides.
- Secrets from env/vault only; no fallback secrets in code.
- Schema version checks on ingest; reject unknown contract versions.
- Multi-tenant data partition enforcement (existing test suites retained).

## 5) Delivery Roadmap (12 Weeks)

## Wave 1 (Weeks 1-3): Integration Hardening

- Refactor `generate_cmdb.py` into reusable adapter package.
- Add idempotency, retry policy, and ingestion metrics.
- Define canonical schema and automated validation tests.

Exit criteria:

- 700+ CIs sync reproducibly into canonical store.
- Full ingest run report with success/failure lineage.

## Wave 2 (Weeks 4-6): Reconciliation Core

- Implement drift detection and finding classification.
- Implement confidence-scored latent edge inference with corroboration rules.
- Persist findings with provenance graph.

Exit criteria:

- At least 3 deterministic drift scenarios detected in replay.
- False-positive suppression demonstrated with policy constraints.

## Wave 3 (Weeks 7-9): Operator Experience + WOW Demo

- Deliver polished GTM demo route in Next.js.
- Add “before/after” CMDB truth panel and ROI deltas.
- Add scenario controls (planned change ghosting, dark graph reveal, policy block).

Exit criteria:

- End-to-end scripted demo runs in under 7 minutes.
- Zero manual DB edits required during run.

## Wave 4 (Weeks 10-12): Pilot-Ready Packaging

- Harden deploy artifacts (docker-compose profile + production env checklist).
- Finalize observability dashboard and runbooks.
- Publish pilot readiness scorecard and known-risk register.

Exit criteria:

- Repeatable deployment in staging.
- Security and tenancy regression tests passing.

## 6) Demo-Driven KPI Framework

Track and present:

- **Truth Recovery Rate:** % of stale/incorrect CMDB records reconciled.
- **Time to Causal Clarity:** event-to-trusted hypothesis time.
- **Dark Graph Yield:** validated hidden dependencies discovered.
- **Policy Safety Rate:** unsafe recommendations blocked before exposure.
- **Operator Acceptance:** recommendation acceptance ratio and override reasons.

## 7) GTM Readiness Gates

- Technical gate: stable ingestion + deterministic reconciliation in replay.
- Product gate: clear user-facing “why this matters” narrative in UI.
- Sales gate: vertical-specific packaging (Telco first, enterprise next).
- Compliance gate: auditability and explicit non-autonomous execution posture.

## 8) Key Risks and Mitigations

- **Risk:** Over-claiming autonomy.  
  **Mitigation:** Keep actuation disabled by default; lead with recommendation + evidence.

- **Risk:** CMDB schema variability across customers.  
  **Mitigation:** adapter contract + mapping templates + schema drift alerts.

- **Risk:** Demo fragility from external dependencies.  
  **Mitigation:** deterministic replay profile with local seed path.

## 9) Immediate Build Backlog (Next 10 Working Days)

1. Extract Datagerry client to `data_fabric/cmdb/datagerry_client.py`.
2. Implement canonical models for CI, Edge, Evidence, Finding.
3. Add reconciliation rule engine scaffold.
4. Add replay scenario loader for CasinoLimit slices.
5. Ship `/gtm-demo` UX page with narrative milestones.
6. Publish demo runbook + pitch deck narrative.

---

This plan aligns existing telco-strength technical assets to the narrower, higher-ROI wedge: **reconciling intent vs reality to heal enterprise operational memory**.
