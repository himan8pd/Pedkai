# Dark Graph and CMDB

**Audience:** NOC engineers and shift leads
**Time to read:** 10 minutes

---

## What is the Dark Graph?

The Dark Graph is pedk.ai's model of your network topology. It is built from two sources:

1. **Your CMDB (Configuration Management Database)** — the declared topology: what equipment exists, where it sits, and what it connects to, as recorded in your configuration management system.
2. **Observed network behaviour** — what pedk.ai can infer from alarm correlation patterns, KPI co-movement, and traffic flows. When two entities consistently degrade together, pedk.ai infers a dependency even if that dependency is not documented in the CMDB.

The "dark" part refers to edges in the graph that are inferred from observation rather than declared in the CMDB. A dark edge is a dependency that exists in practice but has not been recorded — or has not been recorded correctly.

The Dark Graph powers pedk.ai's root cause analysis. When an alarm cluster arrives, pedk.ai traverses the graph to find the most upstream entity that explains the full set of observed degradations. Without accurate topology, root cause attribution goes wrong — a downstream symptom gets misidentified as the cause.

Navigate to `/topology` to explore the Dark Graph visually. Nodes represent network entities (base stations, transport nodes, aggregation switches, core elements). Edges represent dependencies, colour-coded to distinguish CMDB-declared edges from inferred dark edges.

---

## CMDB Divergence — Why CMDBs Drift from Reality

CMDBs are accurate at the moment a change is made. In practice, they drift:

- Field teams make cabling changes, equipment swaps, or temporary re-routes without raising change tickets
- A cell is physically moved or antenna configuration changes, but the CMDB record is not updated
- Vendor upgrades change the logical relationship between baseband units and RRUs without a corresponding CMDB update
- Historical CMDBs contain records for decommissioned equipment that was never removed

The result is a CMDB that partially reflects reality. This matters for pedk.ai because incorrect topology data produces incorrect root cause analysis. If the CMDB says cell A connects to aggregation node X, but in practice it connects to aggregation node Y, pedk.ai will look in the wrong place when A goes down.

The Divergence Report surfaces exactly these discrepancies: places where what the CMDB says and what pedk.ai observes do not agree.

---

## Reading the Divergence Report

Navigate to `/divergence` to access the Divergence Report.

The report lists discrepancies grouped by divergence type:

| Divergence type | What it means |
|----------------|---------------|
| **Missing edge** | pedk.ai has observed a strong dependency between two entities but the CMDB does not record a link between them |
| **Ghost edge** | The CMDB records a link between two entities but pedk.ai never observes correlated behaviour — the link may be stale or for a decommissioned path |
| **Attribute mismatch** | A CMDB attribute (software version, vendor, site ID) does not match what pedk.ai has observed in telemetry metadata |
| **Orphaned entity** | An entity appears in the CMDB but has never produced any telemetry — it may be decommissioned but not removed from the CMDB |

Each divergence record shows:
- **Entity pair** or single entity involved
- **Confidence** — how strongly pedk.ai believes the divergence is real (based on the volume of corroborating observations)
- **First observed** timestamp
- **Evidence summary** — the alarm correlation patterns or KPI co-movement that supports the inferred relationship

High-confidence divergences (0.80+) are worth actioning. Lower-confidence divergences should be noted but are not worth raising change tickets until corroborated by further observation or manual inspection.

---

## Ghost Mask: Maintenance Windows and Suppression

The Ghost Mask is pedk.ai's awareness of planned maintenance. When a network entity is scheduled for maintenance, pedk.ai applies a "ghost mask" to suppress:
- Alarms raised against that entity
- Decay scoring changes for cells served by that entity
- Autonomous action against the entity (at all autonomy levels)

This prevents pedk.ai from raising false incidents during planned work, and prevents autonomous actions that could conflict with what the field team is doing.

Ghost Mask entries are set in `/settings` under the Maintenance Windows section. Each entry specifies:
- The entity ID or group being maintained
- Start and end time (in the configured local timezone)
- The maintenance type (hardware, software, planned outage)

**What you need to know as an NOC engineer:**

- If a sleeping cell flag persists despite a Ghost Mask being active, the mask may have been set for the wrong entity ID or the maintenance window may have expired. Check the mask expiry in `/settings`.
- If pedk.ai is not suppressing alarms during a maintenance window, confirm the entity ID in the Ghost Mask entry matches the entity ID in the topology exactly. String mismatches are a common cause of mask failures.
- Ghost Mask entries do not affect the audit trail — all alarm activity is still logged, just not surfaced as incidents.

---

## How to Action CMDB Corrections

When a divergence is validated, a CMDB correction should be raised. pedk.ai itself does not write to your CMDB — corrections must be actioned through your standard change management process.

**Recommended workflow:**

1. Open the Divergence Report at `/divergence`
2. Click a high-confidence divergence record to open the detail view
3. Review the evidence summary to confirm the divergence is real (not a pedk.ai inference error)
4. If confirmed: raise a change ticket in your ITSM system (ServiceNow) describing the required CMDB correction
5. Reference the pedk.ai divergence report record ID in the change ticket for traceability
6. Once the CMDB is updated, the divergence should clear within the next reconciliation cycle (typically 24 hours)
7. If the divergence persists after CMDB update, report to Engineering — this indicates a reconciliation pipeline issue

**What not to do:**
- Do not action CMDB corrections based on low-confidence divergences (below 0.60) without manual confirmation. The inferred dependency may reflect a transient pattern rather than a permanent topology change.
- Do not dismiss a divergence without investigation if it involves a transport or aggregation node serving multiple cells — a stale edge in this part of the topology will produce systematically wrong root cause analysis.

---

## Why This Matters for Incident Response

Accurate topology data is the foundation of pedk.ai's root cause analysis. When the CMDB is current and the Dark Graph reflects reality:
- Root cause attribution is more accurate
- The alarm clustering correctly groups symptoms with their cause
- Field teams are dispatched to the right location the first time

When CMDB divergence is high:
- pedk.ai's confidence scores will be lower (the system knows its topology is uncertain)
- Root cause analysis may attribute faults to the wrong entity
- You will see more low-confidence SITREPs that require greater manual scrutiny

A well-maintained CMDB is not just a housekeeping task — it directly affects the quality of AI-assisted operations.
