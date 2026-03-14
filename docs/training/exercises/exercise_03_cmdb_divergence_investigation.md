# Exercise 3: CMDB Divergence Investigation

**Duration:** 20 minutes
**Difficulty:** Intermediate
**Learning Objectives:**
- Classify CMDB divergence types from a reconciliation report (dark nodes, phantom nodes, identity mutations, dark attributes)
- Assess the operational risk of each divergence type
- Recommend remediation actions appropriate to each classification

## Scenario

The Pedk.ai platform has completed an overnight reconciliation between the network's CMDB (the authoritative inventory) and the entities discovered through live network polling. The reconciliation covers 47 cells and 12 aggregation nodes across the Yogyakarta cluster.

You are the NOC analyst responsible for triaging the divergence report. Five divergences have been flagged for manual review. Each requires correct classification and a remediation recommendation.

## Data Provided

CMDB reconciliation report extract — Yogyakarta cluster, run at 01:00 WIB:

**Divergence D-001**
- CMDB entry: CELL-X001 (eNB Ericsson RBS6000 at Malioboro tower, active since 2021)
- Live discovery: No response to polling; not visible in SNMP walk; not in neighbour relations of adjacent cells
- Last seen in live data: Never (new CMDB entry added 3 months ago after a planned swap)
- Alarm history: None

**Divergence D-002**
- CMDB entry: CELL-X002 (gNB Nokia AirScale at Prambanan site, commissioned 2023)
- Live discovery: No response; not in S1/NG interface tables; neighbouring cells do not report it in handover statistics
- Last seen in live data: 47 days ago
- Alarm history: Equipment alarm raised 47 days ago, closed by NOC as "duplicate", no field visit

**Divergence D-003**
- CMDB entry: No entry
- Live discovery: CELL-P001 — gNB visible on S1 interface, actively serving UEs (PRB util 22%), appearing in neighbour relations of YKGSLN002-SEC1 and YKGSLN002-SEC2
- Note: No corresponding planned site in rollout tracker

**Divergence D-004**
- CMDB entry: CELL-M001 (eNB, site Kotabaru, Cell ID 0x1A4C, configured band B3)
- Live discovery: Entity with same physical location but Cell ID 0x2B7D, band B1
- Alarm history: None; KPIs appear normal for a B1 cell
- Note: Equipment swap occurred 6 weeks ago; CMDB not updated post-swap

**Divergence D-005**
- CMDB entry: CELL-DA001 (eNB Huawei BTS3900 at Sleman Utara, commissioned 2020)
- Live discovery: Cell visible and active (PRB util 31%); however CMDB shows transmission type "microwave" while live interface shows fibre Ethernet, and CMDB power source is "grid" while site survey notes from last month show "solar+battery"
- Alarm history: None; cell performing normally

## Tasks

1. **Classify each divergence.** For each of D-001 through D-005, assign one of the following types:
   - **Dark node** — CMDB shows a cell that is not present in the live network (never commissioned or decommissioned without update)
   - **Phantom node** — Live network contains an active cell with no CMDB record (unauthorised or unrecorded deployment)
   - **Identity mutation** — Cell exists in both CMDB and live, but key identifiers (Cell ID, band, technology) differ
   - **Dark attribute** — Cell exists in both and identifiers match, but configuration attributes (transport type, power, vendor) differ

2. **Assess operational risk.** For each divergence, state whether the risk is Low, Medium, or High and give a one-sentence justification.

3. **Recommend remediation.** For each divergence, state the appropriate action (e.g., field verification, CMDB update, decommission, escalate to security team).

## Expected Findings

| Divergence | Classification | Risk | Notes |
|-----------|---------------|------|-------|
| D-001 (CELL-X001) | Dark node | Medium | Never appeared in live network after planned swap — likely not commissioned |
| D-002 (CELL-X002) | Dark node | High | Was live, then disappeared 47 days ago; alarm closed incorrectly — possible silent failure |
| D-003 (CELL-P001) | Phantom node | High | Serving live UEs with no CMDB record — may be unauthorised deployment |
| D-004 (CELL-M001) | Identity mutation | Medium | Post-swap CMDB not updated; cell is functional but tracking is unreliable |
| D-005 (CELL-DA001) | Dark attribute | Low | Cell functioning normally; attributes out of date but no safety or performance impact |

Dark nodes: CELL-X001, CELL-X002
Phantom nodes: CELL-P001
Identity mutations: CELL-M001
Dark attributes: CELL-DA001

## Scoring Criteria

| Criterion | Points | Description |
|-----------|--------|-------------|
| D-001 classified as dark node | 12 | Correct type for CELL-X001 |
| D-002 classified as dark node | 12 | Correct type for CELL-X002 |
| D-003 classified as phantom node | 16 | Correct type for CELL-P001 (highest risk, highest weight) |
| D-004 classified as identity mutation | 12 | Correct type for CELL-M001 |
| D-005 classified as dark attribute | 12 | Correct type for CELL-DA001 |
| D-002 and D-003 identified as High risk | 16 | Both high-risk divergences correctly rated |
| Remediation recommendations plausible | 20 | At least 4 of 5 remediations are operationally sensible |

**Total: 100 points**
**Pass mark: 70 points**

## Key Learning Points

- **Dark nodes** require field verification before any CMDB cleanup — a "missing" cell may indicate a silent hardware failure rather than a documentation gap.
- **Phantom nodes** are the highest-risk divergence type: an active cell with no CMDB record cannot be managed, updated, or decommissioned through normal change control processes and may indicate an unauthorised network modification.
- **Dark attributes** are low risk day-to-day but accumulate into a serious operational liability over time — when a site needs emergency maintenance, stale transport or power data can send engineers to the wrong location or with the wrong equipment.
