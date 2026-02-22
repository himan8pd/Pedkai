# AI Maturity Ladder — Pedkai

**Version**: 1.0 | **Audience**: CTO, Board, Legal Counsel, Regulator  
**Status**: Approved — current deployment target is Level 2

---

## Overview

The AI Maturity Ladder defines the governance framework for progressively increasing the autonomy of Pedkai's AI. Each level requires explicit approval before activation. Higher levels are **not available in v1**.

---

## Level 1 — Assisted (Shadow Mode)
**Current state during the 30-day shadow period**

| Aspect | Detail |
|--------|--------|
| **What AI does** | Correlates alarms, generates SITREP drafts, suggests root cause |
| **What operators see** | Nothing — AI outputs are logged but not shown |
| **Human involvement** | 100% — operators run standard NOC procedures |
| **Gate to Level 2** | Shadow mode accuracy targets met (see `docs/shadow_mode.md`) |

*Rationale*: Level 1 establishes the performance baseline required for counterfactual metrics. No operator dependency on AI during this phase.

---

## Level 2 — Supervised (Current Production Target)
**Advisory mode — recommendations shown, human approves every action**

| Aspect | Detail |
|--------|--------|
| **What AI does** | Shows correlations, confidence scores, SITREP + recommended actions |
| **What operators see** | Full AI analysis with `🤖 AI Generated — Advisory Only` watermark |
| **Human involvement** | 3 mandatory gates: approve SITREP, approve action, close |
| **Autonomous execution** | ❌ Not permitted — AI cannot modify network configuration |
| **Gate to Level 3** | 6 months Level 2 operation + board approval + false positive rate < 2% |

*Rationale*: Operators remain in full control. AI is a high-quality recommendation engine with explicit confidence scoring. All decisions are traceable via the audit trail.

---

## Level 3 — Autonomous (Future — Not Available in v1)
**Closed-loop mode — AI executes low-risk actions without prior approval**

| Aspect | Detail |
|--------|--------|
| **What AI does** | Executes approved low-risk playbooks automatically (e.g., restart a service) |
| **Human involvement** | Post-hoc review — operator reviews what AI did, not pre-approves |
| **Restriction** | Only whitelisted action types; emergency service entities always require human gate |
| **Requirements before enabling** | 6 months Level 2 + false positive rate < 2% + explicit board approval |

> [!CAUTION]
> Level 3 is explicitly **not implemented** in v1. Any call to autonomous execution methods raises `NotImplementedError`. Activation requires a separate board-level decision and a new DPIA assessment.

---

## Governance Controls

- The current maturity level is set via `ai_maturity_level` in `config.py` (default: `2`)
- Changing the level requires: CTO approval + DPO review + engineering sign-off
- The maturity level is logged on every AI recommendation in the audit trail
- Emergency service entities are **always subject to human gate regardless of maturity level**
