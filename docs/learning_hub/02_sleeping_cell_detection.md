# Sleeping Cell Detection

**Audience:** NOC engineers and shift leads
**Time to read:** 10 minutes

---

## What is a Sleeping Cell?

A sleeping cell is a base station (or sector) that appears operational — it is attached, registered, and showing green in your OSS — but is delivering severely degraded service or carrying near-zero traffic. Because the cell has not raised an alarm, it is invisible to traditional alarm-driven NOC workflows. Subscribers in coverage are silently affected.

The name comes from the behaviour: the cell looks awake, but is not working.

Sleeping cells commonly arise from:
- Software faults or configuration corruption that does not trigger alarm thresholds
- Radio frequency issues (interference, feeder degradation) below hardware alarm limits
- Scheduler or resource manager hang states affecting throughput without stopping cell registration
- Handover parameter misconfiguration causing traffic to avoid the cell

In a network of thousands of cells, sleeping cells can persist undetected for hours or days without a system like pedk.ai actively monitoring KPI patterns.

---

## How pedk.ai Detects Sleeping Cells

pedk.ai's Sleeping Cell Monitor analyses KPI time-series data for each cell, looking for degradation patterns that diverge from:
- The cell's own historical baseline
- The performance of neighbouring cells in the same cluster
- Expected traffic patterns for the time of day and day of week

Key metrics used in detection:

| Metric | What it measures | Sleeping cell signal |
|--------|-----------------|----------------------|
| `PR_RRC_ConnEstabSucc_Sum` | RRC connection establishment successes | Drop while attempts remain high |
| `throughput_mbps` | Downlink/uplink throughput | Sustained low value without corresponding alarm |
| `rsrp_avg` | Average Reference Signal Received Power | Significant degradation vs neighbours |
| `prb_utilisation` | Physical Resource Block utilisation | Near-zero despite attached UEs |
| `handover_success_rate` | Handover success ratio | Abnormal spike — traffic fleeing the cell |

The system assigns each suspect cell a **decay score** — a value from 0.0 to 1.0 reflecting the probability and severity of a sleeping condition. A higher score means the KPI pattern more closely matches the signature of a sleeping cell, with greater confidence based on the depth of the historical baseline.

Decay score thresholds:

| Score | Interpretation |
|-------|---------------|
| 0.0 – 0.39 | Within normal variation — no action needed |
| 0.40 – 0.69 | Worth monitoring — review if persists across the next sampling window |
| 0.70 – 0.84 | Probable sleeping condition — validate and raise incident if confirmed |
| 0.85 – 1.00 | High-confidence sleeping cell — immediate investigation required |

---

## Reading the Sleeping Cells Page

Navigate to `/sleeping-cells` to access the Sleeping Cell Monitor.

The page shows a list of cells currently flagged above your site's monitoring threshold, sorted by decay score descending. For each cell you will see:

- **Cell ID and site name**
- **Current decay score** with trend indicator (rising, stable, falling)
- **Time since first flag** — how long the cell has been in a degraded state
- **Key KPI summary** — the specific metrics that triggered the flag
- **Ghost Mask status** — whether the cell is currently in a scheduled maintenance window (see doc 03 for Ghost Mask details)
- **Last alarm timestamp** — when the cell last generated any alarm (a long gap here is itself a signal)

Use the **Filter** controls to scope the view by:
- Site, region, or vendor
- Score threshold
- Flag duration (cells flagged for more than N hours)
- Ghost Mask state (exclude maintenance windows from investigation list)

Click any cell to open the detail view, which shows the full KPI trend charts and the evidence that contributed to the decay score.

---

## How to Validate a Suspected Sleeping Cell

When pedk.ai flags a cell with a high decay score, do not raise an incident immediately. Work through this validation sequence first:

**Step 1 — Check for recent maintenance activity**
Cross-reference the cell's flag timestamp against:
- Active or recently completed maintenance windows in `/settings` or your ITSM change management system
- Field team reports or change tickets for the site
- Vendor upgrade schedules for the cell's equipment type

A KPI dip that coincides exactly with a maintenance window is probably not a sleeping cell.

**Step 2 — Check neighbour cells**
If neighbouring cells on the same site or sector are also showing degradation, the cause may be a shared upstream fault (transport, power, or backhaul) rather than a cell-specific sleeping condition. Navigate to `/topology` to visualise the physical and logical relationships.

**Step 3 — Cross-reference alarms**
Open `/incidents` and check for any alarm activity on the cell or its upstream equipment in the last 48 hours. A transport alarm that cleared an hour ago may explain the KPI pattern.

**Step 4 — Review raw OSS data**
Access the cell directly in your OSS tool (Ericsson ENM, Nokia NetAct, or equivalent). Confirm whether the cell is actively scheduling users. A cell with attached UEs but zero scheduled PRBs is exhibiting clear sleeping behaviour.

**Step 5 — Confirm or dismiss**
- If validated: open an incident in pedk.ai. Assign severity based on the subscriber impact estimate shown in the decay detail view.
- If dismissed (maintenance or false positive): use the **Dismiss** button and select a reason code. This feeds back to the model's threshold calibration.

---

## Escalation Steps When pedk.ai Flags SLEEPING Status

Once a sleeping cell is confirmed and an incident is raised, follow the standard escalation workflow:

1. **Severity assignment**: Use the subscriber count and revenue-at-risk estimates from the SITREP as inputs. A cell covering a dense urban area with thousands of affected subscribers warrants higher severity than a rural macro with low traffic.

2. **NOC Tier 1 response**: Attempt remote remediation — cell restart, parameter reset, or software rollback — if the fault type supports it and you have the authorisation scope to act.

3. **SITREP approval**: The shift lead reviews and approves the AI-generated SITREP (Human Gate 1) before any field dispatch or vendor escalation.

4. **Field dispatch**: If remote remediation fails or is not applicable, raise a field ticket. Transport-domain sleeping cells often require physical inspection — fibre, feeder, or power issues that cannot be resolved remotely.

5. **Vendor escalation**: If the fault pattern points to a software defect in the baseband unit or RRU, engage the vendor TAC with the KPI evidence from the decay detail view.

6. **Close and feedback**: When the cell returns to normal KPI levels, close the incident and complete the resolution coding. Record whether the root cause matched pedk.ai's initial assessment — this is high-value training signal.

---

## Threshold Calibration

The decay score threshold that triggers dashboard escalation is configurable in `/settings`. The default is 0.70.

If you are seeing too many false positives — cells flagged as sleeping that are actually fine — the threshold may need to be raised for your specific network characteristics. Raise this concern with your platform Engineering team rather than adjusting it yourself, as the threshold affects all operators on the tenant.

Conversely, if you are finding sleeping cells that pedk.ai missed (discovered through customer complaints or routine drive tests), this is important feedback — contact Engineering with the cell IDs and timestamps so the detection model can be reviewed.
