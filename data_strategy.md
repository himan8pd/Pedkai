# Pedkai Data Strategy (Scalability Layer)

To handle the 500k+ events/second expected in a Tier-1 telco, Pedkai uses a tiered storage architecture.

## 1. Storage Tiers

| Tier | Purpose | Technology | Retention |
| :--- | :--- | :--- | :--- |
| **Hot** | Anomaly Detection, Real-time Dashboard | Redis / In-memory Buffer / TimescaleDB Hypertable | 24 - 48 Hours |
| **Warm** | Root Cause Analysis (RCA), Graph Traversal | PostgreSQL (with JSONB + pgvector) | 30 - 90 Days |
| **Cold** | Model Training, Historic Audit, Compliance | S3 / Parquet / Apache Iceberg | 1 - 7 Years |

## 4. External Intelligence Integration (Business Shielding)

To move from "Network RCA" to "Business Shielding", Pedkai requires real-time integration with external IT and Business systems:

### A. CMDB / ServiceNow (Change Intel)
- **Objective**: Correlate network drift with human-initiated maintenance.
- **Data Points**: Change ID, Target CI (Configuration Item), Start/End Time, Risk Score.
- **Pattern**: Pedkai's Policy Engine automatically reverts changes (via Netconf) if "Cognitive Fingerprint" drift is detected within T+30m of a Change window.

### B. BSS / Billing Engine (Financial Throughput)
- **Objective**: Quantify "Business Vitality" and prioritize autonomous actions.
- **Data Points**: Customer SLA Tier (Gold/Silver/Bronze), Monthly Recurring Revenue (MRR), Penalty per Minute.
- **Pattern**: Nodes in the Context Graph are weighted by the sum of MRR flowing through them. Pedkai prioritizes "Gold-tier" intercepts.

### C. Digital Twin (Predictive Simulation)
- **Objective**: Predict drift before it breaches SLA thresholds.
- **Mechanism**: GRU/LSTM models trained on "Cold" tier data predict metric trajectories 15 minutes into the future.

## 2. In-Memory "Hot Path" Optimization

Instead of querying Postgres for every metric check, the `AnomalyDetector` will now implement a **Baseline Cache**.

- **Mechanism**: The Mean and Standard Deviation for a Metric/Entity pair are cached in memory (or Redis).
- **Update Frequency**: Baselines are recalculated from the "Warm" tier (Postgres) once every hour (or whenever significant drift is detected).
- **Execution**: The incoming metric is compared against the *cached* baseline, reducing DB read IOPS by 99%.

## 3. Migration Roadmap to TSDB

Currently, metrics are stored in `KPIMetricORM` (Postgres). For Phase 2, we recommend:
1.  **Introduce TimescaleDB**: Convert the `kpi_metrics` table into a Hypertable. This allows automatic partitioning and compression.
2.  **Schema-less Ingestion**: Use a dedicated TSDB (like InfluxDB or Prometheus) for raw metric storage, keeping only "Aggregated Wisdom" in Postgres.
