# Pedkai V8 Execution Deep Dive (Implementation-Grade)

Date: 26 Feb 2026  
Purpose: Convert Vision V8 differentiators into executable engineering design.

---

## 0) Direct Answer to "How exactly will this work?"

Pedkai will not claim hidden dependency truth from one source or one model pass.  
Pedkai will infer only when:

1. Candidate structure is generated from intent artifacts,
2. Visibility constraints are explicitly modeled,
3. Multi-source corroboration reaches threshold,
4. Confidence and calibration gates pass,
5. Proof bundle is attached for operator inspection,
6. Policy engine authorizes exposure/action class.

This document defines the full pipeline for **each differentiator**:

- Dark Graph Inference
- Abeyance Memory
- Telemetry Cross-Examination
- Constitutional Guardrails
- Confidence, non-hallucination proof, and NOC presentation

It maps to current code surfaces:

- `backend/app/services/llm_service.py`
- `backend/app/services/policy_engine.py`
- `backend/app/services/causal_models.py`
- `backend/app/services/decision_repository.py`
- `backend/app/api/topology.py`
- `backend/app/models/topology_models.py`
- `backend/app/schemas/topology.py`
- `docs/confidence_methodology.md`

---

## 1) System Design: Intent/Reality/Memory with Explicit Visibility

## 1.1 Core state model

For each entity or edge hypothesis `h`, store:

- `state`: `{observed, inferred, disputed, stale, rejected}`
- `visibility_class`: `{telemetry_visible, telemetry_blind, partially_visible}`
- `evidence_set`: ordered references to all supporting/contradicting evidence
- `confidence`: numeric [0, 1], calibrated
- `lineage_hash`: deterministic hash over evidence IDs + rule IDs + model version

## 1.2 Why visibility must be first-class

Without visibility awareness, inference errors are indistinguishable from missing data.  
Pedkai therefore computes **telemetry reachability** before inference:

- A node/zone is telemetry-blind if no permitted collector path exists from configured ingest points.
- Blindness is stored as metadata, not treated as absence-of-fault.
- In blind zones, inference requires stronger corroboration and cannot claim "verified by telemetry".

Implementation extension:

- Add `visibility_class` to topology relation metadata (`topology_relationships.properties`).

---

## 2) Dark Graph Inference (Detailed)

## 2.1 Goal

Infer hidden dependencies in telemetry-blind areas while preventing correlation-driven hallucination.

## 2.2 Four-stage inference pipeline

### Stage A: Candidate generation (high recall, low precision)

Generate candidate edge `(A -> B, relation_type)` from:

- Change tickets (same maintenance window + shared implementation notes)
- Design docs (diagram adjacency or explicit dependency statements)
- CMDB drift deltas (coordinated updates across types)
- Incident co-occurrence signatures (time-constrained, repeated)

Output: candidate list with weak prior `p0`.

### Stage B: Corroboration scoring (precision builder)

For each candidate, compute evidence factors:

- `E_doc`: document/design corroboration score
- `E_change`: change ticket linkage score
- `E_temporal`: repeated temporal coupling score
- `E_config`: subnet/routing/config overlap score
- `E_memory`: similarity to validated historical patterns
- `E_counter`: contradiction penalty (evidence against edge)

Combine via weighted log-odds model:

$$
L(h) = \log\frac{p_0}{1-p_0} + \sum_i w_i E_i - w_c E_{counter}
$$

$$
p(h) = \sigma(L(h)) = \frac{1}{1+e^{-L(h)}}
$$

### Stage C: Structural consistency checks

Reject candidates that violate topology constraints:

- Invalid entity-type pairing (from ontology)
- Impossible hierarchy (e.g., service hosting transport primitive directly)
- Cycles where relation semantics require DAG behavior
- Violations of site/region boundaries unless explicit exception evidence exists

### Stage D: Promotion policy

Promotion from candidate to inferred edge:

- `p(h) >= T_infer` (default 0.85 for blind zones)
- at least `N>=3` independent evidence families
- no unaddressed hard contradiction
- policy gate allows exposure level

Else remain `hypothesis` in Abeyance queue.

## 2.3 "How does Pedkai identify invisible network and hierarchy?"

For blind segments:

1. Build partial hierarchy from CMDB + design docs + change artifacts.
2. Mark unknown parent links explicitly as unresolved graph gaps.
3. Fill gaps using constrained search:
   - type-compatibility,
   - geographic and naming priors,
   - historical validated motifs.
4. Rank candidate hierarchies by combined evidence likelihood.
5. Emit top-1 only if confidence and proof criteria pass, else show top-k hypotheses.

Pedkai never claims certainty for blind-zone hierarchy; it claims **ranked, evidenced hypotheses**.

---

## 3) Abeyance Memory (Detailed)

## 3.1 Problem solved

Operational clues arrive asynchronously. Useful facts are often non-actionable in isolation.

## 3.2 Data structure

Create `abeyance_clues` store:

- `clue_id`, `tenant_id`, `entity_refs[]`
- `fact_text`, `normalized_fact`
- `source_type` (ticket, attachment, runbook note, operator free text)
- `initial_confidence`, `expiry_at`, `status`
- `wake_triggers` (event patterns that reactivate evaluation)

## 3.3 Lifecycle

1. **Capture**: parse notes/docs into normalized clue atoms.
2. **Hold**: keep clue dormant if insufficient context.
3. **Wake**: trigger on matching future event/change/entity updates.
4. **Fuse**: re-run corroboration with newly available evidence.
5. **Resolve**: promote to evidence or retire with reason code.

## 3.4 Anti-pollution controls

- User-originated clues carry lower prior until corroborated.
- Repeated contradicted clues are down-weighted by source reliability score.
- Compromised-account risk can quarantine all clues from suspicious identity windows.

---

## 4) Telemetry Cross-Examination (Detailed)

## 4.1 Problem solved

Manual notes can be inaccurate or malicious. Learning directly from them is unsafe.

## 4.2 Rule engine behavior

For each operator claim `c` (e.g., "restarted firewall at t"):

1. Identify expected telemetry signatures `S(c)`.
2. Query telemetry windows `[t-Δ, t+Δ]` for those signatures.
3. Compute claim-verification score:

$$
V(c) = \alpha\cdot match\_strength - \beta\cdot contradiction\_strength
$$

4. Decision:
   - `V(c) >= T_accept`: accepted as training evidence
   - `T_review <= V(c) < T_accept`: keep with warning
   - `< T_review`: reject and flag dissonance

## 4.3 Blind-zone adaptation

If no telemetry visibility:

- do not auto-accept,
- request auxiliary corroboration (attachments/config diffs/change logs),
- keep as hypothesis until corroborated.

This prevents "absence of telemetry" from becoming false validation.

---

## 5) Constitutional Guardrails (Detailed)

Current base exists in `policy_engine.py`. Extend policy scope from action gating to inference governance:

## 5.1 New policy dimensions

- `min_confidence_by_visibility` (e.g., blind zone requires 0.85+)
- `min_evidence_families` (e.g., 3+ independent sources)
- `max_unresolved_contradictions` (usually 0 for promoted edges)
- `allowed_exposure_modes` (hypothesis-only vs verified recommendation)
- `high_impact_confirmation_required` (for revenue/SLA-critical outputs)

## 5.2 Decision classes

- `ALLOW_PROMOTION`
- `ALLOW_HYPOTHESIS_ONLY`
- `DENY_AND_ESCALATE`

All classes must log matched/failed gates in audit trail.

---

## 6) Confidence, Proof, and "Not Hallucinating"

## 6.1 Confidence model upgrade

Reuse existing calibrated framework (`docs/confidence_methodology.md`) and add inference-specific terms:

$$
C = clamp(0, 0.95, C_{memory} + C_{causal} + C_{corroboration} - P_{contradiction} - P_{visibility})
$$

Where:

- `P_visibility` penalty is larger in telemetry-blind segments unless multi-source corroboration is high.
- Calibration bins expanded to include visibility class and evidence-family count.

## 6.2 Proof bundle (mandatory for every inferred edge)

For each inference, persist and expose:

- evidence items (IDs, source types, timestamps)
- rule IDs and weight contributions
- contradiction checks and outcomes
- policy gates evaluated and result
- model/version identifiers
- lineage hash

If proof bundle is incomplete, inference cannot be promoted.

## 6.3 Hallucination controls

- No LLM-only structural claims.
- LLM may summarize; it cannot create graph edges without structured evidence pass.
- Deterministic rule engine decides promotion; LLM outputs are advisory text.

---

## 7) NOC Presentation Contract (Useful, Not Opaque)

## 7.1 UI states for each relationship

- **Observed** (telemetry-backed)
- **Inferred-Verified** (multi-source corroborated)
- **Hypothesis** (insufficient confidence)
- **Disputed** (contradictions present)

## 7.2 Operator card requirements

Each inferred edge card must show:

- confidence score + confidence band
- visibility class
- evidence-family count and source breakdown
- top supporting evidence snippets
- contradiction summary
- policy decision outcome
- action affordances: accept / reject / request evidence

## 7.3 Explainability text template

"Pedkai inferred `A depends_on B` with confidence `0.88` in a telemetry-blind segment, based on 4 independent evidence families (change ticket linkage, design artifact adjacency, CMDB co-drift, prior validated motif). No hard contradictions found. Policy gate: ALLOW_PROMOTION."

---

## 8) Data Contracts and Storage Additions

## 8.1 Topology relationship metadata extension

Add JSON fields to relationship properties:

- `state`
- `visibility_class`
- `confidence`
- `evidence_bundle_id`
- `policy_decision`

## 8.2 New tables

1. `inference_hypotheses`
2. `evidence_items`
3. `abeyance_clues`
4. `inference_audit`

Each table must include tenant isolation key and immutable timestamps.

---

## 9) Implementation Plan (8 Weeks, Engineering-Realistic)

## Weeks 1-2: Foundations

- Add visibility modeling and schema extensions.
- Build evidence ingestion abstraction (`EvidenceItem` adapters).
- Create hypothesis store + API scaffolding.

Deliverable: blind-zone aware graph state available via API.

## Weeks 3-4: Inference Engine v1

- Candidate generation + corroboration scoring.
- Structural consistency validator.
- Promotion policy integration with `policy_engine`.

Deliverable: inferred/hypothesis edges with proof bundle IDs.

## Weeks 5-6: Abeyance + Cross-Examination

- Implement clue capture/wake/fuse lifecycle.
- Implement manual-claim telemetry verifier.
- Add reliability scoring for evidence sources.

Deliverable: contradiction-aware learning gate.

## Weeks 7-8: NOC UX + Calibration

- Add operator cards and evidence drill-down.
- Extend confidence calibration bins.
- Add acceptance/rejection feedback loop.

Deliverable: operator-grade explainable inference flow.

---

## 10) Acceptance Criteria (What "Done" Actually Means)

1. In blind-zone replay dataset, inferred edges achieve:
   - precision >= 0.85,
   - contradiction leak <= 0.05.
2. 100% promoted edges include complete proof bundle.
3. LLM-only edge creation is impossible by design (enforced in tests).
4. Operator replay study shows >= 70% acceptance for high-confidence inferred edges.
5. Policy audit log reconstructs every promotion decision end-to-end.

---

## 11) Test Strategy (Must Exist Before Pilot)

- Unit tests: scoring, structural validator, policy promotion gates.
- Integration tests: end-to-end inference with synthetic blind segments.
- Adversarial tests: poisoned operator notes, contradictory evidence injection.
- Determinism tests: same evidence set => same lineage hash and decision.

---

## 12) What Changes in the Pitch Language

Use claims that are now technically provable:

- "Inference is evidence-gated, not model-asserted."
- "Every hidden dependency includes a machine-verifiable proof bundle."
- "Blind segments are explicitly marked and held to stricter thresholds."
- "NOC sees confidence, contradiction, and policy verdict before action."
