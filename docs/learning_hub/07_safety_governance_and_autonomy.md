# Safety, Governance, and Autonomy

**Audience:** NOC engineers, shift leads, and NOC managers
**Time to read:** 12 minutes

---

## The 7 Safety Gates

At the highest autonomy levels, every proposed autonomous action must pass all seven safety gates in sequence before execution. If any gate blocks the action, no partial execution occurs — the action is rejected and the engineer is notified.

Understanding the gates helps you understand why an action was blocked and what that means for how you respond.

### Gate 1 — Blast Radius

The system counts how many distinct network entities would be affected by the proposed action. If this count exceeds ten, the action is unconditionally rejected.

This gate has no override. Its purpose is a hard limit: no single autonomous action can trigger a large-scale change, regardless of confidence or operator policy.

**If this gate blocks an action:** The proposed action scope is too wide for autonomous execution. A human must break it down into smaller steps or take manual action.

### Gate 2 — Policy Rules

The action type is evaluated against the operator's policy configuration. This specifies which action types are permitted for autonomous execution, which entity classes may be acted upon, and during which time windows autonomous execution is allowed.

Actions not on the explicit allowlist are denied by default.

**If this gate blocks an action:** The action type is either not approved for autonomous execution by your organisation, or it is outside the permitted time window. Contact Engineering if you believe the policy should be extended.

### Gate 3 — Confidence Threshold

The confidence score for the proposed action must meet or exceed 85% for autonomous execution. Below this threshold, the action is escalated to human review.

When no similar historical decisions exist in Decision Memory, the system defaults to 50% confidence — always triggering human escalation.

**If this gate blocks an action:** pedk.ai does not have enough historical evidence to be confident this action is appropriate. Human judgement is required.

### Gate 4 — Maintenance Window

If the target entity is currently within a scheduled maintenance window (a Ghost Mask entry), all autonomous action is suppressed.

**If this gate blocks an action:** A maintenance window is active. This is by design — autonomous actions during planned maintenance could conflict with field team work or produce misleading post-execution KPI signals.

### Gate 5 — Duplicate Suppression

If an identical action has already been executed against the same target in the last hour, the proposed action is rejected.

**If this gate blocks an action:** A recent action on this entity is already recorded. Check whether the first action resolved the issue before taking further steps.

### Gate 6 — Human Gate

Actions assessed as HIGH risk — due to action type, entity criticality, or blast radius approaching the threshold — require explicit human approval before execution.

Emergency service entities flagged `is_emergency_service` are unconditionally subject to this gate regardless of any other configuration. This protection cannot be disabled.

**If this gate blocks an action:** You need to explicitly approve it. Open the incident in the NOC dashboard and use the **Approve Action** button.

### Gate 7 — Rate Limit

A maximum of 20 autonomous actions per hour per tenant is enforced. This global rate cap exists as a final safeguard against runaway automation.

**If this gate blocks an action:** The system has executed a high volume of autonomous actions this hour. Review whether the rate is appropriate for current conditions. Contact Engineering if you believe the rate limit is incorrectly set.

---

## When pedk.ai Escalates vs Acts Autonomously

The autonomy level configured for your deployment determines this boundary:

| Level | pedk.ai action on a recommended change | Your responsibility |
|-------|----------------------------------------|---------------------|
| **Level 0 (Advisory)** | None — generates SITREP only | You decide whether to act and take action yourself |
| **Level 1 (Assisted)** | Creates draft ticket; waits for approval | Review and approve every draft before dispatch |
| **Level 2 (Supervised)** | Executes routine actions with an override window | Monitor and veto within the window if needed |
| **Level 3 (Gated Autonomous)** | Executes pre-approved actions after all 7 gates pass | Review gate audit trail; invoke kill-switch if needed |

Most operators run at Level 0 during initial deployment. The default is deliberately conservative: no autonomous action at all.

Advancing to higher levels requires organisational and governance prerequisites that cannot be activated through the dashboard — changes to `ai_maturity_level` require Engineering deployment with CTO approval. If your team is considering moving to a higher autonomy level, speak to your NOC Manager first.

---

## How to Approve or Reject Autonomous Actions

At Level 2 and Level 3, the Human Gate 6 requires explicit approval for high-risk actions. This is done in the NOC dashboard:

**To approve an action:**
1. Open the relevant incident in `/incidents`
2. Navigate to the **Recommended Action** section
3. Review the action details, target entity, and the safety gate evaluation summary
4. Click **Approve Action** — this requires the `incident:approve_action` RBAC scope
5. The action proceeds and is logged in the audit trail with your operator ID and timestamp

**To reject an action:**
1. Open the incident
2. Click **Reject Action**
3. Select a reason code from the list
4. Add a free-text explanation of why the action is not appropriate
5. The action is blocked and logged; pedk.ai will not re-attempt the same action without further operator instruction

**The override window (Level 2):** At Level 2, routine actions proceed after a configurable delay (default 30 seconds) unless vetoed. During this window, you will see a banner in the incident view with a countdown and a **Veto** button. If you do not act within the window, the action proceeds. If you click Veto, the action is cancelled and your veto is logged.

---

## Regulatory Context

pedk.ai's safety architecture is designed to meet or support compliance with several regulatory frameworks:

**Ofcom / Communications Act 2003:** pedk.ai filed a voluntary pre-notification with Ofcom before pilot deployment. The platform's read-only posture at Levels 0–2, mandatory human gates, and full audit trail support the operator's network reliability obligations. Emergency service entities (999/112 infrastructure) are hardcoded as a mandatory human gate at all autonomy levels.

**ICO / UK GDPR:** Network telemetry is processed as aggregate, non-personal data. Operator interactions are recorded via pseudonymous `operator_id` identifiers. PII scrubbing is applied before any data is sent to external LLM providers. The data processing agreement with Google (Gemini API) is governed by Standard Contractual Clauses.

**EU AI Act:** pedk.ai does not meet the EU AI Act's definition of a high-risk AI system because it supports — not replaces — human decision-making. All AI-generated content is watermarked. Confidence scores are disclosed. Human oversight mechanisms are enforced at all levels.

**IEEE 7000 / GSMA AI in Networks:** The tiered autonomy model is consistent with GSMA's progressive autonomy framework and IEEE 7000's value-sensitive design principles.

---

## Audit Trail

Every event in pedk.ai is recorded in the audit trail with an immutable timestamp and a unique `trace_id`. This includes:
- Every SITREP generated, with confidence score and evidence
- Every gate evaluation at Level 3, including pass/fail and the evaluated value
- Every autonomous action attempted, executed, blocked, or rolled back
- Every human approval, rejection, override, and kill-switch invocation
- Every operator feedback submission

The audit trail cannot be modified. Records are retained for a minimum of two years in operational storage; seven years for operators with Ofcom-regulated retention obligations.

**Why this matters for you:** The audit trail documents every decision — yours and the AI's. If a decision needs to be reviewed after the fact (regulatory inquiry, major outage investigation, or internal review), the full chain from initial telemetry anomaly to final resolution is available for reconstruction.

The accountability principle is non-negotiable: approving a pedk.ai recommendation is an active decision with the same accountability consequences as initiating the same action independently. The AI recommendation does not transfer accountability.

---

## Emergency Kill-Switch

At any time, a NOC operator with sufficient RBAC scope can invoke the emergency kill-switch:

**Via the dashboard:** Settings > System Controls > Emergency Stop

**Effect:** pedk.ai's effective autonomy level drops to Level 0 immediately, all recent autonomous actions are flagged for review, and further autonomous execution is halted until explicitly re-enabled.

The kill-switch is authenticated and fully audit-logged. It cannot be invoked by the AI itself. Use it without hesitation if you observe pedk.ai behaving unexpectedly at higher autonomy levels.
