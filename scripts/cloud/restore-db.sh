#!/usr/bin/env bash
# ============================================================================
# Pedkai — Database Volume Restore (runs ON the DB VM)
# ============================================================================
# Restores a named physical snapshot of the Postgres/TimescaleDB data directory
# by stopping the server, wiping /mnt/pgdata, extracting the snapshot, then
# restarting. This is a DESTRUCTIVE operation — current DB state is lost.
#
# Usage (on DB VM):
#   sudo bash scripts/cloud/restore-db.sh <label>
#
# Examples:
#   sudo bash scripts/cloud/restore-db.sh baseline
#   sudo bash scripts/cloud/restore-db.sh before-six-telecom-load
#
# Snapshots are read from: /mnt/pg-snapshots/<label>.tar.gz
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

if [ ! -f "$SNAPSHOT_FILE" ]; then
    echo "ERROR: Snapshot '${LABEL}' not found at ${SNAPSHOT_FILE}." >&2
    echo "       Available snapshots:" >&2
    ls -1 "${SNAPSHOT_DIR}"/*.tar.gz 2>/dev/null | sed 's|.*/||; s|\.tar\.gz$||' | sed 's/^/         /' >&2 || echo "         (none)" >&2
    exit 1
fi

echo "WARNING: This will DESTROY the current database state and restore '${LABEL}'."
echo "         All data loaded since the snapshot was taken will be permanently lost."
echo ""
read -r -p "Type 'yes' to confirm: " CONFIRM
if [ "$CONFIRM" != "yes" ]; then
    echo "Aborted."
    exit 0
fi

echo "==> Stopping PostgreSQL..."
systemctl stop postgresql

echo "==> Removing current data directory ${PG_DATA_DIR} ..."
rm -rf "$PG_DATA_DIR"

echo "==> Extracting snapshot '${LABEL}' → $(dirname "$PG_DATA_DIR") ..."
START_TIME=$(date +%s)
tar -xzf "$SNAPSHOT_FILE" -C "$(dirname "$PG_DATA_DIR")"
END_TIME=$(date +%s)
ELAPSED=$((END_TIME - START_TIME))

echo "==> Fixing ownership..."
chown -R postgres:postgres "$PG_DATA_DIR"

echo "==> Starting PostgreSQL..."
systemctl start postgresql

# Wait for Postgres to accept connections
MAX_WAIT=30
WAITED=0
until pg_isready -q 2>/dev/null || [ $WAITED -ge $MAX_WAIT ]; do
    sleep 1
    WAITED=$((WAITED + 1))
done

if pg_isready -q 2>/dev/null; then
    echo ""
    echo "✓ Database restored to snapshot '${LABEL}' (${ELAPSED}s — Postgres is ready)"
else
    echo ""
    echo "⚠  Database restored but Postgres did not become ready within ${MAX_WAIT}s."
    echo "   Check: sudo systemctl status postgresql"
fi
