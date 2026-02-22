# Shadow-Mode Deployment Architecture

**Version**: 1.0 | **Audience**: Engineering, Legal, Regulator (Ofcom)  
**Status**: Approved — required before advisory mode enablement

---

## 1. What Shadow Mode Is

In shadow mode, Pedkai runs **alongside the existing NOC** consuming the same alarm feed, generating recommendations and correlations — but these outputs are:

- **Logged to `shadow_decisions` table** (not `incidents` or `decision_traces`)
- **Not shown to operators** during the shadow period
- **Not used to trigger any network actions**

This means the live network operates exactly as it would without Pedkai. Operators follow existing NOC procedures. Pedkai is a silent observer collecting a baseline.

This is the **only approved method** for establishing the non-Pedkai baseline required for counterfactual metrics. Without this data, the scorecard returns `null` for non-Pedkai zone comparisons (as documented in `docs/value_methodology.md`).

---

## 2. Why It Is Required

The committee scorecard (`/api/v1/autonomous/scorecard`) reports improvements vs a non-Pedkai baseline. That baseline cannot be fabricated (see Task 2.1 — B-4 BLOCKER fix). It must be measured.

Without shadow mode:
- Revenue protected = `null`
- Incidents prevented = `null`
- MTTR improvement = `null`
- EU AI Act Art. 9 (risk management) cannot be satisfied without accuracy data

---

## 3. Duration and Milestones

| Phase | Duration | What Happens |
|-------|----------|-------------|
| **Shadow mode** | 30 days | Pedkai logs what it *would* have done; operators run business as usual |
| **Accuracy review** | 30 days analysis | Engineering compares shadow decisions to actual operator decisions |
| **Report to L2** | 1 week | Accuracy report presented to CTO + NOC Director |
| **Advisory mode** (gated) | If approved | Pedkai recommendations shown to operators; human gates remain |

---

## 4. Technical Architecture

### 4.1 Configuration Flag
```python
# backend/app/core/config.py
shadow_mode: bool = False  # Set True during shadow period via SHADOW_MODE=true env var
```

When `shadow_mode = True`:
- All AI recommendations write to `shadow_decisions` table
- No records are written to `incidents` or `decision_traces`
- The NOC dashboard does not show AI recommendations
- All alarm processing and correlation still runs (to generate the baseline data)

### 4.2 Shadow Decisions Table Schema
```sql
CREATE TABLE shadow_decisions (
    id          TEXT PRIMARY KEY,
    tenant_id   TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    alarm_ids   JSONB,           -- IDs of correlated alarms
    trigger_type TEXT,           -- What triggered the recommendation
    recommended_action TEXT,     -- What Pedkai would have recommended
    confidence  FLOAT,           -- Confidence score at time of recommendation
    actual_outcome TEXT,         -- Filled in during accuracy review
    agreed_with_operator BOOLEAN -- Was this what the operator actually did?
);
```

### 4.3 Comparison Logic
During the accuracy review period, Engineering compares:
- `shadow_decisions.recommended_action` vs actual operator actions in `incidents`
- Match = true positive; no incident raised = potential prevention; mismatch = learning signal

---

## 5. Success Criteria (Gate to Advisory Mode)

| Metric | Target | How Measured |
|--------|--------|-------------|
| False positive rate | < 5% | Shadow recommendations where no incident was raised / total recommendations |
| Missed correlation rate | < 10% | P1/P2 incidents that Pedkai did NOT flag / total P1/P2 incidents |
| MTTR improvement (simulated) | > 15% vs baseline | Estimated MTTR if shadow recommendations had been followed |
| Zero safety guard violations | 0 violations | Emergency service entities always flagged P1 |

**All four criteria must be met** before L2 approval to enable advisory mode. Any single failure extends the shadow period by 30 days.

---

## 6. Regulatory Context

Under the EU AI Act (Annex III), Pedkai must demonstrate system accuracy before deployment in a high-risk context. Shadow mode provides the required evidence. Results must be included in the conformity assessment documentation.
