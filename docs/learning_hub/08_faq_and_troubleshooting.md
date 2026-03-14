# FAQ and Troubleshooting

**Audience:** NOC engineers and shift leads
**Time to read:** As needed — use as a reference guide

---

## Common Questions from NOC Engineers

**Q: pedk.ai is showing me a SITREP — do I have to follow its recommendation?**

No. pedk.ai is advisory. Every SITREP is a recommendation, not an instruction. You assess it, decide whether it is correct, and act accordingly. If the recommendation is wrong, override it, add a reason code, and proceed with your own analysis. The override is the right action and it improves the system.

**Q: What does a confidence score of 0.82 actually mean?**

It means pedk.ai has found strong historical precedent for this pattern and at least one expert causal template matches. The number is derived from Decision Memory similarity search and expert rule matching — not from the language model's own assessment of its certainty. Scores of 0.75 and above are generally reliable, but "reliable" does not mean certain. Cross-check high-confidence SITREPs when you have specific contextual knowledge that the AI might not have (recent maintenance, vendor upgrades, equipment anomalies you have observed).

**Q: Can pedk.ai actually change my network?**

At Level 0 (Advisory), Level 1 (Assisted), and Level 2 (Supervised without approved autonomous scope), pedk.ai has read-only access to your network. It cannot change configuration, restart equipment, or modify any network element. At Level 3 (Gated Autonomous), pre-approved routine actions can execute automatically — but only after all seven safety gates pass and within the operator-defined allowlist. Check with your NOC Manager which level your deployment is at.

**Q: How often should I be overriding recommendations?**

A healthy override rate is 10–30% of SITREPs reviewed. Below 10% often indicates the team is accepting recommendations without genuine review (rubber-stamping). Above 30% may indicate that pedk.ai is not well-calibrated for your network, or that the team's thresholds for acceptance are set too conservatively. If your team's rate falls outside this range, raise it with your NOC Manager.

**Q: Why does pedk.ai sometimes flag a fault 30 minutes after I already knew about it?**

SITREP generation time depends on alarm ingestion latency, correlation processing time, and Decision Memory search. Most SITREPs are generated within 2–5 minutes of alarm receipt. Longer delays can indicate telemetry pipeline issues (check the backend health indicator in the dashboard header) or very complex clustering that requires more correlation passes. If you consistently see delays >10 minutes, report this to Engineering.

**Q: What happens if I forget to provide feedback on a SITREP?**

Nothing breaks, but the system does not improve for that pattern type. Feedback is what updates the calibration bins. An unrated SITREP is a missed learning opportunity. The team's feedback completion rate is tracked — aim for >70%.

---

## Troubleshooting: "Why did pedk.ai miss this alarm?"

**Scenario:** You discovered a fault — a sleeping cell, a degraded cell, or a service impact — that pedk.ai did not flag or flagged very late.

**Step 1 — Check the alarm ingestion pipeline**
Navigate to `/settings` and check the Ingestion Status panel. Confirm the last successful data ingestion timestamp. If the pipeline is behind by more than a few minutes, telemetry may not have reached pedk.ai in time.

**Step 2 — Check the alarm's entity in the topology**
Navigate to `/topology` and search for the affected entity. If it appears as an orphaned node or has no edges in the Dark Graph, pedk.ai may not have had the topology context to correlate the alarm correctly.

**Step 3 — Check the decay score threshold**
For sleeping cells specifically, the monitoring threshold may be set above the level at which this cell's degradation would appear. Navigate to `/sleeping-cells` and temporarily lower the display threshold to see if the cell was present but below the configured alarm level.

**Step 4 — Check for Ghost Mask suppression**
If a maintenance window was active for this entity, alarms would have been suppressed. Check `/settings` for active or recently expired maintenance windows covering the entity.

**Step 5 — Report as a missed detection**
If none of the above explains the miss, this is a genuine detection gap. File a report via the Feedback panel with reason code "Missed detection" and include the entity ID, the fault timestamp, and what you observed. Engineering uses these reports to adjust detection thresholds and investigate pipeline gaps.

---

## Troubleshooting: "Why is a cell flagged SLEEPING when it seems fine?"

**Scenario:** A cell has a high decay score in `/sleeping-cells` but you believe it is operating normally.

**Step 1 — Validate against current OSS data**
Open the cell in your OSS tool (ENM, NetAct). Confirm it is actively scheduling users and that throughput and connection metrics are within normal range. If they are, this is a likely false positive.

**Step 2 — Check the KPI trend**
In the sleeping cell detail view, examine the KPI trend charts. If the degradation was real but has since recovered, the decay score may not have reset yet. Scores decay gradually — a cell that recovered an hour ago may still show an elevated score that will normalise over the next few sampling cycles.

**Step 3 — Check for a completed maintenance window**
If a maintenance window recently ended and the cell's KPIs dipped during the window, the decay score may have risen during the maintenance period. Check `/settings` for recently expired maintenance windows.

**Step 4 — Dismiss with reason code**
If the cell is confirmed to be operating normally and the flag is a false positive, use the **Dismiss** button and select "False positive — verified normal operation". This feeds back to the threshold calibration and reduces the likelihood of the same false positive recurring.

**Step 5 — If false positives are persistent**
If a specific cell or cell type is consistently generating false positives, the detection threshold for your network may need adjustment. Report to Engineering with the cell IDs, timestamps, and the OSS-verified KPI values. Do not raise change tickets for cells that are confirmed normal.

---

## Troubleshooting: "Why was my autonomous action blocked?"

**Scenario:** An action you expected pedk.ai to execute automatically did not proceed.

**Step 1 — Check the gate evaluation summary**
Open the incident in `/incidents` and navigate to the Autonomous Action section. The gate evaluation record shows each of the 7 gates, whether it passed or failed, and the value that was evaluated.

**Step 2 — Identify the blocking gate**

- **Gate 1 (Blast Radius):** Action affected more than 10 entities. Split the action into smaller steps.
- **Gate 2 (Policy Rules):** Action type not on the approved allowlist. Contact Engineering to review policy configuration.
- **Gate 3 (Confidence):** Score below 85%. Review the SITREP evidence and decide whether to approve manually.
- **Gate 4 (Maintenance Window):** Ghost Mask is active. Check `/settings` for the maintenance window details.
- **Gate 5 (Duplicate Suppression):** A similar action was executed in the last hour. Check whether the earlier action resolved the issue.
- **Gate 6 (Human Gate):** Action requires explicit approval. Use the **Approve Action** button if you have reviewed the action and it is appropriate.
- **Gate 7 (Rate Limit):** Too many autonomous actions this hour. Wait for the rate window to reset or take manual action.

**Step 3 — Take manual action if needed**
A blocked action is not an error — it is a safety gate working as designed. If the action was valid, take it manually. The audit trail records both the blocked autonomous attempt and your manual action.

---

## How to Contact Support / Escalate Technical Issues

**For platform technical issues** (pipeline errors, data ingestion failures, API errors):
- Check the backend health indicator in the dashboard header first
- Review recent platform activity in `/settings` under System Status
- Contact: engineering@pedk.ai with the `trace_id` of any affected incident, the timestamp, and a description of the observed issue

**For calibration issues** (persistent false positives, missed detections, confidence scores that seem wrong):
- File feedback via the Feedback panel with specific reason codes
- For patterns affecting multiple incidents, raise with your NOC Manager who can escalate to Engineering through the platform support channel

**For access and permissions issues** (cannot access a page, RBAC scope error):
- Contact your NOC Manager — RBAC scope is managed at the operator level

**Regulatory or compliance questions:**
- Contact your organisation's regulatory affairs team
- Pedk.ai Ltd regulatory contact: regulatory@pedk.ai

---

## Glossary

| Term | Definition |
|------|-----------|
| **Abeyance** | pedk.ai's Decision Memory system — holds past decisions in active memory, with decay, pending corroboration or contradiction. The technical name for the component referred to as Decision Memory throughout operator documentation. |
| **Dark Graph** | pedk.ai's network topology model, combining CMDB-declared edges with edges inferred from observed alarm correlation and KPI co-movement. Dark edges are inferred; light edges are declared. |
| **CMDB** | Configuration Management Database — the source of record for network equipment, logical relationships, and topology. CMDBs drift from reality over time as field changes are not captured. |
| **Decay score** | A measure of how strongly pedk.ai's Decision Memory weighting supports a past decision, or how severe a sleeping cell condition is. Starts high and decreases unless corroborated by new confirming evidence. |
| **Ghost Mask** | pedk.ai's awareness of planned maintenance windows. Entities under a Ghost Mask have alarm suppression and autonomous action suppression active. |
| **SITREP** | Situation Report — pedk.ai's structured analysis of an incident cluster, including root cause entity, confidence score, affected entities, subscriber impact estimate, and recommended action. |
| **Corroboration** | The accumulation of independent evidence sources (Decision Memory, causal templates, KPI patterns, topology context) supporting a single conclusion. More corroboration means higher confidence. |
| **Blast radius** | The number of network entities that would be affected by a proposed autonomous action. Actions affecting more than 10 entities are unconditionally blocked by Gate 1. |
| **Cold storage** | The archive tier of Decision Memory. Fragments whose decay score has dropped below the dormancy threshold are moved here. Cold storage is retrievable when a new incident matches a dormant pattern. |
| **Human gate** | A mandatory operator approval checkpoint in the incident lifecycle. Three human gates exist: SITREP approval (Gate 1), action approval (Gate 2), and incident close (Gate 3). None can be bypassed by configuration. |
| **Override** | The operator decision to reject a pedk.ai recommendation and proceed with a different course of action. Overrides must be documented with a reason code. They are the highest-quality learning signal available to the system. |
| **Trace ID** | A unique correlation identifier attached to every event in the audit trail. Enables full reconstruction of the complete decision chain for any incident, from initial telemetry anomaly to final resolution. |
| **is_emergency_service** | A flag on network entities identifying 999/112 infrastructure and other safety-critical services. Entities with this flag are subject to mandatory P1 escalation and the Human Gate at all autonomy levels. Cannot be overridden. |
