-- ============================================================================
-- Pedkai — Metrics Database Schema (TimescaleDB)
-- ============================================================================
-- Run against the pedkai_metrics database on VM 2.
-- Prerequisite: CREATE EXTENSION timescaledb; (done by setup-db-vm.sh)
--
-- Usage: psql -h <db-private-ip> -U pedkai -d pedkai_metrics -f create-metrics-tables.sql
-- ============================================================================

-- Main KPI metrics table
CREATE TABLE IF NOT EXISTS kpi_metrics (
    id              BIGSERIAL,
    timestamp       TIMESTAMPTZ     NOT NULL,
    entity_id       VARCHAR(255)    NOT NULL,
    entity_type     VARCHAR(100),
    tenant_id       VARCHAR(100)    NOT NULL,
    kpi_name        VARCHAR(255)    NOT NULL,
    kpi_value       DOUBLE PRECISION,
    unit            VARCHAR(50),
    metadata        JSONB           DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ     DEFAULT NOW()
);

-- Convert to TimescaleDB hypertable (partitioned by timestamp)
SELECT create_hypertable(
    'kpi_metrics',
    'timestamp',
    if_not_exists => TRUE,
    chunk_time_interval => INTERVAL '1 day'
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_kpi_entity_time
    ON kpi_metrics (entity_id, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_kpi_tenant_time
    ON kpi_metrics (tenant_id, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_kpi_name_time
    ON kpi_metrics (kpi_name, timestamp DESC);

-- Enable compression after 7 days
ALTER TABLE kpi_metrics SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'entity_id, tenant_id, kpi_name',
    timescaledb.compress_orderby = 'timestamp DESC'
);

SELECT add_compression_policy('kpi_metrics', INTERVAL '7 days', if_not_exists => TRUE);

-- Retention policy: drop chunks older than 30 days
SELECT add_retention_policy('kpi_metrics', INTERVAL '30 days', if_not_exists => TRUE);
