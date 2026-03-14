# Autonomous Safety in Pedk.ai: Design Philosophy and Control Architecture

**Document Reference:** PEDKAI-REG-003
**Date:** March 2026
**Classification:** Public-facing
**Prepared by:** Pedk.ai Ltd
**Version:** 1.0

---

## Executive Summary

Pedk.ai is designed as a human-supervised AI platform: the system does not act unless a human has approved or pre-authorised the action type within a defined safety perimeter. Autonomy is earned incrementally, advancing through four discrete levels only when the operator chooses to do so, supported by configurable safety gates at every stage. The system cannot and does not take any action that bypasses human authorisation at the configured autonomy level — and at the default deployment level (Level 0), it takes no action whatsoever.

---

## 1. The Autonomy Spectrum

Pedk.ai's autonomy model is built on the principle that different operators have different risk appetites and different regulatory obligations. Rather than imposing a single mode of operation, the platform offers a structured progression that operators advance through deliberately.

| Level | Name | Pedk.ai's Role | Operator's Role |
|:-----:|------|---------------|-----------------|
| 0 | **Advisory Only** | Generates SITREPs. Recommends actions. Takes zero action. | Full manual control. Uses Pedk.ai as a diagnostic assistant. |
| 1 | **Assisted** | Creates draft tickets; pre-populates fields from SITREP analysis. | Reviews, approves, and dispatches every ticket before submission. |
| 2 | **Supervised** | Executes routine actions (e.g., ticket creation) with a configurable operator override window. | Monitors continuously; can veto any action within the override window. |
| 3 | **Gated Autonomous** | Executes pre-approved action types with all seven safety gates enforced. | Reviews safety gate audit trail. Can invoke kill-switch at any time. |

**Default deployment is Level 0.** The operator advances only when they choose to, and only after the governance prerequisites for each level are satisfied. Level 3 is not available in the initial product release; activation requires six months of Level 2 operational data, a false positive rate below 2%, board sign-off, and a refreshed Data Protection Impact Assessment.

The `ai_maturity_level` configuration parameter controls the active level. Changing it requires CTO approval, DPO review, and an engineering deployment. It cannot be changed at runtime via the API.

---

## 2. Seven Safety Gates

At Level 3 (Gated Autonomous), every proposed autonomous action must pass all seven safety gates in sequence before execution. A failure at any gate causes the action to be blocked; no partial execution occurs. The gates are:

### Gate 1 — Blast Radius

The system counts the number of distinct network entities that would be affected by the proposed action. If this count exceeds ten, the action is unconditionally rejected. This gate cannot be overridden by configuration. Its purpose is to ensure that no single autonomous action can trigger a large-scale change, even if every other gate passes.

### Gate 2 — Policy Rules

The proposed action type is evaluated against an operator-defined policy ruleset. Operators specify which action types are permitted for autonomous execution, which entity classes may be acted upon, and during which time windows autonomous execution is allowed. Actions not explicitly listed on the operator-approved allowlist are denied by default.

### Gate 3 — Confidence Threshold

The system's confidence score for the proposed action — derived from Decision Memory similarity search (cosine distance via pgvector) rather than from the LLM itself — must meet or exceed 85%. If confidence falls below this threshold, the action is escalated to human review. When no similar historical decisions exist in memory, the system defaults to a conservative 50% confidence, which always triggers escalation.

### Gate 4 — Maintenance Window

If the target network entities are currently within a scheduled maintenance window (as recorded in the ghost mask schedule), all autonomous action is suppressed. This prevents the system from taking actions that could conflict with planned engineering work or produce misleading post-execution KPI signals.

### Gate 5 — Duplicate Suppression

If an identical or functionally equivalent action has already been executed against the same target within the preceding 3,600 seconds, the proposed action is rejected. This prevents repeated execution of the same action in response to a fault that has not yet cleared, which could cause cascading interventions.

### Gate 6 — Human Gate

Actions assessed as HIGH risk — by virtue of their action type, the criticality of the target entity, or their blast radius approaching the threshold — require explicit human approval before execution. Emergency service entities flagged `is_emergency_service` in the operator's service inventory are unconditionally subject to this gate, regardless of any other configuration.

### Gate 7 — Rate Limit

A maximum of twenty autonomous actions per hour per tenant is enforced. This global rate cap exists as a final safeguard against runaway automation, regardless of whether each individual action passed all preceding gates. The rate limit is configurable downwards by the operator; it cannot be increased beyond twenty actions per hour in the base product.

---

## 3. Kill-Switch and Override Architecture

An emergency kill-switch endpoint (`POST /api/v1/autonomous/kill-switch`) is available to NOC operators at all times. Invoking the kill-switch has the following immediate effects:

- The system's effective autonomy level drops to Level 0 regardless of configuration.
- All autonomous actions executed within the preceding window are marked `rolled_back` in the audit trail, triggering post-hoc review.
- Further autonomous execution is halted pending an explicit operator instruction to resume.

The kill-switch is authenticated and requires a valid operator session token. It is not accessible to the AI components themselves; the system cannot invoke its own kill-switch. All kill-switch invocations are logged in the immutable audit trail with operator identity, timestamp, and the number of actions affected.

There are no cached approval states that could be exploited to bypass the kill-switch. Gate evaluations run in real time against live policy configuration. A policy change by the operator takes effect immediately for all subsequent gate evaluations; no in-flight action can rely on a stale policy state.

---

## 4. Audit Trail

Every event in the Pedk.ai system is recorded in the `decision_traces` table with an immutable timestamp and a unique correlation identifier (`trace_id`). The audit trail captures:

- Every SITREP generated, including the evidence fused and confidence score
- Every gate evaluation at Level 3, including whether it passed or failed and the evaluated value
- Every autonomous action attempted, whether executed, blocked, or rolled back
- Every operator override, kill-switch invocation, and manual approval
- Every instance of operator feedback, including the feedback channel and signal quality

Records in the audit trail cannot be modified after writing. The `trace_id` allows full reconstruction of the complete decision chain for any incident, from the initial telemetry anomaly through to the final operator disposition.

Audit records are retained for a minimum of two years in operational storage. For operators subject to Communications Act 2003 requirements, a seven-year retention configuration is available. All audit data remains within the operator's own infrastructure; Pedk.ai Ltd does not receive copies of audit records from customer deployments.

---

## 5. Failure Modes and Graceful Degradation

Pedk.ai is a read layer. It ingests telemetry from network elements; it does not have write access to network infrastructure. In the default deployment (Level 0–2), the system is physically incapable of modifying network element configuration, regardless of what its AI components recommend.

The consequences of system failure are therefore bounded:

- **If Pedk.ai becomes unavailable:** SITREPs stop being generated. NOC operators revert to standard manual procedures, which remain fully functional. No network operation is interrupted.
- **If the LLM service becomes unavailable:** SITREP text generation pauses. Anomaly detection, sleeping cell identification, and causal inference continue to operate and remain visible in the dashboard as structured data without natural language explanation.
- **If the database becomes unavailable:** The system enters a safe degraded state and queues incoming telemetry for processing once connectivity is restored. No data is lost; the write-ahead log ensures durability.

There is no single point of failure within Pedk.ai that could cause harm to the network. The platform is designed so that its failure mode is always a reduction in AI-assisted insight, never an uncontrolled action.

---

## 6. Comparison to Industry Standards

**IEEE 7000 (Model Process for Addressing Ethical Concerns During System Design):** Pedk.ai's autonomy spectrum and safety gate architecture implement the core IEEE 7000 principle of value-sensitive design: the system is built around the operator's right to remain in control, with every escalation path preserving human agency.

**EU AI Act (Regulation 2024/1689):** Pedk.ai does not meet the criteria for high-risk AI systems as defined in Annex III of the EU AI Act. The Act's high-risk categories relevant to network operations cover systems used in critical infrastructure management where AI directly controls infrastructure components. Pedk.ai is explicitly and architecturally a decision-support tool: it supports human decision-making without controlling infrastructure. The platform meets the Act's transparency obligations through mandatory AI watermarking on all generated content, confidence score disclosure, and the human oversight mechanisms described in this document.

**GSMA AI in Networks (PRD NG.140):** Pedk.ai's tiered autonomy model is consistent with the GSMA's recommended progressive autonomy framework for AI in mobile networks, which calls for human oversight at each automation tier and auditability of all AI-influenced decisions.

**Ofcom Statement on AI in Telecoms (2025):** Pedk.ai Ltd has filed a voluntary pre-notification with Ofcom (see PEDKAI-REG-001) in the spirit of General Conditions of Entitlement §A.3. The platform's read-only posture, mandatory human gates, and full audit trail are designed to support, not supplant, the operator's regulatory obligations under the Communications Act 2003.

---

*This document is reviewed quarterly and updated following any Level 3 safety incident or significant change to the autonomy architecture.*

*Next scheduled review: June 2026*

*Regulatory contact: regulatory@pedk.ai*
