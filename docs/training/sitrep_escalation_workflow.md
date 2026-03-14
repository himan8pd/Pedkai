# SITREP Escalation Workflow

**Applies to:** NOC Engineers, NOC Managers, Field Teams, Vendor Liaison, Executive On-Call
**System component:** `backend/app/services/sitrep_router.py`
**Last updated:** 2026-03-11

---

## Overview

When the Pedk.ai platform generates a SITREP (Situation Report) from an active incident, the `SitrepRouter` automatically assigns it to the correct team and sets a timer for escalation if the incident is not resolved. This document describes the escalation tiers, timing rules, and domain-specific routing logic that NOC staff must understand before approving or rejecting a routed SITREP.

---

## Escalation Tiers

| Tier | Role | Responsibility |
|------|------|---------------|
| **Tier 1 — NOC Engineer** | `noc_engineer` | First responder. Monitors alarms, performs initial diagnosis via CLI or NOC dashboard, applies known remediation actions within ticket SLA. |
| **Tier 2 — NOC Manager** | `noc_manager` | Escalation lead. Assumes ownership when Tier 1 is unable to resolve within threshold. Authorises non-standard remediation, contacts vendor where needed. |
| **Tier 3a — Field Team** | `field_team` | Dispatched for physical site investigation: hardware reseating, fibre inspection, power cycling inaccessible equipment. |
| **Tier 3b — Vendor Support** | `vendor_support` | Engaged when a specific equipment fault is suspected and under warranty or SLA. Raised as a vendor ticket with the relevant TAC. |
| **Tier 4 — Executive** | `executive` | Major outage affecting SLA contractual obligations or regulatory reporting thresholds. Executive on-call is paged; PR / regulatory comms may be triggered. |

---

## Timing Rules by Domain and Severity

The table below shows the initial tier assignment and the escalation threshold. If an incident is not resolved within the threshold, the system flags it for re-routing to the next tier.

| Domain | Severity | Initial Tier | Escalate After (min) | Escalate To | Field Required |
|--------|----------|-------------|----------------------|-------------|---------------|
| RAN | Critical | NOC Engineer | 15 | NOC Manager | No |
| RAN | High | NOC Engineer | 30 | NOC Manager | No |
| RAN | Medium | NOC Engineer | 60 | Field Team | No |
| Core | Critical | NOC Manager | 10 | Executive | No |
| Core | High | NOC Engineer | 20 | NOC Manager | No |
| Transport | Critical | NOC Engineer | 15 | Field Team | **Yes** |
| Transport | High | NOC Engineer | 30 | Field Team | **Yes** |
| Any | Low | NOC Engineer | 120 | NOC Engineer | No |

---

## Domain-Specific Routing Notes

**RAN (Radio Access Network)**
Critical and High RAN faults typically originate from baseband failures, interference events, or feeder issues diagnosable remotely. Escalation to NOC Manager is triggered early because RAN faults directly degrade subscriber experience and affect SLA KPIs.

**Core Network**
Core faults carry the highest blast radius. A Critical Core incident bypasses Tier 1 and is immediately owned by the NOC Manager, with a very short 10-minute window before Executive escalation. This reflects the commercial and regulatory sensitivity of core outages.

**Transport**
Transport faults often require physical inspection of microwave, fibre, or aggregation nodes. The `requires_field` flag is set to `True` for all Transport rules at High severity and above, meaning a field dispatch ticket should be pre-raised in parallel with remote diagnosis.

**Low severity / wildcard**
Low severity incidents across any domain are handled solely by the NOC Engineer for up to two hours before any re-assessment. No automatic tier progression occurs; the incident simply remains assigned to Tier 1 until resolved or manually escalated.

---

## Kill-Switch Procedure

If automated routing produces an incorrect assignment (for example, a false-positive Critical triggered by a monitoring misconfiguration), the NOC Manager can invoke the kill-switch:

1. Open the incident in the Pedk.ai NOC dashboard.
2. Select **Override Routing** from the incident action menu.
3. Set the severity to the correct value and confirm. The router will re-evaluate using the corrected input.
4. Add a mandatory free-text note explaining the override reason. This is logged in the audit trail under `audit_orm` for compliance review.
5. Notify the on-call NOC Manager via Slack channel `#noc-overrides` so the shift handover log is accurate.

---

## Cross-Shift Handover Procedure

At each shift boundary (typically 08:00, 16:00, 00:00 local time):

1. The outgoing shift lead exports the open SITREP list from the **Reports** page (CSV or PDF).
2. For each open incident with elapsed time more than 50% of its escalation threshold, the outgoing engineer adds a brief status note directly in the incident ticket.
3. The incoming shift lead acknowledges receipt in the `#noc-handover` Slack channel by reacting with the designated emoji or typing `/noc ack-handover <shift-id>`.
4. Any incident already flagged `requires_field=True` that has not yet had a field dispatch ticket created must be raised immediately at the start of the incoming shift. Do not carry over an unactioned field flag.
5. Incidents at Executive tier must be verbally handed over between NOC Managers; a Slack message alone is insufficient.
