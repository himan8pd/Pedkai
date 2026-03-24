-- Migration: Upgrade reconciliation tables from GT-based schema to signal-based schema.
--
-- The old reconciliation data was computed by comparing CMDB against ground-truth
-- tables (gt_network_entities, gt_entity_relationships) — which is invalid for
-- production use. All old results are dropped and the tables are recreated with
-- the correct schema.
--
-- Run once before starting the updated backend:
--   psql -h localhost -U postgres -d pedkai -f backend/app/scripts/migrate_reconciliation_schema.sql

BEGIN;

-- Drop old results (they were computed from ground-truth, not from signals)
DROP TABLE IF EXISTS reconciliation_results;
DROP TABLE IF EXISTS reconciliation_runs;

-- Recreate with signal-based schema
CREATE TABLE reconciliation_runs (
    run_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    triggered_by TEXT DEFAULT 'manual',
    status TEXT DEFAULT 'running',
    total_divergences TEXT,
    dark_nodes TEXT DEFAULT '0',
    phantom_nodes TEXT DEFAULT '0',
    identity_mutations TEXT DEFAULT '0',
    dark_attributes TEXT DEFAULT '0',
    dark_edges TEXT DEFAULT '0',
    phantom_edges TEXT DEFAULT '0',
    cmdb_entity_count TEXT DEFAULT '0',
    observed_entity_count TEXT DEFAULT '0',
    cmdb_edge_count TEXT DEFAULT '0',
    observed_edge_count TEXT DEFAULT '0',
    started_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMPTZ
);

CREATE TABLE reconciliation_results (
    result_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    divergence_type TEXT NOT NULL,
    entity_or_relationship TEXT,
    target_id TEXT,
    target_type TEXT,
    domain TEXT,
    description TEXT,
    attribute_name TEXT,
    cmdb_value TEXT,
    observed_value TEXT,
    confidence FLOAT DEFAULT 1.0,
    extra JSONB,
    ai_analysis JSONB,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX ix_rr_tenant ON reconciliation_results(tenant_id);
CREATE INDEX ix_rr_type ON reconciliation_results(divergence_type);
CREATE INDEX ix_rr_domain ON reconciliation_results(domain);

COMMIT;
