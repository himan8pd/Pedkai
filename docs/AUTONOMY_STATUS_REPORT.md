# Pedkai — Autonomy Status Report

**Document ID**: PEDKAI-ASR-001
**Version**: 1.0
**Date**: 2026-02-25
**Reporting Period**: February 2026
**Next Review**: March 2026

---

## 1. Current Autonomy Level

| Parameter | Value |
|-----------|-------|
| **AI Maturity Level** | **2 — Supervised (Advisory)** |
| Configuration key | `ai_maturity_level=2` |
| Autonomous execution | Gated — requires explicit Level 3 activation |
| Kill-switch | Active and tested |
| Safety gates | 4/4 operational (Blast Radius, Policy, Confirmation, Validation) |

## 2. Operational Metrics

### 2.1 AI Recommendation Performance

| Metric | Value | Target | Status |
|--------|-------|--------|--------|
| SITREP accept rate | Pending shadow data | >70% | ⏳ Collecting |
| Drift detection false positive rate | Calibrating | <15% | ⏳ Collecting |
| Alarm correlation accuracy | Functional | >85% | ✅ Operational |
| Sleeping cell detection | Functional | >80% | ✅ Operational |

### 2.2 Safety Pipeline Activity

| Gate | Invocations (this period) | Blocks | Block Rate |
|------|--------------------------|--------|------------|
| Blast Radius | 0 | 0 | N/A |
| Policy Engine | 0 | 0 | N/A |
| Confirmation Window | 0 | 0 | N/A |
| Post-Execution Validation | 0 | 0 | N/A |

> **Note**: Safety pipeline statistics are zero because autonomous execution has not been activated in production. Stats will populate once Level 3 staging tests begin.

## 3. Level 3 Readiness Checklist

| Requirement | Status | Notes |
|-------------|--------|-------|
| Safety whitepaper approved | ✅ Complete | `AUTONOMOUS_SAFETY_WHITEPAPER.md` |
| Ofcom pre-notification filed | ✅ Complete | `OFCOM_PRE_NOTIFICATION.md` |
| ICO DPIA completed | 🟡 Pending DPO sign-off | `ICO_DPIA.md` |
| Blast radius gate tested | ✅ Implemented | Threshold: 10 entities |
| Validation gate tested | ✅ Implemented | 5-min poll, 10% threshold |
| Kill-switch tested | ✅ Implemented | `POST /kill-switch` |
| Confidence scoring from Decision Memory | ✅ Implemented | Replaces hardcoded 0.9 |
| 30-day shadow mode baseline | ⏳ Not started | Required before Level 3 |
| Operator training completed | ❌ Not started | Required before Level 3 |
| Board sign-off | ❌ Not started | Required before Level 3 |

## 4. Risks and Blockers

| Risk | Severity | Mitigation | Owner |
|------|----------|------------|-------|
| Shadow mode baseline not yet collected | High | Schedule 30-day shadow deployment | Platform Ops |
| DPO has not reviewed DPIA | Medium | Escalate for Q1 review | Legal |
| Operator training materials not created | Medium | Draft training guide | Product |
| BSS integration using mock adapter | Medium | `is_estimate` flag on all revenue figures | Engineering |

## 5. Recommendation

**Do NOT activate Level 3 (Autonomous) until:**
1. 30-day shadow mode baseline is collected and validated
2. DPO signs off on DPIA
3. Operator training is completed
4. Board provides formal approval

Current AI Maturity Level 2 (Supervised/Advisory) is appropriate for all production deployments.
