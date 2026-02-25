# Sprint 3 — Production Readiness & Depth

This sprint focuses on moving from "file exists" to "intent fulfilled" for the autonomous execution and intelligence layers.

## Proposed Changes

### [R-17] Standardize Logging
Update all service modules to use the structured `get_logger()` from `backend.app.core.logging`.

#### [MODIFY] Multiple Files
- `backend/app/services/alarm_correlation.py`
- `backend/app/services/auth_service.py`
- `backend/app/services/autonomous_action_executor.py`
- `backend/app/services/autonomous_shield.py`
- `backend/app/services/capacity_engine.py`
- `backend/app/services/customer_prioritisation.py`
- `backend/app/services/cx_intelligence.py`
- `backend/app/services/data_retention.py`
- `backend/app/services/drift_calibration.py`
- `backend/app/services/incident_service.py`
- `backend/app/services/netconf_adapter.py`
- `backend/app/services/pii_scrubber.py`
- `backend/app/services/policy_engine.py`
- `backend/app/services/proactive_comms.py`
- `backend/app/services/rl_evaluator.py`
- `backend/app/services/sleeping_cell_detector.py`
- `backend/app/services/autonomous_actions/cell_failover.py`

---

### [R-16] Audit Trail Enhancements
Add `action_type` to audit trail and implement CSV export.

#### [MODIFY] [audit_trail.py](file:///Users/himanshu/Projects/Pedkai/backend/app/models/audit_trail.py)
- Add `action_type` field (human, automated, rl_system).

#### [MODIFY] [incidents.py](file:///Users/himanshu/Projects/Pedkai/backend/app/api/incidents.py)
- Implement `GET /api/v1/incidents/{id}/audit-trail?format=csv`.

---

### [R-14] Digital Twin Similarity
Replace simplistic matching with real embedding-based similarity in Decision Memory.

#### [MODIFY] [digital_twin.py](file:///Users/himanshu/Projects/Pedkai/backend/app/services/digital_twin.py)
- Call `DecisionTraceRepository.find_similar()` using embeddings.
- Weight risk score by similarity of top-3 past decisions.

---

### [R-15] RL Feedback Loop
Ensure closed-loop integration of feedback into the RL system.

#### [MODIFY] [incidents.py](file:///Users/himanshu/Projects/Pedkai/backend/app/api/incidents.py)
- Update `close_incident()` to call `rl_evaluator.evaluate_decision_outcome()` and `apply_feedback()`.

---

### [R-13] Phase 5 Test Suite [NEW]
Create exhaustive integration tests for autonomous execution.

#### [NEW] [test_autonomous_full_cycle.py](file:///Users/himanshu/Projects/Pedkai/tests/integration/test_autonomous_full_cycle.py)
- Test all 7 gates.
- Test failure modes & auto-rollback.
- Chaos engineering (timeout simulation).

## Verification Plan

### Automated Tests
- `pytest tests/integration/test_autonomous_full_cycle.py`
- `pytest tests/api/test_incidents_audit_csv.py` (to be created)

### Manual Verification
- Trigger an autonomous action and verify Decision Memory similarity lookup in logs.
- Export audit trail CSV and verify column structure.
- Close an incident and verify RL evaluator logs.
