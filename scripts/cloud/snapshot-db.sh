#!/usr/bin/env bash
# ============================================================================
# Pedkai — Database Volume Snapshot (runs ON the DB VM)
# ============================================================================
# Creates a named physical snapshot of the Postgres/TimescaleDB data directory
# by briefly stopping the server, tarballing /mnt/pgdata, then restarting.
#
# Usage (on DB VM):
#   sudo bash scripts/cloud/snapshot-db.sh <label>
#
# Examples:
#   sudo bash scripts/cloud/snapshot-db.sh baseline
#   sudo bash scripts/cloud/snapshot-db.sh before-six-telecom-load
#
# The snapshot is written to: /mnt/pg-snapshots/<label>.tar.gz
# ============================================================================

set -euo pipefail

LABEL="${1:?Usage: $0 <label>}"
PG_DATA_DIR="${PG_DATA_DIR:-/mnt/pgdata}"
SNAPSHOT_DIR="${SNAPSHOT_DIR:-/mnt/pg-snapshots}"
SNAPSHOT_FILE="${SNAPSHOT_DIR}/${LABEL}.tar.gz"

if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: This script must be run as root (sudo)." >&2
    exit 1
fi

if [ -f "$SNAPSHOT_FILE" ]; then
    echo "ERROR: Snapshot '${LABEL}' already exists at ${SNAPSHOT_FILE}." >&2
    echo "       Delete it first or choose a different label." >&2
    exit 1
fi

mkdir -p "$SNAPSHOT_DIR"

echo "==> Stopping PostgreSQL..."
systemctl stop postgresql

echo "==> Snapshotting ${PG_DATA_DIR} → ${SNAPSHOT_FILE} ..."
START_TIME=$(date +%s)
tar -czf "$SNAPSHOT_FILE" -C "$(dirname "$PG_DATA_DIR")" "$(basename "$PG_DATA_DIR")"
END_TIME=$(date +%s)
ELAPSED=$((END_TIME - START_TIME))
SIZE=$(du -sh "$SNAPSHOT_FILE" | cut -f1)

echo "==> Starting PostgreSQL..."
systemctl start postgresql

echo ""
echo "✓ Snapshot '${LABEL}' saved to ${SNAPSHOT_FILE} (${SIZE}, ${ELAPSED}s)"
echo ""
echo "To restore: sudo bash scripts/cloud/restore-db.sh ${LABEL}"
