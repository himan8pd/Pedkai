# Pedkai Data Strategy (Scalability Layer)

To handle the 500k+ events/second expected in a Tier-1 telco, Pedkai uses a tiered storage architecture.

## 1. Storage Tiers

| Tier | Purpose | Technology | Retention |
| :--- | :--- | :--- | :--- |
| **Hot** | Anomaly Detection, Real-time Dashboard | Redis / In-memory Buffer / TimescaleDB Hypertable | 24 - 48 Hours |
| **Warm** | Root Cause Analysis (RCA), Graph Traversal | PostgreSQL (with JSONB + pgvector) | 30 - 90 Days |
| **Cold** | Model Training, Historic Audit, Compliance | S3 / Parquet / Apache Iceberg | 1 - 7 Years |

## 2. In-Memory "Hot Path" Optimization

Instead of querying Postgres for every metric check, the `AnomalyDetector` will now implement a **Baseline Cache**.

- **Mechanism**: The Mean and Standard Deviation for a Metric/Entity pair are cached in memory (or Redis).
- **Update Frequency**: Baselines are recalculated from the "Warm" tier (Postgres) once every hour (or whenever significant drift is detected).
- **Execution**: The incoming metric is compared against the *cached* baseline, reducing DB read IOPS by 99%.

## 3. Migration Roadmap to TSDB

Currently, metrics are stored in `KPIMetricORM` (Postgres). For Phase 2, we recommend:
1.  **Introduce TimescaleDB**: Convert the `kpi_metrics` table into a Hypertable. This allows automatic partitioning and compression.
2.  **Schema-less Ingestion**: Use a dedicated TSDB (like InfluxDB or Prometheus) for raw metric storage, keeping only "Aggregated Wisdom" in Postgres.
