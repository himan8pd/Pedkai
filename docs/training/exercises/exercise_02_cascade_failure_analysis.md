# Exercise 2: Cascade Failure Analysis

**Duration:** 20 minutes
**Difficulty:** Intermediate
**Learning Objectives:**
- Reconstruct a failure propagation path from a multi-domain alarm timeline
- Distinguish the transport-layer root cause from the downstream RAN symptoms it produces
- Produce a structured incident summary suitable for handover to a senior engineer

## Scenario

At 14:27 WIB on a Thursday, the Pedk.ai platform raises a P1 incident: three cells in the Surabaya ring are reporting severe throughput degradation simultaneously. Within four minutes a further six alarms fire across RAN and transport. The on-call NOC engineer must determine whether this is a single transport event with RAN cascade effects, or three independent radio faults coinciding.

The affected cells are:
- **SBYSMG011-SEC1**, **SBYSMG011-SEC2**, **SBYSMG012-SEC1** — all hanging off the same aggregation node at Surabaya Selatan (AGG-SBYS-04)

## Data Provided

Alarm timeline (all timestamps WIB):

| Time | Source | Alarm | Severity |
|------|--------|-------|----------|
| 14:23 | AGG-SBYS-04 | Link loss to transit router TR-SBYS-02 | Critical |
| 14:24 | AGG-SBYS-04 | Backhaul utilisation spike — 98% on port Gi0/1 | Major |
| 14:27 | SBYSMG011-SEC1 | Throughput degradation — DL 12 Mbps vs 94 Mbps baseline | Critical |
| 14:27 | SBYSMG011-SEC2 | Throughput degradation — DL 9 Mbps vs 87 Mbps baseline | Critical |
| 14:28 | SBYSMG012-SEC1 | Throughput degradation — DL 8 Mbps vs 91 Mbps baseline | Critical |
| 14:29 | SBYSMG011-SEC1 | Handover failure rate >30% | Major |
| 14:30 | SBYSMG011-SEC2 | PDCP retransmission rate >25% | Major |
| 14:31 | SBYSMG012-SEC1 | RRC setup failure rate 18% | Major |
| 14:34 | NOC Platform | Correlation engine: 3 cells share AGG-SBYS-04 | Info |

KPI trends for SBYSMG011-SEC1 (5-minute intervals before and during incident):

| Time | DL Throughput (Mbps) | RTT to core (ms) | PRB Util (%) |
|------|---------------------|------------------|--------------|
| 14:10 | 91 | 8 | 44 |
| 14:15 | 93 | 9 | 46 |
| 14:20 | 88 | 11 | 43 |
| 14:25 | 47 | 38 | 61 |
| 14:30 | 14 | 142 | 78 |
| 14:35 | 11 | 189 | 81 |

Note that the PRB utilisation *rises* during the incident. This is a key distinguishing artefact: UEs are retransmitting aggressively, consuming radio resource, but backhaul cannot carry the resulting traffic.

## Tasks

1. **Map the propagation path.** List the failure events in causal order, from initial fault to final RAN symptoms. Use the format: `[event type] → [event type] → ...`. Your path must have at least three hops.

2. **Identify the root cause.** State the root cause domain (transport, RAN, or core) and the specific component. Justify your choice by explaining why the timing of the AGG-SBYS-04 alarms relative to the RAN alarms is diagnostic.

3. **Count directly affected cells.** State how many cells are directly affected by this single transport failure and explain how you determined this from the alarm data.

4. **Draft a 3-sentence incident summary** suitable for the shift handover log, naming the root cause, propagation path, and current status.

## Expected Findings

- **Root cause:** Transport link failure — specifically, loss of the link between AGG-SBYS-04 and transit router TR-SBYS-02 at 14:23 WIB (4 minutes before the first RAN alarm)
- **Propagation path:** `transport_failure (link loss AGG-SBYS-04 → TR-SBYS-02)` → `backhaul_degradation (98% utilisation on surviving path)` → `ran_throughput_drop (3 cells, DL degradation 85–91%)` → `secondary RAN symptoms (handover failures, PDCP retransmissions, RRC setup failures)`
- **Affected cells count:** 3 (SBYSMG011-SEC1, SBYSMG011-SEC2, SBYSMG012-SEC1 — all sharing AGG-SBYS-04)
- The rising PRB utilisation during throughput degradation confirms the radio path itself is functional; the bottleneck is backhaul, ruling out an RF or scheduler fault at the cell level

## Scoring Criteria

| Criterion | Points | Description |
|-----------|--------|-------------|
| Root cause correctly identified as transport | 30 | Must name transport layer and AGG-SBYS-04 or TR-SBYS-02 link |
| Propagation path correct | 30 | All three hops present: transport failure → backhaul degradation → RAN throughput drop |
| Affected cells count correct (3) | 20 | Must state 3 cells and link to shared aggregation node |
| Timing analysis used | 10 | Trainee references the 4-minute lag between transport alarm and RAN alarms |
| PRB utilisation artefact noted | 10 | Trainee notes rising PRB as evidence of backhaul bottleneck not radio fault |

**Total: 100 points**
**Pass mark: 70 points**

## Key Learning Points

- In cascade failures, the **first alarm** is often not from the layer that users experience the problem on. Transport alarms preceding RAN alarms by several minutes is a classic signature.
- Rising PRB utilisation during a throughput drop is a counterintuitive but reliable indicator that the radio interface is functioning and the bottleneck is in the IP transport layer.
- Always check whether degraded cells share a common upstream node before raising separate tickets — the Pedk.ai correlation engine flags this but the NOC engineer must verify and confirm it.
