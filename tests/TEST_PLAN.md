# Pedkai Phase 1 & 2 — Comprehensive Test Plan

**Authors:** Telecom Ops Director & QA Director
**Date:** 2026-02-09
**Scope:** All components delivered in Phase 1 (Foundation) and Phase 2 (Intelligence Hardening)

---

## 1. Test Philosophy

> *"In a live NOC at 3 AM, there is no 'pretty close'. Either the SITREP is trustworthy or it's dangerous."*
> — Telecom Ops Director

This test plan is designed to break the system, not to confirm it works. We test the **unhappy paths** that real networks produce every day: noisy baselines, flapping alarms, multi-vendor clock drift, and operators who click "upvote" 50 times.

---

## 2. Test Data Strategy

### 2.1 Real-World Data Sources (Priority)

> **⚠️ Data Alignment Note (Strategic Review Gap #5):** Kaggle datasets contain **client-side measurements** (RSRP, RSRQ from phones), while Pedkai expects **network-side KPIs** (PRB utilization, cell throughput, CPU load). A **data transformation layer** in `tests/conftest.py` will map compatible fields and document limitations.

| Source | Format | What it gives us | Use Case |
|--------|--------|-------------------|----------|
| **Kaggle: 4G LTE Speed Dataset** (Zenodo/G-NetTrack) | CSV | RSRP, RSRQ, SNR, CQI, throughput, cell tower GPS | Anomaly Detection, Causal AI (real correlations between RF & throughput) |
| **Kaggle: 5G Network Performance** | CSV | Signal strength, speed, latency, jitter, environmental data | End-to-end pipeline stress test with realistic distributions |
| **Kaggle: Cellular Network Analysis** (Bihar, India) | CSV | Multi-technology (3G/4G/5G), signal strength, throughput, latency across 20 sites | Multi-entity topology test, cross-technology anomaly patterns |
| **FCC Cellular Tower Dataset** | CSV/GeoJSON | Real tower locations, operator data | Topology graph validation, realistic entity IDs |

**Data Transformation Mapping:**

| Kaggle Field | Maps To Pedkai Metric | Notes |
|---|---|---|
| `Data Throughput (Mbps)` | `throughput_mbps` | Direct mapping |
| `Latency (ms)` | `latency_ms` | Direct mapping |
| `Signal Strength (dBm)` | `rsrp_dbm` | New metric for validation only |

### 2.2 Synthetic Data Strategy

For scenarios that real-world data cannot provide (e.g., controlled Granger causality, known SLA breaches):

| Scenario | Generator | Parameters |
|----------|-----------|------------|
| **Baseline + Anomaly Injection** | `tests/generators/kpi_generator.py` | Configurable mean, std, anomaly magnitude, injection point |
| **Known Causal Pair** | `tests/generators/causal_pair_generator.py` | X(t) → Y(t+lag) with configurable lag, noise, and non-stationarity |
| **Multi-Operator Feedback** | `tests/generators/feedback_generator.py` | N operators, vote distribution, gaming patterns |
| **Full Topology** | Enhanced `seed_topology.py` | Variable depth (1-5 hops), mixed entity types |

### 2.3 Data Loading Script

```python
# tests/conftest.py - shared fixtures
# Downloads Kaggle datasets if not cached, loads into TimescaleDB
# Falls back to synthetic generators if offline
```

---

## 3. Numbered Test Cases

### Layer 0: Message Bus (Kafka) — **Strategic Review Gap #1**

| ID | Test Case | Type | Priority | Data Source |
|----|-----------|------|----------|-------------|
| **TC-100** | Kafka consumer connects successfully and subscribes to `pedkai.metrics` topic | Integration | P0 | Kafka testcontainer |
| **TC-101** | Duplicate message (same metric, same timestamp) is idempotent (stored once) | Integration | P0 | Synthetic duplicate events |
| **TC-102** | Out-of-order messages (T=10 arrives before T=5) are handled correctly | Integration | P0 | Synthetic out-of-order stream |
| **TC-103** | Kafka consumer failure → System retries connection with exponential backoff | Robustness | P0 | Kill Kafka mid-test |
| **TC-104** | Consumer restart resumes from last committed offset (no duplicate processing) | Integration | P1 | Restart consumer process |
| **TC-105** | Kafka backpressure: 10,000 queued events drain at ≥ 100 events/sec | Performance | P1 | Synthetic burst to Kafka |
| **TC-106** | Malformed JSON in Kafka message is logged and skipped (not crash) | Robustness | P0 | Invalid JSON payload |
| **TC-107** | Kafka topic does not exist → Consumer creates topic or fails gracefully | Integration | P1 | Empty Kafka cluster |

---

### Layer 1: Data Ingestion & Storage (TimescaleDB)

| ID | Test Case | Type | Priority | Data Source |
|----|-----------|------|----------|-------------|
| **TC-001** | KPI metric is persisted with correct tenant_id, entity_id, metric_name, value, timestamp | Unit | P0 | Synthetic |
| **TC-002** | Duplicate metric (same PK) is silently ignored via `on_conflict_do_nothing` | Unit | P0 | Synthetic |
| **TC-003** | Bulk insert of 10,000 metrics completes in < 5 seconds | Performance | P1 | Kaggle 5G dataset |
| **TC-004** | Hypertable compression activates after 7-day threshold | Integration | P2 | Synthetic (backdated) |
| **TC-005** | 30-day retention policy deletes metrics older than 30 days | Integration | P1 | Synthetic (backdated 45 days) |
| **TC-006** | Metrics with NULL or NaN values are rejected gracefully | Unit | P0 | Synthetic |
| **TC-007** | Concurrent writes from 10 "entities" do not deadlock | Stress | P1 | Synthetic (parallel async) |
| **TC-008** | Idempotent schema migration: `init_database()` can be run twice without errors | Integration | P0 | Run init twice |
| **TC-009** | Additive migration: Phase 1 schema + Phase 2 `decision_feedback` table coexist | Integration | P0 | Staged migration |

---

### Layer 2: Context Graph (Topology)

| ID | Test Case | Type | Priority | Data Source |
|----|-----------|------|----------|-------------|
| **TC-010** | Seed topology creates gNodeB → Cell → Customer → SLA chain | Integration | P0 | `seed_topology.py` |
| **TC-011** | `get_entity_by_external_id` returns correct entity for known ID | Unit | P0 | Seeded topology |
| **TC-012** | `get_entity_by_external_id` returns None for unknown ID | Unit | P0 | Seeded topology |
| **TC-013** | `get_relationships` returns both upstream and downstream for Cell entity | Unit | P0 | Seeded topology |
| **TC-014** | `analyze_incident("CELL_LON_001")` returns gNodeB upstream, Customer downstream, SLA in critical_slas | Integration | P0 | Seeded topology |
| **TC-015** | `analyze_incident` for entity with no relationships returns empty lists (not error) | Unit | P1 | Isolated entity |
| **TC-016** | Multi-tenant isolation: tenant_A cannot see tenant_B's entities | Security | P0 | Two seeded tenants |
| **TC-017** | Deep graph (5-hop chain: Site → gNodeB → Cell → Customer → SLA) resolves SLA correctly | Integration | P1 | Extended topology |
| **TC-018** | Circular dependency (A → B → A) does not cause infinite loop in RCA | Robustness | P0 | Synthetic circular graph |

---

### Layer 3: Anomaly Detection

| ID | Test Case | Type | Priority | Data Source |
|----|-----------|------|----------|-------------|
| **TC-020** | Z-score correctly flags value > 3σ from mean as anomaly | Unit | P0 | Synthetic (mean=50, std=5, inject 85) |
| **TC-021** | Z-score does NOT flag value within 2σ as anomaly | Unit | P0 | Synthetic (mean=50, std=5, inject 55) |
| **TC-022** | Baseline cache returns cached value within TTL | Unit | P0 | Synthetic |
| **TC-023** | Baseline cache refreshes after TTL expiry | Unit | P1 | Synthetic (mock time) |
| **TC-024** | New entity with < 5 data points returns `is_anomaly=False` (not crash) | Unit | P0 | Synthetic (3 points) |
| **TC-025** | Entity with constant value (std=0) handles gracefully | Edge | P1 | Synthetic (all values = 42.0) |
| **TC-026** | Real-world LTE throughput data produces reasonable anomaly rate (< 5%) | Validation | P1 | Kaggle 4G LTE dataset |
| **TC-027** | Rapid metric ingestion (100 values/sec for one entity) does not corrupt baseline | Stress | P1 | Synthetic burst |
| **TC-028** | Process_metric stores the new value AND checks for anomaly in single call | Unit | P0 | Synthetic |
| **TC-029** | Anomaly detection works with negative values (e.g., RSRP in dBm: -120 to -60) | Unit | P1 | Kaggle Cellular Network data |
| **TC-027a** | Baseline cache isolation: Two tenants using same `AnomalyDetector` class produce isolated baselines | Security | P0 | Two tenants, shared detector instance |

---

### Layer 4: Causal AI (Granger Causality — Hardened)

| ID | Test Case | Type | Priority | Data Source |
|----|-----------|------|----------|-------------|
| **TC-030** | Series with < 100 points returns `causes=False` with "Insufficient statistical power" error | Unit | P0 | Synthetic (50 points) |
| **TC-031** | Series with exactly 100 points proceeds to Granger test | Unit | P0 | Synthetic (100 points) |
| **TC-032** | Known causal pair (X → Y with lag=2) is detected with p < 0.05 | Unit | P0 | Synthetic causal pair |
| **TC-033** | Non-causal pair (two independent random walks) is NOT flagged as causal | Unit | P0 | Synthetic independent series |
| **TC-034** | Non-stationary trended series triggers ADF differencing | Unit | P0 | Synthetic (linear trend + noise) |
| **TC-035** | After differencing, `stationarity_fixed=True` is returned in result | Unit | P1 | Synthetic trended series |
| **TC-036** | Two non-stationary but spuriously correlated trends are NOT flagged as causal after ADF | Unit | P0 | Synthetic (two independent trends) |
| **TC-037** | Constant series (std=0) does not crash ADF or Granger | Edge | P1 | Synthetic (all values = 5.0) |
| **TC-038** | `get_available_metrics` returns all distinct metric names for entity | Unit | P0 | Multi-metric synthetic entity |
| **TC-039** | `get_available_metrics` returns empty list for unknown entity | Unit | P1 | No data seeded |
| **TC-040** | `find_causes_for_anomaly` skips self-causation (metric != itself) | Unit | P0 | Synthetic 3-metric entity |
| **TC-041** | `find_causes_for_anomaly` results are sorted by ascending p-value | Unit | P1 | Multiple causal pairs |
| **TC-042** | Real-world LTE data: RSRP changes Granger-cause throughput changes | Validation | P2 | Kaggle 4G LTE dataset |
| **TC-043** | Large entity with 20+ metrics does not timeout (< 30 sec) | Performance | P1 | Synthetic 20-metric entity |
| **TC-044** | Granger test with `max_lag > len(series)/3` handles gracefully | Edge | P2 | Synthetic short series |
| **TC-045** | Seasonal false positive: Two independent metrics with 24-hour sine wave cycles are NOT flagged as causal | Unit | P0 | Synthetic seasonal pair |

---

### Layer 5: Decision Memory & RLHF

| ID | Test Case | Type | Priority | Data Source |
|----|-----------|------|----------|-------------|
| **TC-050** | Create decision trace and retrieve by ID | Unit | P0 | Synthetic |
| **TC-051** | `find_similar` returns decisions above `min_similarity` threshold | Unit | P0 | Seeded golden decisions |
| **TC-052** | `find_similar` does NOT return decisions below threshold even if upvoted | Unit | P0 | Low-similarity + high feedback |
| **TC-053** | Upvoted decision is ranked higher than neutral decision at same raw similarity | Unit | P0 | Two decisions, same embedding distance |
| **TC-054** | Downvoted decision is ranked lower than neutral decision | Unit | P0 | Symmetric to TC-053 |
| **TC-055** | `record_feedback` creates entry in `decision_feedback` junction table | Unit | P0 | Synthetic |
| **TC-056** | Same operator voting twice on same decision UPDATES (not duplicates) | Unit | P0 | Upsert test |
| **TC-057** | Two different operators can both vote on same decision | Unit | P0 | Multi-operator test |
| **TC-058** | Aggregate `feedback_score` on `DecisionTraceORM` equals sum of votes | Unit | P0 | 3 upvotes + 1 downvote = 2 |
| **TC-059** | 50 operators all upvoting does not produce unbounded boost (score capped by design?) | Stress | P1 | 50 synthetic operators |
| **TC-059a** | Feedback boost is mathematically bounded: adjusted_similarity ≤ raw_similarity + 0.2 (max boost cap) | Unit | P0 | High vote count scenarios |
| **TC-060** | `record_feedback` for non-existent decision_id returns False | Unit | P0 | Random UUID |
| **TC-061** | Multi-tenant: Tenant A's feedback does not affect Tenant B's similarity search | Security | P1 | Two tenants |
| **TC-062** | Embedding service generates consistent embedding for same text | Unit | P1 | Fixed string |
| **TC-063** | Decision without embedding is excluded from `find_similar` results | Unit | P0 | Decision with `embedding=None` |
| **TC-064** | Round-trip serialization: ORM → Pydantic → ORM preserves all JSONB fields | Unit | P1 | Decision with complex context |

---

### Layer 6: Intelligence (LLM SITREP Generation)

| ID | Test Case | Type | Priority | Data Source |
|----|-----------|------|----------|-------------|
| **TC-070** | SITREP contains all 5 required sections (Executive Summary, Root Cause, Impact, Action, Rationale) | Contract | P0 | Mocked RCA + causal evidence |
| **TC-071** | When causal_evidence is provided, SITREP uses causal language ("caused", not "correlated") | Contract | P0 | Mocked causal evidence |
| **TC-072** | When causal_evidence is empty, SITREP does NOT fabricate causal claims | Contract | P0 | Empty causal_evidence |
| **TC-073** | When similar_decisions is empty, SITREP states "no similar past decisions" | Contract | P1 | Empty decision list |
| **TC-074** | LLM service without API key returns graceful error message | Unit | P0 | No `GEMINI_API_KEY` |
| **TC-075** | SITREP includes SLA entity names from RCA impact assessment | Contract | P1 | RCA with SLA data |
| **TC-076** | LLM API timeout/failure returns error message, not crash | Robustness | P0 | Mocked API failure |

---

### Layer 7: End-to-End Pipeline (Event Handler)

| ID | Test Case | Type | Priority | Data Source |
|----|-----------|------|----------|-------------|
| **TC-080** | Normal metrics → No anomaly → No RCA triggered → Quick return | E2E | P0 | Baseline values |
| **TC-081** | Anomaly metric → RCA → Causal AI → SITREP generated | E2E | P0 | Anomaly injection |
| **TC-082** | Multiple anomalies in one event → All are investigated | E2E | P1 | Multi-metric anomaly |
| **TC-083** | Anomaly on unknown entity (not in graph) → RCA returns "not found", pipeline continues | E2E | P0 | Unknown entity_id |
| **TC-084** | Full pipeline with real Kaggle data: ingest → detect → RCA → SITREP | E2E | P2 | Kaggle 5G dataset |
| **TC-085** | Pipeline handles `entity_id=None` gracefully | Robustness | P1 | Malformed event |
| **TC-086** | Pipeline handles empty `metrics={}` gracefully | Robustness | P1 | Empty payload |
| **TC-087** | Alarm storm: 50 entities trigger anomalies within 10 seconds → No deadlocks, no duplicate SITREPs, total latency < 120s | Stress | P0 | Synthetic alarm storm |
| **TC-088** | End-to-end latency budget: Metric ingestion → SITREP delivery completes in < 30 seconds (95th percentile) | Performance | P0 | Timed E2E test |

---

### Layer 8: API Endpoints

| ID | Test Case | Type | Priority | Data Source |
|----|-----------|------|----------|-------------|
| **TC-090** | `POST /decisions` creates and returns decision with 201 | API | P0 | Valid payload |
| **TC-091** | `GET /decisions/{id}` returns correct decision | API | P0 | Created decision |
| **TC-092** | `GET /decisions/{id}` with invalid UUID returns 404 | API | P0 | Random UUID |
| **TC-093** | `POST /decisions/{id}/upvote` returns 200 and updates score | API | P0 | Existing decision |
| **TC-094** | `POST /decisions/{id}/downvote` returns 200 and updates score | API | P0 | Existing decision |
| **TC-095** | `POST /decisions/{id}/upvote` with invalid ID returns 404 | API | P0 | Random UUID |
| **TC-096** | `POST /similar` returns decisions ranked by feedback-adjusted similarity | API | P1 | Seeded decisions |

---

## 4. Automation Plan

### 4.1 Framework & Tooling

| Tool | Purpose |
|------|---------|
| **pytest** + **pytest-asyncio** | Test runner for async Python |
| **httpx** (AsyncClient) | API endpoint testing |
| **testcontainers-python** | Spin up PostgreSQL + TimescaleDB + Kafka in Docker per test session |
| **factory_boy** | Generate ORM fixtures (DecisionTraceORM, KPIMetricORM) |
| **unittest.mock** / **pytest-mock** | Mock LLM and Embedding API calls |
| **numpy** | Synthetic data generation |
| **pandas** | Load and clean Kaggle CSV datasets |

### 4.2 Test Directory Structure

```
tests/
├── conftest.py                  # DB fixtures, session scope, data loaders, Kaggle transform layer
├── generators/
│   ├── kpi_generator.py         # Synthetic KPI time-series
│   ├── causal_pair_generator.py # Known-causal and non-causal pair generators
│   ├── feedback_generator.py    # Multi-operator vote patterns
│   └── alarm_storm_generator.py # Multi-entity concurrent anomaly injection
├── data/
│   └── README.md                # Instructions to download Kaggle datasets
├── unit/
│   ├── test_kafka_consumer.py      # TC-100 to TC-107
│   ├── test_anomaly_detection.py   # TC-020 to TC-029, TC-027a
│   ├── test_causal_analysis.py     # TC-030 to TC-045
│   ├── test_decision_repository.py # TC-050 to TC-064
│   ├── test_rca.py                 # TC-010 to TC-018
│   └── test_llm_service.py         # TC-070 to TC-076
├── integration/
│   ├── test_data_ingestion.py      # TC-001 to TC-009
│   └── test_event_pipeline.py      # TC-080 to TC-088
├── api/
│   └── test_decisions_api.py       # TC-090 to TC-096
└── validation/
    └── test_real_world_data.py     # TC-026, TC-042, TC-084
```

### 4.3 Execution Commands

```bash
# Full suite (requires Docker for testcontainers)
pytest tests/ -v --tb=short

# Unit tests only (no external deps)
pytest tests/unit/ -v

# Real-world validation (requires downloaded Kaggle data)
pytest tests/validation/ -v -m "realworld"

# Performance tests
pytest tests/ -v -m "performance" --timeout=60

# Coverage report
pytest tests/ --cov=anops --cov=backend --cov-report=html
```

### 4.4 CI/CD Integration

```yaml
# .github/workflows/test.yml
name: Pedkai Test Suite
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: timescale/timescaledb:2.13.0-pg16  # Pinned version (Strategic Review Gap #6)
        env:
          POSTGRES_PASSWORD: test
        ports: ['5432:5432']
    steps:
      - uses: actions/checkout@v4
      - run: pip install -r requirements.txt -r requirements-test.txt
      - run: pytest tests/unit/ tests/integration/ -v --tb=short
```

---

## 5. Risk Matrix

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Kaggle data format changes | Medium | Low | Pin dataset version, validate schema on load |
| LLM output format drift (Gemini updates) | High | Medium | Contract tests (TC-070..076) with regex/keyword assertions |
| TimescaleDB version incompatibility | Low | High | Pin Docker image version in `docker-compose.yml` |
| Granger test false positives in prod | Medium | High | TC-033, TC-036 validate false positive rate |
| Feedback score grows unbounded | Low | **High** | **TC-059a REQUIRES bounded boost implementation** (max +0.2 adjustment) |

---

## 6. Acceptance Criteria

Phase 1 & 2 are considered **field-trial ready** when:

1. **All P0 tests pass** (0 failures)
2. **P1 tests: ≥ 95% pass rate**
3. **No crashes** on any edge case (TC-006, TC-025, TC-037, TC-083, TC-085, TC-086)
4. **Bulk ingestion** completes 10k metrics in < 5 seconds (TC-003)
5. **Causal AI false positive rate** < 5% on synthetic independent data (TC-033, TC-045)
6. **Multi-tenant isolation** confirmed (TC-016, TC-061, TC-027a)
7. **SITREP contract** met on 100% of LLM responses (TC-070..TC-072)
8. **Latency SLA (Strategic Review Gap #3):** 95th percentile end-to-end latency < 30 seconds (TC-088)
9. **Alarm storm resilience:** 50 concurrent anomalies processed without deadlock in < 120s (TC-087)
10. **Kafka resilience:** Consumer survives connection failures and restarts (TC-103, TC-104)
11. **Feedback boost bounded:** Adjusted similarity never exceeds raw + 0.2 (TC-059a)
