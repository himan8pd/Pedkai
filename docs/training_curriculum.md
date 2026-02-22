# NOC Training Curriculum — Pedkai Autonomous Network Operations

**Version**: 1.0 | **Audience**: NOC Engineers, Shift Leads, NOC Managers  
**Mandatory completion**: Before accessing Pedkai in advisory mode  
**Total duration**: ~6 hours (4 modules)

---

## Module 1: Reading Pedkai Reasoning Chains
**Duration**: 2 hours | **Audience**: All NOC staff

### Learning Objectives
- Interpret AI confidence scores and what they mean for decision-making
- Understand when Pedkai's analysis is reliable vs when to apply scepticism
- Recognise the `[LOW CONFIDENCE — TEMPLATE FALLBACK]` prefix and its implications

### Content

**1.1 Anatomy of a Reasoning Chain**
Each Pedkai SITREP contains a reasoning chain with:
- `step`: Sequential analysis step (1 = alarm grouping, 2 = topology traversal, etc.)
- `confidence`: Score 0.0–1.0 (cap of 0.95 — Pedkai never claims certainty)
- `source`: Which engine produced the reasoning (`alarm_correlation:temporal_engine`, `causal_graph`, `decision_memory`)
- `evidence_count`: Number of data points supporting this step

**1.2 Confidence Score Interpretation**

| Score | Meaning | Recommended Action |
|-------|---------|-------------------|
| 0.75 – 0.95 | High: strong evidence from data + memory | Review and likely approve |
| 0.50 – 0.74 | Medium: plausible but limited evidence | Review carefully, check raw alarms |
| 0.30 – 0.49 | Low: minimal evidence, template fallback used | Treat as a starting point only |
| < 0.30 | Very low: insufficient data | Disregard AI recommendation, triage manually |

**1.3 The `[LOW CONFIDENCE — TEMPLATE FALLBACK]` Prefix**
When the confidence score falls below `0.5`, the SITREP text is replaced by a generic template:
```
[LOW CONFIDENCE — TEMPLATE FALLBACK]
Anomaly detected on entity {entity_id}. Insufficient historical data for AI analysis.
Manual investigation recommended.
```
This is intentional — Pedkai does not fabricate analysis. When you see this prefix, treat it as a cue to perform manual triage.

**1.4 When to Override AI Recommendations**
Always override if:
- The AI has misidentified the root cause entity
- The recommended action would cause a service impact not accounted for in the reasoning
- You have direct NOC knowledge contradicting the AI analysis

When overriding, **always log your reason** via the "Override" button — this feedback improves future recommendations.

### Assessment
Complete the 15-question confidence score quiz on the training portal. Pass mark: 80%.

---

## Module 2: Operating Human Gates
**Duration**: 1 hour | **Audience**: Shift Leads and above

### Learning Objectives
- Understand the 3 mandatory human gates and the RBAC scope required for each
- Know how to approve and reject at each gate
- Understand the consequences of rejection and what happens next

### Content

**2.1 The Three Gates**

| Gate | Stage | Who Can Approve | Scope Required |
|------|-------|-----------------|----------------|
| Gate 1 — Sitrep Approval | `sitrep_draft → sitrep_approved` | Shift Lead | `incident:approve_sitrep` |
| Gate 2 — Action Approval | `resolving → resolution_approved` | Engineer | `incident:approve_action` |
| Gate 3 — Close | `resolved → closed` | NOC Manager | `incident:close` |

**2.2 What to Check at Each Gate**

*Gate 1 — Sitrep Review*:
- Does the executive summary accurately describe the alarm cluster?
- Is the root cause entity correctly identified?
- Is the severity appropriate?
- Is the `🤖 AI Generated — Advisory Only` watermark visible? (Always should be)

*Gate 2 — Action Review*:
- Is the proposed action safe?
- Is a rollback plan understood?
- Has the engineer confirmed this action won't impact adjacent services?

*Gate 3 — Close Review*:
- Has the alarm cleared in OSS (ENM/NetAct)?
- Are there any residual risks?
- Is the post-incident review complete?

**2.3 Rejecting at a Gate**
Rejection returns the incident to the previous stage. The AI does NOT automatically retry. The rejecting operator must:
1. Document the rejection reason in the incident notes
2. Either provide a corrected SITREP manually, or request a new AI analysis

### Assessment
Practical exercise on the training environment: approve and reject an incident through all 3 gates.

---

## Module 3: Providing Feedback to Improve AI
**Duration**: 1 hour | **Audience**: All NOC staff

### Learning Objectives
- Know how to flag incorrect correlations (thumbs down)
- Know how to mark false positives
- Understand how feedback enters the RLHF loop

### Content

**3.1 Types of Feedback**
- **Thumbs down on correlation**: "These alarms should NOT have been grouped together"
- **False positive flag**: "This alarm cluster was noise — no real incident"
- **Root cause correction**: "The root cause was X, not Y" (entered in incident notes)

**3.2 How to Submit Feedback**
1. Open the incident in the Pedkai dashboard
2. Use the feedback controls in the SITREP panel
3. Select the feedback type and add a brief note
4. Submit — the feedback is stored in the Decision Memory system

**3.3 How Feedback Improves the AI**
Your feedback:
- Reduces the similarity score for incorrect correlations in future cases
- Adds negative examples to the decision memory used for confidence scoring
- Is aggregated by Engineering to calibrate the drift detection threshold

> [!NOTE]
> No feedback is used to change AI behaviour in real time. Changes are reviewed by Engineering and applied in scheduled updates.

**3.4 What NOT to Do**
- Do not submit false positive feedback for incidents you were not sure about
- Do not use feedback to "game" metrics
- All feedback is logged with your user ID for audit purposes

---

## Module 4: Degraded-Mode Operations
**Duration**: 2 hours | **Audience**: All NOC staff

### Learning Objectives
- Operate the NOC effectively without Pedkai available
- Follow the degraded-mode triage process
- Know when and how to escalate during degraded mode

### Content

**4.1 Detecting Degraded Mode**
- Pedkai dashboard shows "Backend Unavailable" banner, OR
- `GET /health/ready` returns non-200, OR
- Alarm feed stops updating for > 5 minutes

**4.2 Manual Alarm Triage (Pedkai Down)**
Refer to the full procedure in Section 4 of this runbook (`docs/noc_runbook.md`).

Key principle: **Pedkai is an enhancement, not a dependency.** All existing OSS tools (ENM, NetAct) remain available and are the authoritative source of truth.

**4.3 Escalation Contacts During Degraded Mode**

| Scenario | Contact | Method |
|----------|---------|--------|
| Pedkai backend down | Platform Engineering on-call | PagerDuty |
| Database unavailable | DBA on-call | PagerDuty |
| P1 incident during downtime | NOC Manager | Phone (always) |
| Extended downtime > 1 hour | CTO | Phone |

**4.4 Restoring Pedkai**
1. `GET /health/live` — confirms process is running
2. `GET /health/ready` — confirms DB and Kafka connections
3. If down: `systemctl restart pedkai-backend`
4. Notify NOC team when service is restored
5. Review missed alarms in OSS and create manual incidents for P1/P2 events

### Assessment
Tabletop exercise: Simulate a Pedkai outage scenario. Groups of 3 must triage 5 alarm events without Pedkai. Debrief with NOC Manager.
