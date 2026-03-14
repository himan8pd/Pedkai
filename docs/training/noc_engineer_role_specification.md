# AI-Adjusted NOC Engineer Role Specification

**Document Reference:** PEDKAI-HR-001
**Date:** March 2026
**Applicable Deployment:** Pedk.ai Level 0–3

---

## 1. Role Overview

The Network Operations Centre (NOC) Engineer working alongside Pedk.ai occupies a fundamentally changed role. In a traditional NOC, the engineer's primary cognitive load is investigative: sifting a high-volume alarm stream, manually correlating events, forming hypotheses about root causes, and racing to establish situational awareness before the fault cascades. The role is reactive and largely consumed by triage.

With Pedk.ai deployed at Level 0 (Advisory) or above, the primary cognitive load shifts. Pedk.ai handles the first layer of alarm correlation, topology traversal, causal inference, and SITREP generation. The engineer no longer needs to ask "what is happening?" as the first question — Pedk.ai answers that question, to a measurable confidence level, before the engineer opens the incident. The engineer's first question becomes: "Is the AI correct, and what should I do about it?"

This is a supervisory, critical-reasoning role. It requires the engineer to maintain deep technical competence — both to evaluate AI recommendations and to operate independently when Pedk.ai is unavailable — whilst also developing new skills in AI literacy and structured feedback. The role's value is no longer primarily measured in alarms acknowledged per shift; it is measured in the quality of oversight decisions and the accuracy of feedback that improves the system over time.

Neither role is easier. The nature of the cognitive work is different, and this specification defines that new shape.

---

## 2. Core Responsibilities

### 2.1 AI Supervision (New — Primary Responsibility)

The engineer's most important function in a Pedk.ai-assisted NOC is active, critical supervision of AI outputs. This is not passive monitoring. It requires deliberate engagement with each SITREP.

For every AI-generated SITREP:

- **Review for accuracy**: Does the executive summary match the alarm cluster? Has Pedk.ai correctly identified the root cause entity, or has it attributed the incident to a correlated but downstream component?
- **Review for completeness**: Does the SITREP reflect the full scope of the fault? Are there alarms from adjacent network domains that have not been included in the cluster?
- **Assess confidence scores**: Pedk.ai attaches a confidence score (0.0–0.95, capped at 0.95 — the system never claims certainty) to every recommendation. Scores below 0.50 trigger a `[LOW CONFIDENCE — TEMPLATE FALLBACK]` prefix, indicating that the AI has insufficient evidence for analysis. Scores in the 0.50–0.74 range require careful manual cross-checking against raw alarms. High-confidence outputs (0.75–0.95) are generally reliable but must still be reviewed — confidence reflects evidence quality, not infallibility.
- **Flag anomalous AI behaviour**: If Pedk.ai is consistently over- or under-estimating confidence for a specific network domain, equipment vendor, or fault type, this should be escalated to the Engineering team as a potential model calibration issue.
- **Provide structured approval or override**: At Level 0, engineers review recommendations and decide which to act upon. At Level 1 and above, the human gates (sitrep approval, action approval, incident close) must be exercised with genuine scrutiny, not as rubber-stamps.

### 2.2 Alarm Management (Evolved — Reduced Volume)

Pedk.ai pre-filters the raw alarm stream through temporal and topology-based correlation, collapsing what may be hundreds of related alarms into a single managed cluster with an identified root cause entity. The engineer no longer reviews individual alarms in sequence; they review Pedk.ai's cluster assessments.

This changes the skill required. The engineer must understand:

- Whether the clustering logic is sound for the specific fault type (some fault patterns, such as software-driven cascades, may require different correlation windows than hardware failures)
- Whether alarm suppression has obscured a secondary fault beneath the primary cluster
- How to interrogate the raw alarm source (Ericsson ENM, Nokia NetAct) directly when Pedk.ai's cluster seems incomplete

The reduced alarm volume is only beneficial if the engineer trusts it appropriately. Novel alarm patterns — those outside Pedk.ai's training distribution, for instance arising from a new equipment vendor rollout or an unprecedented failure mode — will often surface as low-confidence outputs or will be left unclustered. The engineer is specifically responsible for recognising and escalating these situations, which are precisely the cases where Pedk.ai's contribution is smallest and the engineer's domain expertise is most critical.

### 2.3 Incident Management (Evolved — Guided Workflow)

Pedk.ai integrates with the ITSM workflow at each autonomy level:

- **Level 0 (Advisory)**: The engineer initiates incidents from SITREP recommendations. Pedk.ai has produced the diagnostic analysis; the engineer decides whether to open a ticket and populates it, drawing on the SITREP content.
- **Level 1 (Assisted)**: Pedk.ai generates draft tickets pre-populated with root cause, severity, and recommended action. The engineer reviews every draft before approving and dispatching. The engineer's role here is to catch errors before they propagate into the ITSM record.
- **Level 2+ (Supervised/Gated Autonomous)**: The engineer monitors actions executed within the override window and exercises the veto if the action is unsafe or premature.

In all cases, resolution coding at incident closure is a high-value activity. How the engineer codes the resolution — and whether it matches or diverges from Pedk.ai's recommendation — is ingested as a behavioural learning signal. Engineers should treat resolution coding as a contribution to system improvement, not an administrative afterthought.

### 2.4 Sleeping Cell Monitoring (New Workflow)

Sleeping cells are a specific fault category that produces no alarms — a cell may be attached, registered, and apparently functional, whilst delivering severely degraded throughput or producing zero traffic. Because there is no alarm to act as a trigger, sleeping cells are invisible to traditional alarm-driven NOC workflows.

Pedk.ai's Sleeping Cell Monitor detects these faults through KPI pattern analysis, identifying cells where KPI metrics have degraded whilst alarm feeds remain silent. The decay scoring system assigns each suspect cell a score reflecting the probability and severity of the sleeping condition.

The engineer's responsibilities in this workflow are:

- **Periodic dashboard review**: The Sleeping Cell Monitor must be reviewed at a cadence agreed with the shift lead — Pedk.ai will not alert on a sleeping cell via the standard alarm channel.
- **Hypothesis validation**: When Pedk.ai flags a cell with a high decay score, the engineer should cross-reference against field team reports, maintenance logs, and recent change history before raising an incident. A recently completed antenna maintenance task may explain a temporary KPI dip.
- **Threshold management**: The decay score threshold that triggers dashboard escalation is configurable. Engineers should raise threshold calibration concerns with Engineering if they observe excessive false positives or missed sleeping cells in their network.

### 2.5 Override and Escalation (Critical Responsibility)

The override mechanism is one of the most important controls in the Pedk.ai system. An override occurs when the engineer determines that Pedk.ai's recommendation is incorrect, unsafe, or inapplicable, and proceeds with a different course of action. Overrides must be exercised freely and without hesitation when warranted.

Situations that should trigger an override include:

- **Confidence below threshold**: When Pedk.ai's confidence score falls below 0.50, the system is effectively signalling that it has insufficient data for a reliable recommendation. Manual triage is required.
- **Suspected stale CMDB data**: Pedk.ai's Dark Graph analysis depends on topology data from the CMDB. If the CMDB has not been updated to reflect recent infrastructure changes (equipment replacement, cell reconfiguration, fibre rerouting), Pedk.ai may produce plausible-looking but incorrect root cause attributions. Engineers with direct knowledge of recent changes should treat topology-dependent recommendations with caution.
- **Maintenance activity not yet reflected in system**: Network maintenance windows may not be captured in Pedk.ai's data in real time. An alarm cluster arising during a planned maintenance window may be attributable to the maintenance activity itself, not an incident.
- **Novel failure mode**: If the fault pattern does not match any known failure archetype — particularly in newly deployed equipment or software versions — Pedk.ai's pattern-matching may select the nearest historical analogue incorrectly. The engineer's domain expertise is the primary defence in this scenario.

All overrides must be documented with a reason code via the Override button in the NOC dashboard. This documentation is the highest-quality learning signal available to the Pedk.ai system — a structured override with a clear reason code is significantly more informative than a thumbs-down click, because it tells the system not merely that something was wrong but precisely what was wrong and what the correct action was.

---

## 3. Required Skills

### 3.1 Retained Technical Skills

The following technical competencies remain essential and must not atrophy:

- **RAN/Core/Transport fault analysis**: The ability to independently diagnose network faults from first principles, without AI assistance. This is required for degraded-mode operations, for evaluating Pedk.ai recommendations in novel fault scenarios, and for the periodic deep-dive investigations that AI-assisted triage surfaces but does not resolve.
- **CMDB querying and interpretation**: Understanding of the CMDB data model, its known gaps, and its typical staleness characteristics. Required to evaluate whether Pedk.ai's topology-dependent recommendations are based on current data.
- **ITSM workflow**: Ticket creation, classification, routing, and resolution coding in the ITSM platform. Required at all autonomy levels.
- **Alarm correlation**: Manual alarm correlation against OSS tools (ENM, NetAct) is the fallback for all situations where Pedk.ai is unavailable or producing low-confidence outputs.
- **Vendor-specific tooling**: Direct access to Ericsson ENM, Nokia NetAct, Huawei iMaster, and equivalent tools remains necessary. Pedk.ai ingests from these sources; it does not replace them.

### 3.2 New AI Literacy Skills

Engineers working alongside Pedk.ai must develop the following:

- **Confidence score interpretation**: Understanding what a score of 0.62 means in practical terms — what evidence mix produced it, why it is not high enough to approve without scrutiny, and what additional checks are proportionate.
- **Dark Graph visualisation reading**: The ability to navigate the topology visualisation, identify CMDB divergences surfaced by Pedk.ai, and understand what a "dark edge" (an inferred but undocumented dependency) represents and why it might be relevant to the current incident.
- **Structured feedback provision**: Writing override reason codes and structured assessments that are technically specific, not vague. "Root cause wrong — actual cause was transport link flap upstream, not baseband unit failure" is useful feedback. "Recommendation unhelpful" is not.
- **AI failure mode recognition**: Awareness of the specific ways Pedk.ai can be wrong — overconfidence on fault patterns it has seen many times before but which are presenting slightly differently; stale-data effects on topology reasoning; false pattern matches on novel fault types outside the training distribution. These are not hypothetical risks; they will occur.

### 3.3 Critical Thinking (Elevated Importance)

The most significant risk in AI-assisted NOC operations is automation bias: the tendency to accept AI recommendations without adequate scrutiny because they arrive with apparent authority, are presented clearly, and are usually correct. Overcoming automation bias requires active effort.

Engineers must maintain a posture of healthy scepticism. The fact that Pedk.ai has identified a root cause does not mean the root cause is correct. The fact that a confidence score is 0.82 does not mean the remaining 18% of uncertainty is negligible in the current context. The engineer who has seen a similar fault type handled differently three months ago, or who knows that a vendor software upgrade was rolled out this week, has information that Pedk.ai may not have — and that information may be decisive.

Independence of judgement must be explicitly preserved. The NOC shift lead is responsible for ensuring that override capability is exercised freely, that no engineer feels pressure to accept AI recommendations, and that override rates are reviewed at team level. An override rate that is too low (consistently below 10%) may indicate rubber-stamping rather than genuine review.

---

## 4. Performance Metrics

| Metric | Pre-AI Baseline | AI-Assisted Target |
|---|---|---|
| Mean Time to Resolve (MTTR) | Existing baseline | 15% reduction year 1 |
| Override rate | N/A | 10–30% (too low = rubber-stamping; too high = AI not helping) |
| Structured feedback rate | N/A | >80% of overrides with specific reason codes |
| Structured assessment completion | N/A | >70% of SITREPs rated on accuracy, relevance, and actionability |
| False escalation rate | Existing baseline | 20% reduction year 1 |
| Degraded-mode drill pass rate | N/A | 100% annually |

Override rate is the most operationally important metric here. It is a two-tailed concern: too low suggests the team is not exercising genuine critical review; too high suggests the AI is not delivering value or has a miscalibration issue that Engineering needs to address. The target band of 10–30% is indicative and should be reviewed in the context of deployment maturity and the specific network environment.

---

## 5. Training Requirements

All NOC engineers must complete the following before working with Pedk.ai in any advisory or higher mode:

**Initial 3-day training programme:**

- Day 1: AI fundamentals for NOC engineers — how Pedk.ai works, what the autonomy levels mean, confidence score interpretation, Dark Graph concepts. Includes hands-on exercises with the Sleeping-Cell-KPI-Data synthetic environment.
- Day 2: Human gate operations — the 3-gate incident lifecycle, RBAC scopes and responsibilities, how to approve and reject at each gate. Practical exercises simulating high-confidence and low-confidence scenarios.
- Day 3: Feedback and override mechanics — structured override coding, structured SITREP assessment, degraded-mode operations drill. Assessment and sign-off.

**Prerequisites for Level 2+ deployment sign-off:** Engineers operating in Supervised or Gated Autonomous mode must complete an additional half-day assessment, demonstrating the ability to correctly identify 4 out of 5 scenarios requiring override intervention in a proctored exercise using the synthetic environment.

**Annual refresher:** 4-hour refresher covering any changes to Pedk.ai's recommendation logic, updates to confidence score thresholds, and a degraded-mode tabletop exercise. Mandatory completion before shift sign-off is renewed.

All training exercises use the Sleeping-Cell-KPI-Data synthetic dataset, which is specifically designed to generate sleeping cell scenarios with zero alarms, forcing engineers to practise the non-alarm-driven detection workflow that is absent from traditional NOC training.

---

## 6. Accountability Framework

Engineer accountability in a Pedk.ai-assisted NOC is unchanged in one critical respect: the engineer who approves an action is responsible for that action. The AI recommendation does not transfer accountability. Approving a Pedk.ai-recommended action is an active decision with the same accountability consequences as initiating the same action independently.

This principle is deliberately unambiguous. It exists to prevent the erosion of accountability that can occur when AI-generated recommendations are treated as a form of organisational cover — "the AI said to do it" is not a valid explanation for an approved action that caused an outage.

The audit trail — which records every AI recommendation, confidence score, and operator decision with timestamps and user IDs — supports this accountability framework by making every decision legible after the fact. Engineers should be aware that the audit trail is permanent and complete.

Conversely, engineers must not allow accountability concerns to create a chilling effect on override behaviour. Overriding the AI when the override is technically justified is the correct exercise of the engineer's responsibility, not an act of defiance. The documented override with a reason code is precisely how the accountability framework is satisfied — it records that the engineer made a deliberate, reasoned decision rather than a passive non-decision.

The NOC Manager is responsible for reviewing override rates, feedback quality metrics, and escalation decisions at team level on a monthly basis, and for escalating anomalies in these metrics to the Platform Engineering team.
