# Value Methodology: How Pedkai Calculates Business Impact

**Version**: 1.0 | **Audience**: CFO, Board, Commercial Teams, Auditors

---

## Overview

Pedkai reports three value metrics:
1. **Revenue Protected** — revenue that would have been at risk during service outages
2. **Incidents Prevented** — outages avoided through early drift detection
3. **Uptime Gained** — minutes of additional network availability

These are **estimates based on counterfactual analysis**. They are not guaranteed savings. Confidence intervals are provided for all figures.

---

## Methodology: Pedkai Zone vs Non-Pedkai Zone

### Comparison Framework

Pedkai divides the network into two zones:
- **Pedkai Zone**: Sites and cells where Pedkai is actively monitoring and providing recommendations
- **Non-Pedkai Zone**: Sites and cells operating under standard NOC procedures without Pedkai

We compare MTTR (Mean Time to Resolve) and incident count between the two zones over a rolling 30-day window.

### Why This Approach?

A randomised control trial is not feasible in a live network. The zone comparison is the most rigorous available methodology for measuring operational tool impact in production environments.

### Limitations and Caveats

1. **Zone selection bias**: Pedkai may have been deployed first in more complex or higher-traffic areas, which could inflate the apparent improvement.
2. **Operator skill variation**: NOC engineers in Pedkai zones may have more experience.
3. **Seasonal effects**: Network load varies by season; 30-day windows may not capture this.
4. **Correlation ≠ causation**: Improvement in Pedkai zones may be partly attributable to other factors.

---

## Revenue Protected Calculation

```
Revenue Protected = Σ (revenue_at_risk for each prevented incident)

Where:
  revenue_at_risk = monthly_fee × (outage_duration_hours / 720)

For each customer:
  - monthly_fee: sourced from BSS billing data (no fallback ARPU)
  - outage_duration_hours: estimated from MTTR difference (Pedkai zone vs non-Pedkai zone)
```

### Important Constraints

- **No fallback ARPU**: If a customer has no billing data, they are marked `unpriced` and excluded from revenue calculations. We do not use industry-average ARPU as a proxy.
- **Unpriced customers are flagged**: The API returns `requires_manual_valuation: true` for unpriced customers.
- **Revenue figures require CFO sign-off** before use in board presentations or commercial materials.

---

## Incidents Prevented Calculation

```
Incidents Prevented = count of drift detections where:
  - Pedkai issued a recommendation
  - Engineer acted on the recommendation within 2 hours
  - No P1/P2 incident was raised in the subsequent 24 hours
  - The entity would have been expected to breach threshold (based on drift trajectory)
```

### Confidence Scoring

Each prevented incident is assigned a confidence score (0.0–1.0):
- `0.7–1.0`: High confidence — clear drift trajectory, recommendation acted on, no incident
- `0.4–0.69`: Medium confidence — drift detected but trajectory was uncertain
- `0.0–0.39`: Low confidence — excluded from headline figures

---

## Uptime Gained Calculation

```
Uptime Gained (minutes) = Σ (MTTR_non_pedkai - MTTR_pedkai) for each incident

Where:
  MTTR_non_pedkai: average MTTR for equivalent incidents in non-Pedkai zones
  MTTR_pedkai: actual MTTR for the incident in the Pedkai zone
```

---

## Confidence Interval

All figures are reported with a **±15% confidence interval** based on:
- 30-day comparison window
- Zone selection methodology
- Billing data completeness

---

## Audit Trail

All value calculations are reproducible from:
1. Incident records in the Pedkai database
2. BSS billing data snapshots
3. Alarm timestamps from OSS
4. Drift detection logs

Contact the Pedkai team for a full audit data export.
