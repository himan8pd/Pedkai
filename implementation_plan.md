# Pedkai: AI-Native Telco Operating System — Implementation Plan

## Overview

**Pedkai** is an AI-native control plane that sits above legacy BSS/OSS, networks, IT, and operations to provide **decision intelligence** and **automation** for large-scale telcos (Vodafone/Jio/Verizon scale).

This plan covers the initial phases to build a working MVP for the **ANOps (Autonomous Network Operations)** wedge with a focus on **MTTR reduction**.

---

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **Primary Use Case** | ANOps → MTTR Reduction | Highest ROI, data-rich, measurable |
| **Deployment Model** | Cloud-hosted SaaS, multi-tenant | Scale, isolation, easier updates |
| **Data Strategy** | Public datasets + synthetic + proprietary | Bootstrap development while awaiting real data |

---

## Context Graph: Decision Memory (Not a Graph Database)

> [!IMPORTANT]
> Based on your clarification, the **Context Graph** in Pedkai is a *behavioral layer* — not a Neo4j-style graph database.

### What is a Context Graph?

Inspired by [Jaya Gupta's work on Decision Traces](https://www.linkedin.com/pulse/where-context-graphs-materialize-jaya-gupta-lsqoe):

| Traditional Systems | Context Graph (Decision Memory) |
|---------------------|--------------------------------|
| Store **what** happened | Store **why** the decision was made |
| Record events and state | Record evidence, constraints, tradeoffs, outcomes |
| Schema of nouns (devices, alarms) | Schema of **decisions** with reasoning chains |
| Can replay history | Can **learn from** history and apply patterns |

### Why Telco is Ideal for This

Telcos are **ontologically stable** — the nouns are durable:
- A cell site is a cell site
- An alarm is an alarm
- A ticket is a ticket

This stability means Pedkai can invest in modeling decisions without the schema breaking every quarter. The missing layer in telco is not *what* exists, but *why* one valid option worked and another quietly failed.

### Decision Trace Structure

Each decision captured by Pedkai includes:

```
┌─────────────────────────────────────────────────────────────┐
│                     DECISION TRACE                          │
├─────────────────────────────────────────────────────────────┤
│  decision_id: "dt-2024-0208-001"                            │
│  timestamp: "2024-02-08T14:30:00Z"                          │
│  context:                                                   │
│    - alarm_ids: [A1, A2, A3]                                │
│    - kpi_snapshot: {throughput: 45Mbps, latency: 23ms}      │
│    - related_tickets: [TKT-5532]                            │
│  constraints_binding:                                       │
│    - SLA: Enterprise customer, 99.99% uptime                │
│    - Maintenance window: None available for 48hrs           │
│  options_considered:                                        │
│    - Option A: Restart baseband unit (risk: 5min outage)    │
│    - Option B: Failover to adjacent cell (risk: capacity)   │
│    - Option C: Escalate to vendor (risk: 4hr response)      │
│  tradeoff_made: "Chose Option B because..."                 │
│  action_taken: "Executed failover to Cell-XYZ"              │
│  outcome:                                                   │
│    - resolution_time: 12 minutes                            │
│    - customer_impact: 0 complaints                          │
│    - success: true                                          │
│  learnings: "Failover effective when adjacent has <70% load"│
└─────────────────────────────────────────────────────────────┘
```

### Storage: Standard Databases, Not Graph DB

Since Context Graph is about capturing **decision traces** (structured records), we can use:

| Component | Technology | Purpose |
|-----------|------------|---------|
| **Decision Store** | PostgreSQL + JSONB | Store decision traces with flexible schema |
| **Time-Series** | TimescaleDB | KPI snapshots, metrics history |
| **Search/Retrieval** | pgvector or Elasticsearch | Semantic search for similar past decisions |
| **Event Stream** | Kafka | Real-time decision capture |

- **Multi-Tenant with Global Escape**: Decision memory is isolated by tenant for security, but supports a "global" view for the Pedkai Operator.
- **Tunable Strategy**: All search parameters (similarity, limit, scope) are externalized to environment variables.
- **Benchmarking Phase**: A future phase is dedicated to establishing "Gold Standard" defaults based on objective outcome testing.

> [!TIP]
> This avoids introducing Neo4j or TigerGraph — your clients can use familiar Postgres.

---

## Revised Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│                           PEDKAI CONTROL PLANE                           │
├──────────────────────────────────────────────────────────────────────────┤
│  Layer 5: Automation & Actuation                                         │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐        │
│  │ Ticket API  │ │ Config API  │ │ Vendor APIs │ │ Human Loop  │        │
│  └─────────────┘ └─────────────┘ └─────────────┘ └─────────────┘        │
├──────────────────────────────────────────────────────────────────────────┤
│  Layer 4: Decision & Policy Engine (Pedkai's Moat)                       │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │ Risk-aware recommendations │ Explainability │ Policy constraints │    │
│  │ ─────────────────────────────────────────────────────────────── │    │
│  │ Decision Trace Capture │ Pattern Matching │ Outcome Learning    │    │
│  └─────────────────────────────────────────────────────────────────┘    │
├──────────────────────────────────────────────────────────────────────────┤
│  Layer 3: Intelligence Engines                                           │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐           │
│  │ Anomaly    │ │ Root Cause │ │ LLM        │ │ Decision   │           │
│  │ Detection  │ │ Analysis   │ │ Reasoning  │ │ Similarity │           │
│  └────────────┘ └────────────┘ └────────────┘ └────────────┘           │
├──────────────────────────────────────────────────────────────────────────┤
│  Layer 2: Context Graph (Decision Memory)                                │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │ Decision Traces │ Evidence Snapshots │ Constraint History       │    │
│  │ Outcome Records │ Learning Patterns  │ Exception Handling       │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│  Storage: PostgreSQL + JSONB │ TimescaleDB │ pgvector                   │
├──────────────────────────────────────────────────────────────────────────┤
│  Layer 1: Data & Signal Fabric                                           │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐           │
│  │ Streaming  │ │ Event      │ │ Historical │ │ External   │           │
│  │ Telemetry  │ │ Ingestion  │ │ Data Lake  │ │ Feeds      │           │
│  └────────────┘ └────────────┘ └────────────┘ └────────────┘           │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## Technology Stack (Simplified)

| Component | Technology | Rationale |
|-----------|------------|-----------|
| **Backend API** | Python (FastAPI) | ML ecosystem, rapid development |
| **Decision Store** | PostgreSQL + JSONB | Flexible, familiar, no new DB type |
| **Time-Series** | TimescaleDB (Postgres extension) | Same database, KPI storage |
| **Vector Search** | pgvector | Semantic similarity for past decisions |
| **Streaming** | Apache Kafka | Industry standard for telemetry |
| **ML/AI** | PyTorch, scikit-learn | Anomaly detection, pattern recognition |
| **LLM** | Gemini API | Explanation layer, reasoning |
| **Frontend** | Next.js | Modern SaaS UI |
| **Cloud** | GCP or AWS | Multi-tenant SaaS |

---

## Available Datasets

| Category | Dataset | Source | Purpose |
|----------|---------|--------|---------|
| **Decision Memory** | `tecnicolaude/Telelogs-CoT` | Hugging Face | **Primary**: Reasoning traces for 5G RCA |
| **ANOps Faults** | `greenwich157/telco-5G-core-faults` | Hugging Face | Core network failure events |
| **ANOps Faults** | `crystalou123/5G_Faults_Full` | Hugging Face | 5G Network alarms and status |
| **In-Service Logs**| `electricsheepafrica/nigerian-telecom-network-event-logs` | Hugging Face | Real network event logs |
| **Support Actions**| `electricsheepafrica/nigerian-telecom-customer-support-ticket-records` | Hugging Face | Closing the loop on "Action Taken" |
| **Performance** | `AliMaatouk/TelecomTS` | Hugging Face | Time-series for KPI anomaly detection |
| **Performance** | `electricsheepafrica/nigerian-telecom-quality-of-service-metrics` | Hugging Face | QoS monitoring snapshots |

---

## Proposed Changes

### Phase 1: Foundation & Data Fabric

#### [NEW] `/Pedkai/backend/` — Core API Service
- FastAPI skeleton with multi-tenant auth
- Decision trace CRUD endpoints
- Query APIs for similar past decisions

#### [NEW] `/Pedkai/decision_memory/` — Context Graph Implementation
- Decision trace schema (Pydantic models)
- PostgreSQL + JSONB storage layer
- pgvector integration for semantic search
- Pattern extraction from historical decisions

#### [NEW] `/Pedkai/data_fabric/` — Ingestion Layer
- Kafka consumers for real-time events
- [NEW] `kaggle_loader.py`: Specialized loader for Kaggle CSV datasets
- [MODIFY] `seed_database.py`: Enhanced CLI with Kaggle regional support
- ETL pipelines for public datasets (Hugging Face + Kaggle)

### Phase 2: ANOps MVP - MTTR Reduction

#### [NEW] `/Pedkai/anops/` — MTTR Reduction Logic
- Alarm correlation with decision context
- "Have we seen this before?" pattern matching
- Recommended actions from past successful decisions
- Outcome tracking loop
- **Expanding ANOps Logic (New Use Cases)**:
    - **Congestion Management**: Correlating `prb_utilization` with `latency` to trigger capacity offload.
    - **Sleeping Cell Detection**: Identifying "silent failures" where stats drop to zero without hardware alarms.
    - **Voice/SMS Reliability**: Monitoring Call Drop Rate (CDR) and SMSC queue depths to identify core signaling or delivery issues.
    - **Emergency Compliance**: Detecting Landline exchange congestion that blocks emergency (999/911) dial-outs.

### Phase 15: Strategic Pivot (AI Control Plane)

#### [NEW] `/Pedkai/backend/app/models/bss_orm.py` — BSS Data Layer
- Service Plan and Billing Account models for revenue tracking.
- Integration with external billing identifiers.

#### [NEW] `/Pedkai/backend/app/services/bss_service.py` — Revenue Logic
- Real-time "Revenue at Risk" calculation for anomalies.
- Customer tier resolution for policy enforcement.

#### [NEW] `/Pedkai/backend/app/services/policy_engine.py` — Declarative Control
- YAML-based policy enforcement ("Telco Constitution").
- Logic for prioritizing Gold/Corporate traffic and protecting high-revenue sites.

---

## Verification Plan

### Automated Tests
```bash
pytest tests/ -v  # Unit + integration tests
```
- Decision trace storage and retrieval
- Semantic similarity search accuracy
- Multi-tenant isolation
- `python3 -m data_fabric.seed_database --kaggle shivan118/telecom-churn-dataset --limit 50`

### Manual Verification
1. Inject alarm → verify system finds similar past decisions
2. Simulate decision → verify trace is captured correctly
3. Query "why did we do X last time?" → verify LLM explanation
- Verify that the new Indian/UK/Ireland records are searchable via the `/search` endpoint.

---

## User Review Required

> [!IMPORTANT]
> Please confirm before proceeding:

1. **Tech Stack**: Python/FastAPI + PostgreSQL (JSONB + pgvector) + Kafka + Next.js — acceptable?

2. **Cloud Provider**: GCP vs AWS vs Azure?

3. **Starting Point**:
   - (A) Project scaffolding + decision trace schema
   - (B) Explore public datasets first
   - (C) Design decision trace schema in detail

4. **LLM**: Gemini API for reasoning?

5. **Timeline**: 12-16 weeks for ANOps MVP reasonable?

---

## Next Steps (Upon Approval)

1. Create project directory structure
2. Design decision trace Pydantic schema
3. Set up PostgreSQL with JSONB + pgvector
4. Build decision capture and query APIs
5. Load sample alarm data and create synthetic decision traces
