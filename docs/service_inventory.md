# Pedkai Service Inventory & Dependency Map

This document provides a complete inventory of the Pedkai backend services and API modules as of Phase 0.1.

## Summary
- **Total Service Modules**: 18
- **Total API Modules**: 14
- **Stateful Singletons**: 5 (Targets for decoupling)
- **Session Dependency**: 9 services directly depend on `AsyncSession` in `__init__`.

---

## 1. Service Modules (`backend/app/services/`)

| Module | Purpose | Class/Functions | Stateful? | Session Dep? |
| :--- | :--- | :--- | :--- | :--- |
| `alarm_correlation.py` | Alarm clustering & enrichment | `AlarmCorrelationService` | No | Yes (`AsyncSession`) |
| `auth_service.py` | User auth & seeding | `authenticate_user`, etc. | No | Yes (Arg-based) |
| `autonomous_shield.py` | Drift detection & advice | `AutonomousShieldService` | No | Yes (`AsyncSession`) |
| `bss_adapter.py` | BSS vendor abstraction | `LocalBSSAdapter` | No | Yes (`session`) |
| `bss_service.py` | Billing & revenue logic | `BSSService` | No | Yes (`AsyncSession`) |
| `capacity_engine.py` | Network densification AI | `CapacityEngine` | No | Yes (`session`) |
| `customer_prioritisation.py`| Strategy-based sorting | `prioritise_customers` | No | No |
| `cx_intelligence.py` | Churn & topology correlation | `CXIntelligenceService` | No | Yes (`session`) |
| `data_retention.py` | Retention & GDPR erasure | `run_retention_cleanup` | No | Yes (Arg-based) |
| `decision_repository.py` | Decision trace CRUD/Search | `DecisionTraceRepository` | No | Yes (`AsyncSession`) |
| `drift_calibration.py` | FP rate monitoring | `get_false_positive_rate` | No | Yes (Arg-based) |
| `embedding_service.py` | Vector generation (Gemini) | `EmbeddingService` | **Yes** (`_embedding_service`) | No |
| `llm_adapter.py` | Multi-LLM provider adapter | `GeminiAdapter`, `OnPremAdapter` | No | No |
| `llm_service.py` | SITREP & reasoning | `LLMService` | **Yes** (`_llm_service`) | Yes (Arg-based) |
| `pii_scrubber.py` | Regex prompt sanitization | `PIIScrubber` | No | No |
| `policy_engine.py` | "Telco Constitution" | `PolicyEngine` | **Yes** (`policy_engine`) | No |
| `proactive_comms.py` | Customer notification drafts | `ProactiveCommsService` | No | Yes (`AsyncSession`) |
| `rl_evaluator.py` | Closed-loop feedback | `RLEvaluatorService` | No | Yes (`db_session`) |

---

## 2. API Modules (`backend/app/api/`)

| Module | Scope | Dependencies | Stateful? |
| :--- | :--- | :--- | :--- |
| `auth.py` | JWT Token generation | `auth_service`, `db` | No |
| `autonomous.py` | Drift & Scorecard | `AutonomousShieldService`, `db`| No |
| `capacity.py` | Densification requests | `CapacityEngine`, `db` | No |
| `cx_router.py` | Proactive care trigger | `CXIntelligenceService`, `db` | No |
| `decisions.py` | Memory CRUD & Search | `DecisionTraceRepository`, `db`| **Yes** (`_decision_store`) |
| `health.py` | Liveness/Readiness | Direct DB engines | No |
| `incidents.py` | Lifecycle & Human Gates | `IncidentORM`, `db` | No |
| `service_impact.py` | Alarm clusters & Revenue | `AlarmCorrelationService`, `db`| No |
| `sse.py` | Real-time push | `db` | No |
| `tmf628.py` | Performance mgmt | `db` | No |
| `tmf642.py` | Alarm mgmt | `db` | No |
| `topology.py` | Graph & Impact | `db` | **Yes** (`_rate_limit_store`) |

---

## 3. Implementation Targets for Phase 0.3/0.4

### Session Factory Refactor (P0.3)
The following classes must switch from `AsyncSession` to `async_sessionmaker[AsyncSession]` to enable execution outside of FastAPI request context:
1. `AlarmCorrelationService`
2. `DecisionTraceRepository`
3. `AutonomousShieldService`
4. `BSSService`
5. `CapacityEngine`
6. `CXIntelligenceService`
7. `ProactiveCommsService`
8. `LocalBSSAdapter`
9. `RLEvaluatorService`

### PolicyEngine DI (P0.4)
1. Convert `policy_engine = PolicyEngine()` in `policy_engine.py` to `get_policy_engine()`.
2. Update `CXIntelligenceService`, `LLMService`, `RLEvaluatorService`, and others to use the factory.
