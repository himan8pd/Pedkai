#!/usr/bin/env bash
# ============================================================================
# Pedkai — Load Six Telecom Data on OCI (Cloud)
# ============================================================================
# Run this script FROM YOUR LOCAL MACHINE after running deploy-and-migrate.sh.
#
# What it does:
#   1. Transfers the Six Telecom parquet files to VM1 (App Server)
#   2. Runs load_tenant.py inside a temporary Docker container on VM1
#      (the container has access to DATABASE_URL / GRAPH_DB_DSN from .env)
#
# Usage:
#   bash scripts/cloud/load-six-telecom-cloud.sh \
#     <vm1_public_ip> \
#     <local_output_dir> \
#     [ssh_user] \
#     [tenant_id] \
#     [tenant_name]
#
# Examples:
#   # Full load (transfers files + loads all steps + abeyance memory)
#   bash scripts/cloud/load-six-telecom-cloud.sh \
#       140.238.1.2 \
#       /Users/himanshu/Projects/Sleeping-Cell-KPI-Data/tmp_pedkai_data/output
#
#   # Custom tenant ID
#   bash scripts/cloud/load-six-telecom-cloud.sh \
#       140.238.1.2 \
#       /Users/himanshu/Projects/Sleeping-Cell-KPI-Data/tmp_pedkai_data/output \
#       ubuntu \
#       six-telecom-01 \
#       "Six Telecom"
# ============================================================================

set -euo pipefail

VM1_IP="${1:?Usage: $0 <vm1_public_ip> <local_output_dir> [ssh_user] [tenant_id] [tenant_name]}"
LOCAL_OUTPUT_DIR="${2:?Usage: $0 <vm1_public_ip> <local_output_dir> [ssh_user] [tenant_id] [tenant_name]}"
SSH_USER="${3:-ubuntu}"
TENANT_ID="${4:-six-telecom-01}"
TENANT_NAME="${5:-Six Telecom}"

REMOTE_DATA_DIR="/tmp/pedkai-data/${TENANT_ID}"
REPO_DIR="/home/${SSH_USER}/Pedkai"
SSH="ssh -o StrictHostKeyChecking=no ${SSH_USER}@${VM1_IP}"

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║   Pedkai — Six Telecom Cloud Data Load                         ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo "  VM1 (App):   ${SSH_USER}@${VM1_IP}"
echo "  Local data:  ${LOCAL_OUTPUT_DIR}"
echo "  Remote data: ${REMOTE_DATA_DIR}"
echo "  Tenant ID:   ${TENANT_ID}"
echo "  Tenant name: ${TENANT_NAME}"
echo ""

# ---------------------------------------------------------------------------
# Step 1: Validate local data directory
# ---------------------------------------------------------------------------
echo "━━━ Step 1: Validate local data directory ━━━"
if [ ! -d "${LOCAL_OUTPUT_DIR}" ]; then
    echo "  ✗ Directory not found: ${LOCAL_OUTPUT_DIR}"
    exit 1
fi

CORE_FILES=("cmdb_declared_entities.parquet" "customers_bss.parquet" "kpi_metrics_wide.parquet")
for f in "${CORE_FILES[@]}"; do
    if [ ! -f "${LOCAL_OUTPUT_DIR}/${f}" ]; then
        echo "  ✗ Missing core file: ${LOCAL_OUTPUT_DIR}/${f}"
        exit 1
    fi
done

ABEYANCE_DIR="${LOCAL_OUTPUT_DIR}/abeyance_memory"
ABEYANCE_FLAG=""
if [ -d "${ABEYANCE_DIR}" ]; then
    ABEYANCE_COUNT=$(ls "${ABEYANCE_DIR}"/*.parquet 2>/dev/null | wc -l)
    echo "  ✓ Core parquet files found"
    echo "  ✓ Abeyance memory directory found (${ABEYANCE_COUNT} parquet files)"
    ABEYANCE_FLAG="--load-abeyance-memory"
else
    echo "  ⚠ No abeyance_memory/ subdirectory found — will skip abeyance load"
fi
echo ""

# ---------------------------------------------------------------------------
# Step 2: Transfer parquet files to VM1
# ---------------------------------------------------------------------------
echo "━━━ Step 2: Transfer parquet files to VM1 ━━━"
$SSH "mkdir -p '${REMOTE_DATA_DIR}/abeyance_memory'"

echo "  Transferring core parquet files..."
rsync -avz --progress \
    --include="*.parquet" \
    --exclude="*" \
    "${LOCAL_OUTPUT_DIR}/" \
    "${SSH_USER}@${VM1_IP}:${REMOTE_DATA_DIR}/"

if [ -d "${ABEYANCE_DIR}" ]; then
    echo "  Transferring abeyance_memory/ parquet files..."
    rsync -avz --progress \
        --include="*.parquet" \
        --exclude="*" \
        "${ABEYANCE_DIR}/" \
        "${SSH_USER}@${VM1_IP}:${REMOTE_DATA_DIR}/abeyance_memory/"
fi

echo "  ✓ Files transferred"
echo ""

# ---------------------------------------------------------------------------
# Step 3: Dry run first (validate without touching the DB)
# ---------------------------------------------------------------------------
echo "━━━ Step 3: Dry run (validation only) ━━━"
$SSH bash -c "
  set -euo pipefail
  cd '${REPO_DIR}'
  docker compose -f docker-compose.cloud.yml run --rm \
    -e PYTHONPATH=/app \
    -v '${REMOTE_DATA_DIR}:${REMOTE_DATA_DIR}:ro' \
    pedkai-backend \
    python -m backend.app.scripts.load_tenant \
      --tenant-id '${TENANT_ID}' \
      --tenant-name '${TENANT_NAME}' \
      --output-dir '${REMOTE_DATA_DIR}' \
      ${ABEYANCE_FLAG} \
      --dry-run
"
echo "  ✓ Dry run passed"
echo ""

# ---------------------------------------------------------------------------
# Step 4: Actual load
# ---------------------------------------------------------------------------
echo "━━━ Step 4: Load data ━━━"
echo "  This will load all tenant data into the live OCI database."
echo "  Press ENTER to proceed or Ctrl+C to abort..."
read -r

$SSH bash -c "
  set -euo pipefail
  cd '${REPO_DIR}'
  docker compose -f docker-compose.cloud.yml run --rm \
    -e PYTHONPATH=/app \
    -v '${REMOTE_DATA_DIR}:${REMOTE_DATA_DIR}' \
    pedkai-backend \
    python -m backend.app.scripts.load_tenant \
      --tenant-id '${TENANT_ID}' \
      --tenant-name '${TENANT_NAME}' \
      --output-dir '${REMOTE_DATA_DIR}' \
      ${ABEYANCE_FLAG}
"
echo ""

# ---------------------------------------------------------------------------
# Step 5: Verify row counts in DB
# ---------------------------------------------------------------------------
echo "━━━ Step 5: Verify row counts ━━━"
$SSH bash -c "
  set -euo pipefail
  cd '${REPO_DIR}'
  docker compose -f docker-compose.cloud.yml run --rm \
    -e PYTHONPATH=/app \
    pedkai-backend \
    python -c \"
import os, psycopg2
dsn = os.environ.get('GRAPH_DB_DSN') or os.environ.get('DATABASE_URL', '')
if not dsn:
    print('  ⚠ No GRAPH_DB_DSN / DATABASE_URL set — cannot verify counts')
    exit(0)
# Convert SQLAlchemy URL to psycopg2 if needed
if dsn.startswith('postgresql+asyncpg://'):
    dsn = dsn.replace('postgresql+asyncpg://', 'postgresql://', 1)
conn = psycopg2.connect(dsn)
tables = [
    'network_entities', 'entity_relationships', 'customers',
    'telco_events_alarms', 'neighbour_relations', 'vendor_naming_map',
    'kpi_dataset_registry', 'abeyance_fragment', 'snap_decision_record',
    'disconfirmation_events', 'bridge_discovery', 'causal_evidence_pair',
    'surprise_event', 'entity_sequence_log',
]
print(f'  Row counts for tenant: ${TENANT_ID}')
print(f'  {\\\"Table\\\":40s} {\\\"Rows\\\":>12}')
print(f'  {\\\"-\\\" * 54}')
with conn.cursor() as cur:
    for t in tables:
        try:
            cur.execute(f\\\"SELECT COUNT(*) FROM {t} WHERE tenant_id = %s\\\", ('${TENANT_ID}',))
            count = cur.fetchone()[0]
            print(f'  {t:40s} {count:>12,}')
        except Exception as e:
            print(f'  {t:40s}   (error: {e})')
            conn.rollback()
conn.close()
\"
"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✓ Six Telecom load complete"
echo ""
echo "  Cleanup (optional — remove transferred files):"
echo "    ssh ${SSH_USER}@${VM1_IP} 'rm -rf ${REMOTE_DATA_DIR}'"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
