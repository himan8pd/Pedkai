#!/usr/bin/env bash
# ============================================================================
# Pedkai — Load Six Telecom Data (run directly on VM1 App Server)
# ============================================================================
# Run this script ON THE CLOUD APP SERVER (VM1) where the parquet files
# already exist (either generated locally on VM1 or placed there by other
# means). DB loading happens entirely over the private VCN to VM2, so
# throughput is fast without any local-machine bottleneck.
#
# Prerequisites:
#   - deploy-and-migrate.sh has already been run successfully
#   - Parquet files exist on this VM (generated or transferred)
#   - Docker is running and pedkai-backend image is built
#   - .env in ~/Pedkai/ contains DATABASE_URL / GRAPH_DB_DSN
#
# Usage (run on VM1):
#   cd ~/Pedkai
#   bash scripts/cloud/load-six-telecom-cloud.sh <output_dir> [options]
#
# Arguments:
#   output_dir      Path to the directory containing *.parquet files
#                   (e.g. ~/Sleeping-Cell-KPI-Data/tmp_pedkai_data/output)
#
# Options:
#   --tenant-id     Tenant slug               (default: six-telecom-01)
#   --tenant-name   Tenant display name       (default: "Six Telecom")
#   --kpi-hours     Hours of KPI data to load into TimescaleDB (default: 0 = skip)
#   --clean         Delete existing tenant data before loading (DANGER)
#   --dry-run       Validate files, print row counts, no DB writes
#   --abeyance-dir  Subdirectory name for abeyance memory files (default: abeyance_memory)
#
# Examples:
#   # Standard full load (no KPI time-series)
#   bash scripts/cloud/load-six-telecom-cloud.sh \
#       ~/Sleeping-Cell-KPI-Data/tmp_pedkai_data/output
#
#   # Load with 24h KPI sample into TimescaleDB
#   bash scripts/cloud/load-six-telecom-cloud.sh \
#       ~/Sleeping-Cell-KPI-Data/tmp_pedkai_data/output \
#       --kpi-hours 24
#
#   # Dry run first (always recommended before first load)
#   bash scripts/cloud/load-six-telecom-cloud.sh \
#       ~/Sleeping-Cell-KPI-Data/tmp_pedkai_data/output \
#       --dry-run
#
#   # Re-load after clean (danger — deletes all existing tenant data)
#   bash scripts/cloud/load-six-telecom-cloud.sh \
#       ~/Sleeping-Cell-KPI-Data/tmp_pedkai_data/output \
#       --clean
# ============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------
OUTPUT_DIR="${1:?Usage: $0 <output_dir> [--tenant-id <id>] [--tenant-name <name>] [--kpi-hours <n>] [--clean] [--dry-run]}"
shift

TENANT_ID="six-telecom-01"
TENANT_NAME="Six Telecom"
KPI_HOURS=0
CLEAN_FLAG=""
DRY_RUN_FLAG=""
ABEYANCE_DIR="abeyance_memory"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --tenant-id)    TENANT_ID="$2";    shift 2 ;;
        --tenant-name)  TENANT_NAME="$2";  shift 2 ;;
        --kpi-hours)    KPI_HOURS="$2";    shift 2 ;;
        --abeyance-dir) ABEYANCE_DIR="$2"; shift 2 ;;
        --clean)        CLEAN_FLAG="--clean"; shift ;;
        --dry-run)      DRY_RUN_FLAG="--dry-run"; shift ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# Resolve repo dir relative to this script's location
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Resolve output dir to an absolute path
OUTPUT_DIR="$(cd "${OUTPUT_DIR}" && pwd)"

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║   Pedkai — Six Telecom Tenant Loader (on-server)               ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo "  Repo dir:    ${REPO_DIR}"
echo "  Output dir:  ${OUTPUT_DIR}"
echo "  Tenant ID:   ${TENANT_ID}"
echo "  Tenant name: ${TENANT_NAME}"
echo "  KPI hours:   ${KPI_HOURS}"
echo "  Dry run:     ${DRY_RUN_FLAG:-no}"
echo "  Clean mode:  ${CLEAN_FLAG:-no}"
echo "  Timestamp:   $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
echo ""

# ---------------------------------------------------------------------------
# Step 1: Validate parquet files
# ---------------------------------------------------------------------------
echo "━━━ Step 1: Validate parquet files ━━━"

if [ ! -d "${OUTPUT_DIR}" ]; then
    echo "  ✗ Output directory not found: ${OUTPUT_DIR}"
    exit 1
fi

CORE_FILES=(
    "cmdb_declared_entities.parquet"
    "cmdb_declared_relationships.parquet"
    "customers_bss.parquet"
    "events_alarms.parquet"
    "neighbour_relations.parquet"
    "vendor_naming_map.parquet"
)
MISSING=0
for f in "${CORE_FILES[@]}"; do
    if [ -f "${OUTPUT_DIR}/${f}" ]; then
        SIZE=$(du -sh "${OUTPUT_DIR}/${f}" | cut -f1)
        echo "  ✓ ${f} (${SIZE})"
    else
        echo "  ✗ MISSING: ${f}"
        MISSING=$((MISSING + 1))
    fi
done

ABEYANCE_PATH="${OUTPUT_DIR}/${ABEYANCE_DIR}"
ABEYANCE_FLAG=""
if [ -d "${ABEYANCE_PATH}" ]; then
    ABEYANCE_COUNT=$(ls "${ABEYANCE_PATH}"/*.parquet 2>/dev/null | wc -l | tr -d ' ')
    echo "  ✓ ${ABEYANCE_DIR}/ (${ABEYANCE_COUNT} parquet files)"
    ABEYANCE_FLAG="--load-abeyance-memory"
else
    echo "  ⚠ No ${ABEYANCE_DIR}/ subdirectory found — abeyance memory will be skipped"
fi

if [ "${MISSING}" -gt 0 ]; then
    echo ""
    echo "  ✗ ${MISSING} required file(s) missing. Aborting."
    exit 1
fi
echo ""

# ---------------------------------------------------------------------------
# Step 2: Check Docker image is available
# ---------------------------------------------------------------------------
echo "━━━ Step 2: Check Docker image ━━━"
cd "${REPO_DIR}"
if ! docker compose -f docker-compose.cloud.yml images pedkai-backend 2>/dev/null | grep -q pedkai; then
    echo "  ⚠ pedkai-backend image not found — building now..."
    docker compose -f docker-compose.cloud.yml build pedkai-backend
fi
echo "  ✓ Docker image ready"
echo ""

# ---------------------------------------------------------------------------
# Step 3: Run loader in a temporary container
#
# The container mounts the output dir read-only (or read-write for clean mode
# so the loader can write logs if needed). The .env file is picked up via
# env_file in docker-compose.cloud.yml, giving the container DATABASE_URL,
# GRAPH_DB_DSN, METRICS_DB_DSN etc.
# ---------------------------------------------------------------------------
echo "━━━ Step 3: Run load_tenant.py ━━━"

# Build the KPI hours flag
KPI_FLAG=""
if [ "${KPI_HOURS}" -gt 0 ]; then
    KPI_FLAG="--kpi-sample-hours ${KPI_HOURS}"
fi

# If clean mode, ask for confirmation (mirrors the safety gate in load_tenant.py)
if [ -n "${CLEAN_FLAG}" ] && [ -z "${DRY_RUN_FLAG}" ]; then
    echo ""
    echo "  ⚠  CLEAN MODE — this will DELETE all existing data for tenant '${TENANT_ID}'"
    echo "     Press ENTER to confirm or Ctrl+C to abort..."
    read -r
fi

docker compose -f docker-compose.cloud.yml run --rm \
    -e PYTHONPATH=/app \
    -v "${OUTPUT_DIR}:${OUTPUT_DIR}:ro" \
    pedkai-backend \
    python -m backend.app.scripts.load_tenant \
        --tenant-id    "${TENANT_ID}" \
        --tenant-name  "${TENANT_NAME}" \
        --output-dir   "${OUTPUT_DIR}" \
        --abeyance-dir "${ABEYANCE_PATH}" \
        ${ABEYANCE_FLAG} \
        ${KPI_FLAG} \
        ${CLEAN_FLAG} \
        ${DRY_RUN_FLAG}

echo ""
if [ -n "${DRY_RUN_FLAG}" ]; then
    echo "  ✓ Dry run complete — no data written"
    echo "  Re-run without --dry-run to perform the actual load."
else
    echo "  ✓ Load complete"
fi
echo ""

# ---------------------------------------------------------------------------
# Step 4: Print row counts (skipped in dry-run)
# ---------------------------------------------------------------------------
if [ -z "${DRY_RUN_FLAG}" ]; then
    echo "━━━ Step 4: Row count verification ━━━"

    docker compose -f docker-compose.cloud.yml run --rm \
        -e PYTHONPATH=/app \
        pedkai-backend \
        python -c "
import os, sys
try:
    import psycopg2
except ImportError:
    print('  psycopg2 not available — skipping verification')
    sys.exit(0)

dsn = os.environ.get('GRAPH_DB_DSN') or os.environ.get('DATABASE_URL', '')
if not dsn:
    print('  ⚠ No GRAPH_DB_DSN / DATABASE_URL set')
    sys.exit(0)
if dsn.startswith('postgresql+asyncpg://'):
    dsn = dsn.replace('postgresql+asyncpg://', 'postgresql://', 1)

tables = [
    'network_entities', 'entity_relationships', 'topology_relationships',
    'customers', 'bss_service_plans', 'bss_billing_accounts',
    'telco_events_alarms', 'neighbour_relations', 'vendor_naming_map',
    'kpi_dataset_registry', 'abeyance_fragment', 'snap_decision_record',
    'disconfirmation_events', 'bridge_discovery', 'causal_evidence_pair',
    'surprise_event', 'entity_sequence_log',
]
tenant = '${TENANT_ID}'
conn = psycopg2.connect(dsn)
print(f'  {\"Table\":<40} {\"Rows\":>12}')
print(f'  {\"-\" * 54}')
total = 0
with conn.cursor() as cur:
    for t in tables:
        try:
            cur.execute(f'SELECT COUNT(*) FROM {t} WHERE tenant_id = %s', (tenant,))
            count = cur.fetchone()[0]
            total += count
            mark = '✓' if count > 0 else '⊘'
            print(f'  {mark} {t:<38} {count:>12,}')
        except Exception as e:
            print(f'  ? {t:<38}   (error: {e})')
            conn.rollback()
print(f'  {\"-\" * 54}')
print(f'    {\"TOTAL\":<38} {total:>12,}')
conn.close()
"
    echo ""
fi

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Done — tenant: ${TENANT_ID}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
