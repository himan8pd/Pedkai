# Test Suite Coverage Audit Report
**Date:** 2026-03-10
**Codebase:** /Users/himanshu/Projects/Pedkai

---

## Executive Summary

The Pedkai test suite contains **43 test functions** across **12 test files**, totaling **5,411 lines of test code**. However, **34 major source modules (42.5% of services/API modules) have zero test coverage**, indicating significant gaps in unit and integration testing.

---

## Test Files Inventory

### Unit Tests (4 files, 16 tests)
| File | Test Count | Location |
|------|-----------|----------|
| test_causal_models.py | 3 | `tests/unit/` |
| test_normalizer.py | 2 | `tests/unit/` |
| test_pii_scrubber.py | 8 | `tests/unit/` |
| test_sovereignty.py | 3 | `tests/unit/` |

### Integration Tests (4 files, 9 tests)
| File | Test Count | Location |
|------|-----------|----------|
| test_action_state_machine.py | 1 | `tests/integration/` |
| test_e2e_pipeline.py | 2 | `tests/integration/` |
| test_embedding_isolation.py | 2 | `tests/integration/` |
| test_netconf_adapter.py | 1 | `tests/integration/` |
| test_policy_security.py | 3 | `tests/integration/` |

### Security Tests (2 files, 15 tests)
| File | Test Count | Location |
|------|-----------|----------|
| test_security_regressions.py | 9 | `tests/security/` |
| test_tenant_isolation_regression.py | 6 | `tests/security/` |

### Load Tests (1 file, 3 tests)
| File | Test Count | Location |
|------|-----------|----------|
| test_correlation_load.py | 3 | `tests/load/` |

### Supporting Files (with no test functions)
- `tests/conftest.py` — pytest fixtures and configuration
- `tests/data/__init__.py` — test data markers
- `tests/data/live_test_data.py` — live data validation support
- `tests/load/locustfile.py` — load testing configuration
- `tests/load/__init__.py` — load test package marker
- `tests/security/__init__.py` — security test package marker
- `tests/validation/__init__.py` — validation test package marker
- `tests/validation/test_live_data_*.py` (8 files) — validation suite without explicit test functions

---

## Total Test Count

**43 test functions** across **12 files with test code**

---

## Module Coverage Analysis

### Modules with ZERO Test Coverage (34 modules)

#### API Routes (10 modules)
- `adapters`
- `auth`
- `autonomous`
- `capacity`
- `cx_router`
- `decisions`
- `health`
- `incidents`
- `ingestion`
- `operator_feedback`
- `policies`
- `reports`
- `service_impact`
- `sse`
- `tmf628`
- `tmf642`

#### Services (20 modules)
- `auth_service`
- `autonomous_action_executor` ⚠️ (has safety gates but only 2 integration tests)
- `bss_adapter`
- `bss_service`
- `capacity_engine`
- `customer_prioritisation`
- `data_retention`
- `drift_calibration`
- `embedding_local`
- `embedding_service`
- `incident_service`
- `investment_planning`
- `llm_adapter`
- `llm_service`
- `netconf_adapter` (1 minimal test only)
- `proactive_comms`
- `reconciliation_engine`
- `rl_evaluator`
- `sleeping_cell_detector`
- `topology`

#### Models (4 modules)
- `tmf642_models`
- `topology_models`
- Plus base/utility models

### Modules with Partial Coverage (9 modules)
- `causal_models` — 3 tests
- `policy_engine` — 1 test (policy_gate_blocks_invalid_action)
- `normalizer` — 2 tests
- `pii_scrubber` — 8 tests
- `sovereignty_service` — 3 tests
- `digital_twin` — tested indirectly in phase5_readiness
- Core modules (config, database, security) — tested indirectly

---

## Safety Gates Implementation

The codebase implements a **4-gate safety pipeline** for autonomous actions (found in `backend/app/services/autonomous_action_executor.py`):

### Gate 1: Blast Radius Check (R-9)
- **Description:** Hard limit on affected entities to prevent cascading failures
- **Threshold:** Maximum 10 entities per action (`BLAST_RADIUS_MAX_ENTITIES = 10`)
- **Implementation Location:** `autonomous_action_executor.py:107-122`
- **Test Coverage:** `test_safety_gates_blast_radius()` in `test_phase5_readiness.py`
- **Block Action:** Fails action with reason "blast_radius_exceeded"

### Gate 2: Policy Evaluation
- **Description:** Evaluates action against tenant policies and confidence thresholds
- **Implementation Location:** `autonomous_action_executor.py:168-192`
- **Test Coverage:** `test_policy_gate_blocks_invalid_action()` in `test_safety_rails.py`
- **Block Action:** Fails action with reason "policy_blocked" if decision != "allow"
- **Confidence Source:** Derives from Decision Memory similarity (default 0.5 conservative)

### Gate 3: Confirmation Window (implicit)
- **Description:** Enforces human-in-the-loop confirmation delay for autonomous actions
- **Timing:** Awaits confirmation window (default 30 seconds, configurable per policy)
- **Implementation Location:** `autonomous_action_executor.py:194-204`
- **Status:** No dedicated unit test found
- **State:** Action transitions to AWAITING_CONFIRMATION before execution

### Gate 4: Post-Execution Validation (R-8)
- **Description:** Monitors KPIs post-execution; auto-rollback if degradation exceeds threshold
- **Threshold:** > 10% KPI degradation (`VALIDATION_DEGRADATION_PCT = 10.0`)
- **Poll Window:** 5 minutes (`VALIDATION_POLL_SECONDS = 300`), capped at 10s in PoC
- **Implementation Location:** `autonomous_action_executor.py:239-243, 283-332`
- **Test Coverage:** `test_safety_gates_validation_rollback()` in `test_phase5_readiness.py`
- **Fallback:** Uses Digital Twin prediction if no KPI baseline (risk_score < 70 = pass)
- **Rollback:** Transitions action to ROLLED_BACK state with audit trail

### Additional Gates Identified

#### Human Gate (Incident Lifecycle)
- **Description:** Enforces human approval before advancing incident from sitrep_draft
- **Implementation:** Incident API requires explicit approve-sitrep endpoint
- **Test Coverage:** `test_human_gate_enforcement()` in `test_incident_lifecycle.py`
- **Location:** `backend/app/api/incidents.py`

#### Policy Rule Gates
- **Description:** Policy Engine evaluates named rules to block invalid actions
- **Matched Rules:** Returned in action failure response
- **Implementation Location:** `policy_engine.py` (NO UNIT TESTS)

---

## Pytest Configuration

**pytest.ini settings:**
```ini
[pytest]
asyncio_mode = auto
pythonpath = .
filterwarnings =
    ignore::DeprecationWarning
    ignore::UserWarning
testpaths = tests
```

**Test Command:**
```bash
pytest tests/
```

**Run Specific Category:**
```bash
pytest tests/unit/          # Unit tests only
pytest tests/security/      # Security regression tests
pytest tests/integration/   # Integration tests
pytest tests/load/          # Load tests
```

**Run with Verbose Output:**
```bash
pytest tests/ -v
```

**Run with Coverage Report:**
```bash
pytest tests/ --cov=backend.app --cov-report=html
```

---

## Coverage Gaps - Priority Recommendations

### Critical (Safety/Security)
1. **autonomous_action_executor.py** — Only 2 integration tests for 4-gate system. Needs:
   - Unit tests for each gate independently
   - Negative test cases (malformed entities, policy violations)
   - Edge cases (UUID string handling, null baselines)

2. **policy_engine.py** — Core safety gate with 1 policy test. Needs:
   - Rule evaluation matrix tests
   - Named rule matching tests
   - Policy conflict resolution tests

3. **incident_service.py** — No tests for incident state transitions. Needs:
   - Full lifecycle tests (anomaly → sitrep → action → resolved)
   - Failure path tests

### High (Feature Completeness)
4. **embedding_service.py** — No direct tests. Used by Decision Memory. Needs:
   - Embedding quality tests
   - Similarity search accuracy tests

5. **auth_service.py** — No unit tests. Needs:
   - Token generation/validation
   - Role-based access control
   - Multi-tenant isolation

6. **llm_service.py** — No tests. Mock LLM calls. Needs:
   - Prompt construction
   - Response parsing

### Medium (Integration)
7. **capacity_engine.py** — No tests for capacity planning logic
8. **cx_intelligence.py** — Tested indirectly, needs explicit coverage
9. **rl_evaluator.py** — No tests for RL decision evaluation

---

## Test Code Quality Notes

### Strengths
- Comprehensive security regression suite (15 tests)
- Good async/await testing patterns (all integration tests use pytest-asyncio)
- Fixture-based setup in conftest.py for database and client mocking
- Clear test naming convention (test_<feature>_<scenario>)

### Weaknesses
- Many integration tests have placeholder implementations (mocked Digital Twin, mock Netconf)
- Validation test suite (8 files) exists but functions lack explicit `def test_` naming
- No pytest markers for test categories (slow, security, unit) — manual filtering only
- Limited parametrized tests (testing only happy paths)

---

## Appendix: Source Module Inventory

### Services Layer (25 modules)
Located in `backend/app/services/`:
- Tested: causal_models, embedding_service, netconf_adapter, policy_engine, pii_scrubber
- **NOT Tested:** alarm_correlation, auth_service, autonomous_action_executor (minimal), bss_adapter, bss_service, capacity_engine, customer_prioritisation, cx_intelligence, data_retention, decision_repository, digital_twin, drift_calibration, embedding_local, incident_service, llm_adapter, llm_service, proactive_comms, reconciliation_engine, rl_evaluator, sleeping_cell_detector, sovereignty_service, topology, and 2 others

### API Routes (17 modules)
Located in `backend/app/api/`:
- **All untested:** adapters, alarm_ingestion, auth, autonomous, capacity, cx_router, decisions, health, incidents, ingestion, operator_feedback, policies, reports, service_impact, sse, tmf628, tmf642, topology

### Models (24 modules)
Located in `backend/app/models/`:
- ORM models: action_execution_orm, audit_orm, bss_orm, customer_orm, decision_trace_orm, incident_orm, kpi_orm, kpi_sample_orm, network_entity_orm, policy_orm, tenant_orm, user_orm, user_tenant_access_orm, and others
- Schema models: autonomy schemas, customer_experience, incidents, investment_planning, policies, service_impact, topology
- **Coverage:** Only indirect testing via API/service integration tests

### Core (5 modules)
Located in `backend/app/core/`:
- config.py, database.py, init_db.py, logging.py, observability.py, resilience.py, security.py
- **Coverage:** Tested indirectly through fixtures and integration tests

---

## Conclusion

The test suite focuses on **integration and security** (28 tests, 65%) rather than **unit testing** (12 tests, 28%), leaving **critical autonomous action safety gates underfunded** with only 2 dedicated tests. The lack of coverage for 34 modules (primarily API routes and services) indicates that **most feature paths are untested** and depend on integration tests or production validation.

**Estimated Coverage:** ~8-12% of codebase (based on module coverage only; actual line coverage likely lower due to conditional logic and error paths).

**Recommendation:** Increase unit test coverage to 40%+ minimum before production deployment, with emphasis on safety gates, policy evaluation, and core business logic (incidents, autonomy, capacity).
