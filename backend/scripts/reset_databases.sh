#!/usr/bin/env bash
# reset_databases.sh — Drop and recreate both Pedkai databases.
#
# This script is deliberately destructive. It is intended for development
# and synthetic-data environments where a clean rebuild is safer than
# surgical repair.
#
# Usage:
#   bash backend/scripts/reset_databases.sh            # local defaults
#   GRAPH_DB_HOST=10.0.0.5 bash backend/scripts/reset_databases.sh  # cloud
#
# After running, apply migrations:
#   cd backend && alembic upgrade head
#
# Then set up the metrics hypertable (Alembic does not manage the metrics DB):
#   See Step 1.3 in the recovery plan.
set -euo pipefail

GRAPH_HOST="${GRAPH_DB_HOST:-localhost}"
GRAPH_PORT="${GRAPH_DB_PORT:-5432}"
GRAPH_USER="${GRAPH_DB_USER:-pedkai}"
METRICS_HOST="${METRICS_DB_HOST:-localhost}"
METRICS_PORT="${METRICS_DB_PORT:-5433}"
METRICS_USER="${METRICS_DB_USER:-pedkai}"

echo "=== Pedkai Database Reset ==="
echo "Graph DB:   ${GRAPH_USER}@${GRAPH_HOST}:${GRAPH_PORT}"
echo "Metrics DB: ${METRICS_USER}@${METRICS_HOST}:${METRICS_PORT}"
echo ""
echo "This will DROP and recreate both pedkai and pedkai_metrics databases."
read -rp "Type YES to continue: " confirm
if [ "$confirm" != "YES" ]; then
    echo "Aborted."
    exit 1
fi

echo ""
echo "--- Resetting main database (pedkai) ---"
psql -h "$GRAPH_HOST" -p "$GRAPH_PORT" -U "$GRAPH_USER" -d postgres <<SQL
    SELECT pg_terminate_backend(pid)
    FROM pg_stat_activity
    WHERE datname = 'pedkai' AND pid <> pg_backend_pid();

    DROP DATABASE IF EXISTS pedkai;
    CREATE DATABASE pedkai;
SQL

psql -h "$GRAPH_HOST" -p "$GRAPH_PORT" -U "$GRAPH_USER" -d pedkai <<SQL
    CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
    CREATE EXTENSION IF NOT EXISTS vector;
SQL

echo "--- Resetting metrics database (pedkai_metrics) ---"
psql -h "$METRICS_HOST" -p "$METRICS_PORT" -U "$METRICS_USER" -d postgres <<SQL
    SELECT pg_terminate_backend(pid)
    FROM pg_stat_activity
    WHERE datname = 'pedkai_metrics' AND pid <> pg_backend_pid();

    DROP DATABASE IF EXISTS pedkai_metrics;
    CREATE DATABASE pedkai_metrics;
SQL

psql -h "$METRICS_HOST" -p "$METRICS_PORT" -U "$METRICS_USER" -d pedkai_metrics <<SQL
    CREATE EXTENSION IF NOT EXISTS timescaledb;
SQL

# Create the load-progress tracking table (operational, not Alembic-managed)
psql -h "$GRAPH_HOST" -p "$GRAPH_PORT" -U "$GRAPH_USER" -d pedkai <<SQL
    CREATE TABLE IF NOT EXISTS _load_progress (
        tenant_id   VARCHAR(100) NOT NULL,
        step_name   VARCHAR(100) NOT NULL,
        completed_at TIMESTAMPTZ NOT NULL,
        row_count   INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (tenant_id, step_name)
    );
SQL

echo ""
echo "=== Databases reset successfully ==="
echo ""
echo "Next steps:"
echo "  1. cd backend && alembic upgrade head"
echo "  2. Set up metrics hypertable (see recovery plan Step 1.3)"
echo "  3. Load tenant data with load_tenant.py"
