# Pedkai Amendment Status Tracker

**Source**: `committee_reassessment_feb2026.md` — 5 BLOCKER, 10 HIGH, 8 MEDIUM findings  
**Updated**: 22 February 2026 — after completion of Layers 0–8

---

## Status Legend

| Symbol | Meaning |
|--------|---------|
| ✅ | Complete and verified |
| ⚠️ | Out of scope / requires non-engineering action |

---

## Amendment Tracker

| # | Amendment | Layer | Task(s) | Status | Evidence |
|---|-----------|-------|---------|--------|----------|
| 1 | Remove `execute_preventive_action()` | Pre-existing | — | ✅ Done | Method absence confirmed |
| 2 | 3 human gates in incident lifecycle | Pre-existing | — | ✅ Done | Gates visible in `incidents.py` lifecycle |
| 3 | LLM data classification + PII scrubbing | 0 | 0.2 | ✅ Done | `PIIScrubber` wired in `llm_service.py`; test passes |
| 4 | DPIA and regulatory framework | 6 | 6.3 | ✅ Done | `docs/dpia_scope.md` — 7 sections incl. EU AI Act |
| 5 | NOC operational runbook | 6 | 6.1 | ✅ Done | `docs/noc_runbook.md` — 5 sections incl. Emergency Protocol |
| 6 | Emergency service unconditional P1 | 1 | 1.3 | ✅ Done | `incidents.py` uses `entity_type` DB lookup; test passes |
| 7 | Audit trail (approver + model version + timestamps) | 3 | 3.4 | ✅ Done | `llm_model_version` + `llm_prompt_hash` populated in `incidents.py` |
| 8 | LLM grounding validation + confidence scoring | 3 | 3.2 | ✅ Done | `_compute_confidence()` in `llm_service.py`; test passes |
| 9 | Topology accuracy monitoring + refresh strategy | 2 | 2.4 | ✅ Done | `last_synced_at` 7-day threshold in `topology.py`; documented in ADR |
| 10 | BSS adapter abstraction layer | Pre-existing | — | ✅ Done | `bss_adapter.py` + batch query fix (Task 1.4) |
| 11 | ARPU fallback → "unpriced" flag | Pre-existing | — | ✅ Done | `requires_manual_valuation` returned by BSS service |
| 12 | Multi-tenant isolation testing | 0 + 8 | 0.3, 0.4, 8.3 | ✅ Done | `test_tenant_isolation_regression.py` — 6 tests pass |
| 13 | WebSocket/SSE for real-time push | 4 | 4.1, 4.2 | ✅ Done | `sse.py` registered at `/api/v1/stream/alarms`; frontend uses `EventSource` |
| 14 | Load test at 200K alarms/day | 8 | 8.2 | ⚠️ Template created | `tests/load/LOAD_TEST_RESULTS.md` — requires live run against PostgreSQL |
| 15 | AI maturity ladder | 7 | 7.1 | ✅ Done | `docs/ai_maturity_ladder.md`; `ai_maturity_level` in `config.py` |
| 16 | TMF mapping for new APIs (621, 656, 921) | — | — | ⚠️ Out of scope v1 | Documented as future work — requires product owner scoping |
| 17 | Shadow-mode pilot architecture | 6 | 6.4 | ✅ Done | `docs/shadow_mode.md` — full architecture with DB schema + success criteria |
| 18 | NOC training curriculum | 6 | 6.2 | ✅ Done | `docs/training_curriculum.md` — 4 modules, 6 hours total |
| 19 | Demo milestones per work stream | — | — | ⚠️ Product owner required | Not a code task — requires roadmap decision |
| 20 | Per-incident LLM cost model | 7 | 7.5 | ✅ Done | `_estimate_cost()` in `llm_service.py`; `llm_cost_usd` in every response |
| 21 | Customer prioritisation algorithm (configurable) | 7 | 7.3 | ✅ Done | `customer_prioritisation.py` — 4 strategies; config-driven |
| 22 | RBAC granularity for new endpoints | 1 | 1.1 | ✅ Done | Real auth + `shift_lead` + `engineer` users seeded in `auth_service.py` |
| 23 | Bias drift detection in RLHF loop | — | — | ⚠️ Future work | RLHF loop does not yet exist — prerequisite missing |
| 24 | Drift detection calibration protocol | 7 | 7.2 | ✅ Done | `drift_calibration.py`; `drift_threshold_pct` configurable in `config.py` |
| 25 | Dashboard progressive disclosure design | 5 | 5.2 | ✅ Done | `StatCard`, `AlarmCard`, `SitrepPanel` extracted as components |
| 26 | Data retention policies | 7 | 7.4 | ✅ Done | `data_retention.py` — per-DPIA policies; `anonymise_customer()` for GDPR Art. 17 |

---

## Summary

| Category | Count |
|----------|-------|
| ✅ Complete and verified | **22** |
| ⚠️ Out of scope / non-engineering action required | **4** |
| **Total amendments** | **26** |

---

## Out-of-Scope Items (require non-engineering action)

| # | Amendment | Reason | Owner |
|---|-----------|--------|-------|
| 14 | Load test at 200K alarms/day | Template created; requires actual PostgreSQL instance for valid results | Engineering + Infra |
| 16 | TMF mapping for APIs 621, 656, 921 | No product requirement yet; requires scoping with product owner | Product |
| 19 | Demo milestones per work stream | Roadmap decision — not a code task | Product Owner |
| 23 | Bias drift detection in RLHF loop | RLHF loop does not exist; prerequisite for this amendment | Engineering (future) |

---

## Security Regression Test Coverage

The following amendments are now covered by automated regression tests that will fail if a regression is introduced:

```
tests/security/test_security_regressions.py     — 9 tests (Amendments 3, 6, 7, 8, 12, 20)
tests/security/test_tenant_isolation_regression.py — 6 tests (Amendment 12)

Run: python -m pytest tests/security/ -v
Result: 15 passed in 0.04s ✅
```
