- [x] Critical Remediations (Security & Core logic)
    - [x] [C-1] Secure Policy Engine (Remove `eval()`)
    - [ ] [C-2] Implement Real Closed-Loop RL (KPI checks)
    - [ ] [C-3] Fix BSS Revenue Fallback & Heuristics
- [/] High-Severity Remediations
    - [ ] [H-1] Expand Memory Benchmark (25+ cases, distractors)
    - [ ] [H-2] Real-world Capacity Engine (Context Graph integration)
    - [ ] [H-3] Graph-based CX Intelligence
    - [x] [H-4] Deprecate `utcnow()` (3 files)
    - [ ] [H-5] Fix LLM Prompt Duplication
- [/] **Medium-Severity Remediations**
    - [ ] [M-1] Implement Integration Tests for Phases 14/15
    - [ ] [M-2] Policy Engine Enhancements (Versioning, ALLOW handler)
    - [ ] [M-3] Fix Policy Engine Path config
    - [ ] [M-4] Optimize Recursive CTE (Remove N+1)


## Phase 2: Context Graph MVP (Layer 2)
- [x] Design graph schema (network topology, services, customers)
- [x] Implement graph database setup
- [x] Build multi-dataset loaders for Hugging Face targets
    - [x] `Telelogs-CoT` Integration (Reasoning Traces)
    - [x] `5G_Faults` Integration (Network Alarms)
    - [x] `Support-Tickets` Integration (Action Outcomes)
    - [x] "Wide Net" Mass-Ingestion (10+ Datasets via UniversalLoader)
    - [x] Western Market Alignment (US/EU Datasets Ingestion)
- [x] Gated TeleLogs Ingestion (Authenticated Access)
- [x] Kaggle Regional Expansion (India/UK/IE Logic)
    - [x] Configure Kaggle API credentials
    - [x] Implement `KaggleLoader` for CSV ingestion
    - [x] Ingest India: `arnavr10880/voice-call-quality-customer-experience-india`
    - [x] Ingest India: `kiranmehta1/indian-telecom-customer-churn-prediction-dataset`
    - [x] Ingest UK: `qwikfix/uk-broadband-speeds-2016`
    - [x] Ingest Global: `mnassrib/telecom-churn-datasets` & `blastchar/telco-customer-churn`
- [x] Build ETL pipelines for Context Graph population
- [x] Verify similarity search on real data samples

### Ingested Dataset Inventory
- **Regional Expansion (Kaggle)**: 
    - **India**: `arnavr10880/voice-call-quality-customer-experience-india` (Voice Quality), `kiranmehta1/indian-telecom-customer-churn-prediction-dataset` (Churn)
    - **UK**: `qwikfix/uk-broadband-speeds-2016` (Ofcom Broadband Performance)
    - **Global Baseline**: `mnassrib/telecom-churn-datasets`, `blastchar/telco-customer-churn`
- **Specialized 5G (Gated)**: `netop/TeleLogs` (High-fidelity troubleshooting)
- **Western Market (US/EU)**: `mnemoraorg/telco-churn-7k` (US), `muqsith123/telco-customer-churn` (Global/Regional), `talkmap/telecom-conversation-corpus` (200k support)
- **Reasoning & RCA**: `tecnicolaude/Telelogs-CoT`, `netop/TeleLogs`, `Agaba-Embedded4/Combined-Telecom-QnA`
- **Network Events & Alarms**: `electricsheepafrica/nigerian-telecom-network-event-logs`, `crystalou123/5G_Faults_Full`, `greenwich157/telco-5G-core-faults`, `GSMA/open_telco`
- **Customer Experience**: `electricsheepafrica/nigerian-telecom-customer-support-ticket-records`, `Hashiru11/support-tickets-telecommunication`, `Ming-secludy/telecom-customer-support-synthetic-replicas`, `Amjad123/telecom_conversations_1k`
- **Metrics & Performance**: `electricsheepafrica/nigerian-telecom-quality-of-service-metrics`, `AliMaatouk/TelecomTS`, `Genteki/tau2-bench-telecom-tiny`

## Phase 3: ANOps Wedge - MTTR Reduction
- [x] Implement anomaly detection on KPI streams
- [x] Build root cause analysis using graph reasoning
- [x] Create LLM-powered explanation layer
- [x] Design and build NOC engineer interface
- [x] Experiment with expanded ANOps use cases:
    - [x] Congestion Management (PRB Utilization vs Latency)
    - [x] Sleeping Cell Detection (Silent Failure)
    - [x] Voice & SMS Reliability (VoLTE CDR & SMSC Latency)
    - [x] Landline Emergency Services (911/999 Dial-out Failures)

## Phase 4: Foundational Hardening (Strategic Review)
- [x] **Data Strategy Implementation**:
    - [x] Deploy TimescaleDB container for "Hot" metric storage
    - [x] multi-database support in backend (Graph vs Metrics)
    - [x] Convert `kpi_metrics` to Hypertable
- [x] **Async Ingestion Pipeline**:
    - [x] Implement `kafka_producer.py` for simulation events
    - [x] Implement `kafka_consumer.py` & `event_handlers.py` (Decoupled Detection)
    - [x] Refactor `simulate_advanced_scenarios.py` to use producer
- [x] **Phase 1 Critical Fixes (Strategic Review Feedback)**:
    - [x] Fix Idempotency: Change `KPIMetricORM` to use natural primary key
    - [x] Set TimescaleDB Retention Policy (30 days)
    - [x] Enable TimescaleDB Native Compression
    - [x] Wire up actual RCA `diagnose()` in event handler

## Phase 5: Deepen the Intelligence (Strategic Review Phase 2)
- [x] **Causal AI (Granger Causality)**:
    - [x] Add `statsmodels` to `requirements.txt`
    - [x] Create `anops/causal_analysis.py` with `GrangerCausalityAnalyzer`
    - [x] Integrate causality check into RCA output ("High Latency *caused by* High Load")
    - [x] Update `LLMService` prompts to include causal evidence
- [x] **Operator Feedback Loop (RLHF)**:
    - [x] Add `feedback_score` column to `DecisionTraceORM` (Integer: 1=Up, -1=Down, 0=Neutral)
    - [x] Create API endpoints: `POST /decisions/{id}/upvote` and `/downvote`
    - [x] Modify similarity search to weight by feedback score
    - [ ] (Future) Re-rank LLM output based on successful past decisions

## Phase 6: Strategic Review Fixes (Phase 2 Hardening)
- [x] **Causal AI Hardening**:
    - [x] Increase minimum observations to 100 in `causal_analysis.py`
    - [x] Implement ADF test and differencing for stationarity
    - [x] Dynamically fetch candidate metrics for `entity_id`
- [x] **Feedback Reliability**:
    - [x] Create `DecisionFeedbackORM` (junction table for multi-operator voting)
    - [x] Update repository to aggregate feedback scores
    - [x] Fix RLHF boost logic to apply *after* threshold filtering

## Phase 7: Memory Optimization & Benchmarking
- [x] Establish "Gold Standard" test cases for search
- [x] Benchmark search parameters against gold standard
- [x] Fine-tune default `min_similarity` and `limit`
- [x] Implement automated parameter optimization tool

## Phase 8: Market Readiness (TMF Compliance & Integration)
- [x] **TMF642 Alarm Management API**:
    - [x] Create `tmf642_models.py` (Pydantic schema: Alarm, Severity, AlarmType enums)
    - [x] Add `ack_state`, `external_correlation_id`, `internal_correlation_id`, `probable_cause` to `DecisionTraceORM`
    - [x] Build `tmf642.py` API endpoints (GET/PATCH/POST /alarm)
    - [x] Register TMF642 router in `main.py`
    - [x] Implement OAuth2 scopes (`tmf642:alarm:write`, `tmf642:alarm:read`)
- [x] **TMF628 Performance Management API**:
    - [x] Create `tmf628_models.py` (PerformanceMeasurement, IndicatorSpec)
    - [x] Build `tmf628.py` API endpoints (GET /performanceMeasurement)
- [x] **Mock OSS Integration**:
    - [x] Create `alarm_normalizer.py` (vendor-agnostic alarm translation)
    - [x] Create `mock_ericsson_oss.py` (ENM-style alarm generator)
    - [x] Create `mock_nokia_netact.py` (NetAct-style alarm generator)
    - [x] Register alarm handler in `kafka_consumer.py`
- [x] **Documentation & Compliance**:
    - [x] Update `tmf642_mapping.md` (close all 3 compliance gaps)
    - [x] End-to-end demo: Vendor alarm → Kafka → Pipeline → TMF642 API

## Phase 9: Ruthless Executive Review (Committee Analysis)
- [ ] Ops Director Audit (Operational Readiness & Maintainability)
- [ ] CEO Audit (Business Value, ROI, & Brand)
- [ ] Strategist Audit (Market Fit & Future-Proofing)
- [ ] Enterprise Architect Audit (Scale, Security, & Integration)
- [ ] QA Director Audit (Resilience, Quality, & Chaos)
- [ ] **Final Verdict & Improvement Plan**:
    - [ ] Prioritize gaps
    - [ ] Propose remediations

## Phase 4: Operational Hardening (Execution)
- [x] **Observability & Resilience**:
    - [x] Implement structured JSON logging (`logging.py`) to replace `print()`
    - [x] Add Request ID middleware in `main.py`
    - [x] Implement Real Health Probes (Ready/Live) in `health.py`
    - [x] Add Circuit Breakers for external dependencies
- [x] **Testing & Quality Assurance**:
    - [x] Create `tests/conftest.py` (AsyncClient, DB fixtures)
    - [x] Implement Integration Tests for TMF642
    - [x] Implement Unit Tests for RCA Logic (Normalizer)
    - [x] Create Load Test script (`locustfile.py`)
- [x] **Deployment & Configuration**:
    - [x] Create Production `Dockerfile`
    - [x] Create `docker-compose.prod.yml`
    - [x] Enforce strict env var validation in `config.py`

## Phase 10: Executive Rework (Hardening v2)
- [x] **Security & Identity**:
    - [x] Implement JWT signature verification & RBAC roles
    - [x] Restrict CORS origins
    - [x] Secure production secrets
    - [x] Initialize Alembic for migrations
- [x] **Operational Resilience**:
    - [x] Implement LLM Vendor Abstraction & Cost Control
    - [x] Integrate OpenTelemetry for tracing
    - [x] Fix load test schema bug
- [x] **User Experience & Scalability**:
    - [x] Design and build NOC Dashboard (Next.js)
    - [x] Provide Kubernetes/Helm manifests

## Phase 11: Real Hardening & Dashboard Integration (Substance v2)
- [x] **Security & Identity [🔴 Criticals #1, #2, #3 & 🟡 High #8]**:
    - [x] [🔴 #1] Make `secret_key` mandatory (remove default)
    - [x] [🔴 #2] Externalize all DB credentials in `docker-compose.prod.yml` (Reworked in v3)
    - [x] [🔴 #3] Enable `db_ssl_mode` in config/connections (Reworked in v3)
    - [x] [🟡 #8] Implement `/token` endpoint and auth router
- [x] **NOC Dashboard Integration [🔴 Critical #4 & 🟡 High #9]**:
    - [x] [🔴 #4] Wire frontend to real TMF642 APIs (fetch alarms) (Reworked in v3: Added Auth Headers)
    - [x] [🟡 #9] Implement functional "Acknowledge" button logic (Reworked in v3: Added Auth Headers)
- [x] **Operational Resilience & QA [🔴 Criticals #5, #6 & 🟡 Highs #7, #11]**:
    - [x] [🔴 #5] Fix `conftest.py` test fixtures (User model regression)
    - [x] [🔴 #6] Install OpenTelemetry dependencies in `requirements.txt`
    - [x] [🟡 #7] Make `sampling_rate` configurable in `llm_service.py`
    - [x] [🟡 #11] Add token retrieval to Locust load test (Reworked in v3)
- [x] **Enterprise Scaling [🟡 High #10]**:
    - [x] [🟡 #10] Provide K8s manifests for Postgres and Kafka (Reworked in v3: Added Zookeeper & PVCs)
- [x] [R12] Fix Kafka K8s YAML Indentation (Audit v5 Final fix)

## Phase 12: Memory Optimization & Pilot Benchmarking
- [x] [🟡 #7.1] Establish "Gold Standard" test cases for Decision Memory
- [x] [🟡 #7.2] Benchmark search parameters against gold standard
- [x] [🟡 #7.3] Fine-tune default `min_similarity` and `limit`
- [x] [🟢 #7.4] Implement automated parameter optimization tool

## Phase 13: Wedge 2 - AI-Driven Capacity Planning
- [x] [🔴 #13.1] Design "Densification" schema (Investment Plan ORM)
- [x] [🟡 #13.2] Implement CapEx vs Coverage tradeoff engine
- [x] [🟢 #13.3] Build densification visualization in Dashboard

## Phase 14: Wedge 3 - Customer Experience Intelligence
- [x] [🔴 #14.1] Correlate Churn data with Anomaly context
- [x] [🟡 #14.2] Implement "Proactive Care" automation (email/SMS trigger)

## Phase 15: Strategic Pivot (Pedkai v2.0 - AI Control Plane)
- [x] [🔴 #15.1] Implement **BSS Data Layer** (Revenue & Billing Context)
- [x] [🔴 #15.2] Develop **Policy Engine** (Declarative "Telco Constitution")
- [x] [🟡 #15.3] Upgrade to **Semantic Context Graph** (Recursive Reasoning)
- [x] [🟡 #15.4] Implement **Closed-Loop RL Evaluator**
