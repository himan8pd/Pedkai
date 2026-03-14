# Exercise 1: Sleeping Cell Identification

**Duration:** 20 minutes
**Difficulty:** Beginner
**Learning Objectives:**
- Recognise the KPI signature of a sleeping cell (near-zero PRB utilisation with no corresponding alarm)
- Distinguish sleeping cells from normally lightly-loaded cells using SINR and handover trends
- Formulate a hypothesis for escalation to field engineering

## Scenario

It is 02:15 WIB on a Tuesday. The NOC receives an automated nightly summary for the Jakarta-Bandung corridor. Site reliability baseline shows average PRB utilisation of 38 % across the corridor with normal traffic patterns. You are asked to review KPI exports for five cells and flag any that appear to be in a sleeping state.

The five cells under review are:

| Cell ID | Site | Sector |
|---------|------|--------|
| JKTBND001-SEC1 | Jatinegara interchange | Sector 1 (North) |
| JKTBND001-SEC2 | Jatinegara interchange | Sector 2 (South) |
| JKTBND002-SEC1 | Bekasi Barat overpass | Sector 1 |
| BDGDGO003-SEC1 | Dago highland | Sector 1 (East) |
| BDGDGO003-SEC2 | Dago highland | Sector 2 (West) |

## Data Provided

You have access to 72-hour KPI snapshots (15-minute granularity) exported from the Pedk.ai platform for each cell. The relevant KPIs are:

- **PRB Utilisation (%)** — proportion of Physical Resource Blocks scheduled during the interval
- **SINR (dB)** — signal-to-interference-plus-noise ratio averaged across connected UEs
- **Handover Success Rate (%)** — ratio of successful outgoing handovers to attempted
- **Active UE Count** — average number of UEs attached during the interval
- **Alarm count** — number of active alarms in the same window

KPI summary (72-hour mean ± standard deviation):

| Cell ID | PRB Util (%) | SINR (dB) | HO Success (%) | Active UEs | Alarms |
|---------|-------------|-----------|----------------|------------|--------|
| JKTBND001-SEC1 | 1.2 ± 0.4 | 4.1 ± 3.8 | 71 ± 9 | 0–2 | 0 |
| JKTBND001-SEC2 | 35.4 ± 7.2 | 14.2 ± 2.1 | 96 ± 1 | 18–42 | 0 |
| JKTBND002-SEC1 | 29.1 ± 8.4 | 12.8 ± 1.9 | 94 ± 2 | 14–38 | 1 |
| BDGDGO003-SEC1 | 18.3 ± 5.1 | 11.4 ± 2.4 | 91 ± 3 | 9–22 | 0 |
| BDGDGO003-SEC2 | 2.8 ± 1.1 | 3.3 ± 4.2 | 67 ± 14 | 0–3 | 0 |

Note: cells with zero alarms and very low PRB utilisation are the primary candidates. Alarm suppression or silent failure is a key characteristic of sleeping cells.

## Tasks

1. **Identify the sleeping cells.** Using the KPI table above, determine which cell IDs are exhibiting sleeping-cell behaviour. List each cell ID and cite the specific KPI values that support your conclusion.

2. **Rule out normal low-load conditions.** For each candidate cell, explain why the KPI pattern cannot simply be explained by low traffic demand (e.g., overnight quiet period on a rural site). Reference the SINR degradation and handover success rate as part of your reasoning.

3. **Prioritise for field investigation.** Rank the two sleeping cells by urgency and state which should be dispatched first. Consider that JKTBND001-SEC1 covers a motorway on-ramp used by inter-city coaches, while BDGDGO003-SEC2 serves a university residential block.

## Expected Findings

Trainees should identify **JKTBND001-SEC1** and **BDGDGO003-SEC2** as sleeping cells based on:
- PRB utilisation below 5 % across the full 72-hour window (including peak commute hours 07:00–09:00 and 17:00–19:00 WIB)
- SINR degraded below 6 dB, indicating the cell is transmitting with distorted pilot signals rather than simply being idle
- Handover success rate below 80 %, indicating UEs that do connect are failing to hand off cleanly — a symptom of a misconfigured or partially initialised cell
- Zero active alarms despite abnormal KPI state — the cell has not self-reported a fault

JKTBND001-SEC1 should be flagged as higher urgency due to safety-critical motorway coverage.

## Scoring Criteria

| Criterion | Points | Description |
|-----------|--------|-------------|
| Correct sleeping cell identification | 40 | Both JKTBND001-SEC1 and BDGDGO003-SEC2 identified (20 pts each) |
| PRB evidence cited | 20 | Trainee references sub-5% PRB utilisation for both cells |
| SINR degradation cited | 15 | Trainee references SINR below threshold (< 6 dB) |
| Handover success rate cited | 15 | Trainee references HO success below 80% |
| Prioritisation correct | 10 | JKTBND001-SEC1 ranked first with plausible safety justification |

**Total: 100 points**
**Pass mark: 70 points**

## Key Learning Points

- A sleeping cell presents as anomalously low PRB utilisation *without a corresponding alarm*. The absence of an alarm is itself a signal.
- SINR degradation distinguishes a sleeping cell from a legitimately quiet cell: a quiet cell has good SINR (it is simply not loaded); a sleeping cell has degraded SINR because the scheduler or radio unit is malfunctioning.
- Prioritisation of sleeping cells should account for the criticality of coverage — safety-of-life and transport-corridor cells rank above residential or rural sites.
