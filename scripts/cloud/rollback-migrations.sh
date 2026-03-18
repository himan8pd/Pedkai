#!/usr/bin/env bash
# ============================================================================
# Pedkai — Rollback Migrations on OCI (Emergency)
# ============================================================================
# Rolls back the two new migrations (015, then 014) if something went wrong
# after deploy-and-migrate.sh. Runs in a temporary Docker container so no
# local Python environment is needed.
#
# Usage:
#   bash scripts/cloud/rollback-migrations.sh <vm1_public_ip> [target_revision] [ssh_user]
#
# Examples:
#   # Roll back to 013 (undoes 015 and 014)
#   bash scripts/cloud/rollback-migrations.sh 140.238.1.2
#
#   # Roll back to 014 only (undoes 015 alone)
#   bash scripts/cloud/rollback-migrations.sh 140.238.1.2 014_add_missing_core_tables
# ============================================================================

set -euo pipefail

VM1_IP="${1:?Usage: $0 <vm1_public_ip> [target_revision] [ssh_user]}"
TARGET_REV="${2:-013_counterflag}"
SSH_USER="${3:-ubuntu}"
REPO_DIR="/home/${SSH_USER}/Pedkai"
SSH="ssh -o StrictHostKeyChecking=no ${SSH_USER}@${VM1_IP}"

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║   Pedkai — OCI Migration Rollback                              ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo "  Target revision: ${TARGET_REV}"
echo ""
echo "  WARNING: This will DOWNGRADE the database schema."
echo "  The abeyance-specific columns and tables will be removed."
echo "  Ensure the backend is stopped or no tenant data has been"
echo "  loaded against the new schema before proceeding."
echo ""
echo "  Press ENTER to proceed or Ctrl+C to abort..."
read -r

$SSH bash -c "
  set -euo pipefail
  cd '${REPO_DIR}'

  echo 'Current head:'
  docker compose -f docker-compose.cloud.yml run --rm \
    -e PYTHONPATH=/app pedkai-backend \
    bash -c 'cd /app && python -m alembic -c backend/alembic.ini current'

  echo 'Downgrading to: ${TARGET_REV} ...'
  docker compose -f docker-compose.cloud.yml run --rm \
    -e PYTHONPATH=/app pedkai-backend \
    bash -c 'cd /app && python -m alembic -c backend/alembic.ini downgrade ${TARGET_REV}'

  echo 'New head:'
  docker compose -f docker-compose.cloud.yml run --rm \
    -e PYTHONPATH=/app pedkai-backend \
    bash -c 'cd /app && python -m alembic -c backend/alembic.ini current'
"

echo ""
echo "  ✓ Rollback to ${TARGET_REV} complete"
echo ""
echo "  To re-apply: bash scripts/cloud/deploy-and-migrate.sh ${VM1_IP}"
