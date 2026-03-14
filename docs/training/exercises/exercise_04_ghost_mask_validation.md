# Exercise 4: Ghost Mask Validation

**Duration:** 20 minutes
**Difficulty:** Intermediate
**Learning Objectives:**
- Understand when anomalies should be suppressed due to planned maintenance
- Distinguish genuine anomalies from expected degradation during change windows
- Correctly apply ghost masking rules in Pedk.ai

## Scenario

It is Tuesday 14:00 WIB (Western Indonesia Time). The Jakarta NOC team is reviewing Pedk.ai's anomaly feed. A planned maintenance window was scheduled: **Site JKTBND002 — equipment firmware upgrade — 13:00-16:00 WIB**. Simultaneously, a transport maintenance window is active: **JKTHUB001-JKTHUB002 link — traffic reroute — 13:30-15:30 WIB**.

The following 5 anomalies have been flagged by Pedk.ai:

| Anomaly ID | Entity ID | Domain | Type | Detected At | Z-Score |
|------------|-----------|--------|------|-------------|---------|
| ANML-001 | JKTBND002-SEC1 | RAN | PRB spike | 13:15 WIB | 4.1 |
| ANML-002 | JKTBND002-SEC3 | RAN | SINR drop | 13:22 WIB | 3.8 |
| ANML-003 | JKTHUB001 | Transport | Link utilisation spike | 13:35 WIB | 5.2 |
| ANML-004 | SBYBDR001-SEC2 | RAN | Sleeping cell decay | 11:45 WIB | 3.1 |
| ANML-005 | JKTBND001-SEC1 | RAN | Handover failure spike | 14:05 WIB | 6.7 |

The change schedule confirms:
- JKTBND002 cells are under firmware upgrade (13:00-16:00 WIB) — all anomalies expected
- JKTHUB001 traffic reroute causes downstream congestion on JKTHUB001 — expected
- SBYBDR001 has no planned maintenance
- JKTBND001 has no planned maintenance

## Tasks

1. Review the anomaly list and change schedule. Identify which anomalies should be ghost-masked.
2. For ANML-005 (the highest z-score, JKTBND001 — no maintenance), determine whether this requires immediate investigation or could be related to the JKTHUB transport reroute.
3. Document your masking decisions with reason codes.

## Expected Findings

ANML-001 and ANML-002: **Ghost masked** — within JKTBND002 maintenance window.
ANML-003: **Ghost masked** — within JKTHUB001 transport maintenance window.
ANML-004: **Genuine anomaly** — SBYBDR001 has no maintenance; sleeping cell decay pre-dates maintenance windows.
ANML-005: **Genuine anomaly requiring investigation** — no maintenance at JKTBND001; z-score 6.7 is high; possible cascade from JKTHUB reroute affecting neighbouring cells outside maintenance scope.

## Scoring Criteria

| Criterion | Points | Description |
|-----------|--------|-------------|
| Correctly ghost-mask ANML-001 | 15 | Must cite maintenance window overlap |
| Correctly ghost-mask ANML-002 | 15 | Must cite maintenance window overlap |
| Correctly ghost-mask ANML-003 | 15 | Must cite transport maintenance window |
| Correctly identify ANML-004 as genuine | 20 | No maintenance → genuine sleeping cell |
| Correctly identify ANML-005 as genuine + note cascade hypothesis | 25 | Z-score severity + cascade from transport |
| Provide reason codes for all decisions | 10 | At least 3 of 5 with documented rationale |

**Total: 100 points. Pass mark: 70 points.**

## Key Learning Points

- Ghost masking prevents alert fatigue during legitimate maintenance, but only applies to the exact entities in the change schedule — not neighbours or downstream systems.
- High-severity anomalies outside the maintenance scope always require investigation, even if temporally proximate to planned maintenance.
- The cascade effect (JKTHUB reroute causing JKTBND001 congestion) illustrates why Pedk.ai's Dark Graph is essential — simple alarm suppression would miss this.
