# NOC Operational Runbook

**Version**: 1.0 | **Audience**: NOC Engineers, Shift Leads, NOC Managers

---

## 1. Pedkai-Assisted Alarm Triage Workflow

Pedkai is a **decision-support tool**. It does not take autonomous action. Engineers remain in control at every step.

### Step-by-Step Triage Process

```
1. Alarm received by OSS (Ericsson ENM / Nokia NetAct)
   ↓
2. Alarm normalised by Pedkai alarm_normalizer.py
   ↓
3. Pedkai correlates alarms into clusters (temporal + topology proximity)
   ↓
4. NOC Dashboard displays: cluster summary, noise reduction %, root cause entity
   ↓
5. Engineer reviews cluster — reads AI reasoning chain
   ↓
6. Engineer decides:
   a. Accept Pedkai recommendation → create incident, advance lifecycle
   b. Override Pedkai → log override reason, proceed with manual triage
   c. Dismiss → mark as false positive, provide feedback (thumbs down)
   ↓
7. Incident created in Pedkai with status: ANOMALY
   ↓
8. AI generates SITREP draft → Engineer reviews → Human Gate 1 (approve-sitrep)
   ↓
9. Resolution action recommended → Engineer reviews → Human Gate 2 (approve-action)
   ↓
10. Resolution executed by engineer → Incident resolved
    ↓
11. NOC Manager closes incident → Human Gate 3 (close)
    ↓
12. Pedkai captures learning → Decision Memory updated
```

> **Key Principle**: Pedkai never executes network changes. Steps 6, 8, 9, and 11 are mandatory human decisions.

---

## 2. Incident Lifecycle with Human Gates

### Lifecycle Stages

| Stage | Description | Who Acts |
|:------|:------------|:---------|
| `anomaly` | KPI deviation detected | System |
| `detected` | Alarm correlated and classified | System |
| `rca` | Root cause analysis complete | System (AI) |
| `sitrep_draft` | Situation report drafted by AI | System (AI) |
| **`sitrep_approved`** | **🔒 Human Gate 1** | Shift Lead |
| `resolving` | Resolution in progress | Engineer |
| **`resolution_approved`** | **🔒 Human Gate 2** | Engineer |
| `resolved` | Service restored | System |
| **`closed`** | **🔒 Human Gate 3** | NOC Manager |
| `learning` | Post-incident review | System |

### Gate Responsibilities

**Human Gate 1 — Sitrep Approval** (`incident:approve_sitrep` scope required)
- Shift Lead reviews AI-generated situation report
- Confirms: root cause assessment is accurate, severity is correct
- Approves or requests revision

**Human Gate 2 — Action Approval** (`incident:approve_action` scope required)
- Engineer reviews proposed resolution steps
- Confirms: action is safe, rollback plan is understood
- Approves before executing any network change

**Human Gate 3 — Close** (`incident:close` scope required)
- NOC Manager confirms: service fully restored, no residual risk
- Triggers post-incident learning capture

---

## 3. Escalation Matrix

| Severity | Priority | Who is Notified | Response SLA | Escalation if Unresolved |
|:---------|:---------|:----------------|:-------------|:------------------------|
| `critical` | P1 | NOC Manager + On-call Engineer + Shift Lead | **15 minutes** | CTO after 30 min |
| `major` | P2 | Shift Lead + Engineer | **1 hour** | NOC Manager after 2 hours |
| `minor` | P3 | Engineer | **4 hours** | Shift Lead after 8 hours |
| `warning` | P4 | Engineer (next available) | **Next business day** | Shift Lead if SLA at risk |

### Emergency Service Override (H&S §2.13)
Any incident affecting an entity of type `EMERGENCY_SERVICE` (999/112 call routing, emergency broadcast) is **automatically escalated to P1 regardless of detected severity**. This override cannot be disabled.

---

## 4. Degraded-Mode Procedures

Use these procedures when the Pedkai backend is unavailable.

### 4.1 Detecting Pedkai Unavailability
- Health check: `GET /health/ready` returns non-200, or
- NOC Dashboard shows "Backend Unavailable" banner

### 4.2 Manual Alarm Triage (Pedkai Down)
1. Continue using existing OSS tools (ENM / NetAct) directly
2. Use standard NOC runbook for manual alarm triage
3. **Do not wait for Pedkai** — existing processes are the fallback
4. Log all decisions in the existing ticketing system (ServiceNow / Jira)

### 4.3 Incident Tracking Without Pedkai
- Use existing ITSM tool for incident lifecycle management
- Pedkai is NOT required for incident tracking — it is an enhancement
- All human gate decisions can be recorded in the ITSM tool

### 4.4 Restoring Pedkai Service
1. Check backend logs: `journalctl -u pedkai-backend -n 100`
2. Check database connectivity: `GET /health/live`
3. Restart if needed: `systemctl restart pedkai-backend`
4. Verify: `GET /health/ready` returns 200

### 4.5 Post-Degraded-Mode Sync
After Pedkai is restored:
1. Review alarms that occurred during downtime in OSS
2. Manually create incidents in Pedkai for any P1/P2 events
3. Attach post-incident notes to maintain audit trail continuity
