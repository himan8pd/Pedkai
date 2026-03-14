# AI Behaviour Specification

**Document Reference:** PEDKAI-REG-004
**Date:** March 2026
**Classification:** Confidential — Operator and Regulator Distribution
**Prepared by:** Pedk.ai Ltd
**Version:** 1.0

---

## Purpose

This document formalises what Pedk.ai's AI components are permitted and forbidden to do at each autonomy level. It exists to provide operators, their Data Protection Officers, and relevant regulatory bodies with an unambiguous, verifiable description of AI behaviour boundaries — removing reliance on informal assurances and ensuring that governance commitments can be independently tested against implementation.

This specification is binding. Any change to the permitted or forbidden behaviour listed here constitutes a material change to the product and requires the review and sign-off process described in the final section of this document.

---

## Permitted Behaviours by Level

### Level 0 — Advisory Only

At Level 0, Pedk.ai is a pure intelligence layer. It observes, analyses, and advises. It does not act.

**PERMITTED:**
- Generate Situation Reports (SITREPs) from telemetry analysis, including anomaly identification, root cause assessment, and recommended corrective actions expressed as text
- Identify sleeping cells — network elements that have silently degraded and produce no alarms despite active subscriber impact
- Identify alarm correlation patterns and present them with confidence scores derived from Decision Memory
- Recommend corrective actions as advisory text; such recommendations carry no execution capability at this level
- Update Decision Memory with operator feedback signals (thumbs up/down, structured assessment scores, and behavioural observation where the feedback pipeline is active)
- Run causal inference analysis (Granger Causality; Transfer Entropy and PCMCI where enabled) and present causal graphs to operators
- Run dark graph analysis to identify divergence between topological map state and live network state
- Compute subscriber impact estimates and revenue-at-risk figures, flagged `is_estimate: true` where derived from estimated rather than confirmed billing data
- Ingest and process telemetry, alarm events, and OSS/BSS data within the operator's configured perimeter

**FORBIDDEN:**
- Take any action on network infrastructure, including but not limited to: configuration changes, service restarts, parameter adjustments, or session terminations
- Create, modify, submit, or close ITSM tickets in any downstream system
- Send notifications, emails, or messages of any kind without explicit operator instruction
- Modify its own configuration, including safety gate thresholds, confidence thresholds, autonomy level, or policy rules
- Access systems, data stores, or APIs outside the operator-defined integration perimeter

---

### Level 1 — Assisted

At Level 1, Pedk.ai may prepare work for human review. It does not submit anything.

**PERMITTED (in addition to Level 0):**
- Draft ITSM tickets, pre-populating fields (summary, description, category, affected CIs, severity) from SITREP analysis
- Present draft tickets to operators for review before any submission action is available
- Pre-populate ticket fields with evidence citations from the underlying telemetry

**FORBIDDEN:**
- Submit any ticket to a downstream ITSM system without explicit operator approval action
- Close, modify, or reassign existing tickets
- All forbidden behaviours listed under Level 0

---

### Level 2 — Supervised

At Level 2, Pedk.ai may execute limited, reversible actions within a configurable human override window. The operator retains veto power throughout.

**PERMITTED (in addition to Level 1):**
- Create ITSM tickets in the connected system after the operator override window has elapsed without a veto (override window is configurable between 5 and 60 minutes; default is 30 minutes)
- Acknowledge low-priority alarms where the operator has configured alarm acknowledgement as a permitted Level 2 action
- Notify the operator of pending actions approaching their override window expiry

**FORBIDDEN:**
- Modify network element configuration of any kind
- Close, escalate, or reassign incidents without explicit operator review and approval
- Execute any action after the override window has elapsed if the operator has raised a veto during that window
- Modify the override window duration or policy configuration at runtime
- All forbidden behaviours listed under Level 0 and Level 1

---

### Level 3 — Gated Autonomous

At Level 3, Pedk.ai may execute a constrained set of pre-approved actions, but only after all seven safety gates pass. The operator defines the action allowlist; Pedk.ai cannot expand it.

**PERMITTED (in addition to Level 2, only after all seven safety gates pass):**
- Execute action types that appear on the operator-configured autonomous execution allowlist
- Acknowledge alarms in alarm categories explicitly listed on the operator allowlist
- Create ITSM tickets for fault patterns that meet the confidence threshold and blast radius constraints
- Close ITSM tickets for routine fault patterns where closure is on the operator allowlist and the fault has been confirmed resolved by post-execution KPI validation

**FOREVER FORBIDDEN (at any level, regardless of configuration):**
- Modifying network element configuration — router parameters, base station parameters, transmission settings, or any other network infrastructure configuration
- Disabling, bypassing, or suppressing monitoring systems or alarm feeds
- Accessing systems, data stores, or APIs outside the operator-defined integration perimeter
- Reading, processing, or acting on data belonging to any tenant other than the authorised `tenant_id` of the active session
- Self-modifying any safety gate threshold, confidence threshold, autonomy level setting, or policy rule
- Invoking its own kill-switch or executing any action that would reduce its own safety constraints
- Operating on emergency service entities without explicit human gate approval, at any autonomy level

---

## Behavioural Constraints

**Read-only posture against network infrastructure.** Pedk.ai holds no write credentials to any network element, OSS platform, or network management system. At Levels 0–2, this architectural constraint makes autonomous network action technically impossible, not merely policy-prohibited. At Level 3, the only write actions available are to ITSM ticketing systems and alarm management systems via APIs explicitly provisioned by the operator. The system does not and cannot issue NETCONF, SNMP write, CLI, or any other network configuration protocol command.

**Evidence-grounded recommendations.** Every recommendation generated by Pedk.ai cites specific telemetry evidence that supports it: the metric values observed, the time window of the anomaly, the alarm events correlated, and the causal path identified. Pedk.ai does not generate recommendations without a traceable evidentiary basis in the ingested data. All AI-generated content carries a mandatory watermark identifying it as AI-generated and advisory. Confidence scores are derived from Decision Memory similarity search, providing an independent signal separate from the LLM that generates the natural language explanation.

**Uncertainty is always expressed.** The system does not produce overconfident outputs. Where confidence is below the configured threshold, the recommendation is explicitly marked as low-confidence and escalated for human review. Where the underlying data is estimated rather than confirmed — for example, subscriber impact figures derived from incomplete billing data — the `is_estimate: true` flag is propagated through all outputs. Pedk.ai does not suppress uncertainty to produce cleaner outputs; expressing the limits of its knowledge is a core design requirement, not an optional feature.

---

## Review and Update Process

This behaviour specification is reviewed and updated:

- On a regular six-month cycle, regardless of whether any incidents have occurred
- Within thirty days of any Level 3 autonomous action that resulted in an unexpected outcome, a rolled-back action, or a kill-switch invocation
- Whenever a change is proposed to the permitted or forbidden behaviour at any level
- When material changes are made to the safety gate architecture described in PEDKAI-REG-003

Changes to this specification require written sign-off from:

1. **Chief Technology Officer** — confirming the proposed change is architecturally sound and implementable without weakening the safety constraints
2. **Customer Data Protection Officer** (or equivalent) — confirming the change does not introduce new data protection risks or conflict with the operator's DPIA
3. **Regulatory Affairs Lead** — confirming the change does not create new obligations or conflicts with applicable telecommunications or AI regulation

No change to permitted behaviour at Level 3 takes effect until the operator's policy configuration is explicitly updated to include the new action type on the allowlist. An update to this specification alone does not automatically expand the set of actions the system can execute; a deliberate operator configuration change is always required.

A version history of this document is maintained in the Pedk.ai document management system. Previous versions are retained and available for regulatory inspection.

---

*Next scheduled review: September 2026*

*For questions regarding this specification: regulatory@pedk.ai*
