#!/usr/bin/env bash
# ============================================================================
# Pedkai — Cloud Deploy & Migrate (Oracle Cloud Infrastructure)
# ============================================================================
# Run this script FROM YOUR LOCAL MACHINE to deploy code updates and run
# Alembic migrations against the OCI database.
#
# What it does:
#   1. SSH into VM1 (App Server) and git pull latest code
#   2. Run `alembic upgrade head` inside a temporary Docker container
#      connected to the live OCI database (VM2)
#   3. Rebuild and restart the backend Docker container
#   4. Print a post-deploy health check
#
# Prerequisites (run once):
#   - SSH key auth set up to VM1
#   - .env on VM1 contains DATABASE_URL pointing to VM2
#   - OCI Security List / iptables: VM1 can reach VM2:5432
#
# Usage:
#   bash scripts/cloud/deploy-and-migrate.sh <vm1_public_ip> [ssh_user] [repo_dir]
#
# Examples:
#   bash scripts/cloud/deploy-and-migrate.sh 140.238.1.2
#   bash scripts/cloud/deploy-and-migrate.sh 140.238.1.2 ubuntu /home/ubuntu/Pedkai
# ============================================================================

set -euo pipefail

VM1_IP="${1:?Usage: $0 <vm1_public_ip> [ssh_user] [repo_dir]}"
SSH_USER="${2:-ubuntu}"
REPO_DIR="${3:-/home/ubuntu/Pedkai}"

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║   Pedkai — OCI Cloud Deploy & Migrate                          ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo "  VM1 (App):   ${SSH_USER}@${VM1_IP}"
echo "  Repo dir:    ${REPO_DIR}"
echo "  Timestamp:   $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
echo ""

# ---------------------------------------------------------------------------
# Step 1: Pull latest code on VM1
# Uses 'bash -s -- <args>' with a quoted heredoc to avoid shell quoting issues.
# Variables expanded locally (REPO_DIR) are passed as positional args.
# ---------------------------------------------------------------------------
echo "━━━ Step 1: Pull latest code ━━━"
ssh -o StrictHostKeyChecking=no "${SSH_USER}@${VM1_IP}" bash -s -- "${REPO_DIR}" <<'ENDSSH'
REPO_DIR="$1"
set -euo pipefail
cd "${REPO_DIR}"
echo "  Branch: $(git branch --show-current)"
echo "  Before: $(git rev-parse --short HEAD)"
git pull --ff-only
echo "   After: $(git rev-parse --short HEAD)"
ENDSSH
echo "  ✓ Code updated"
echo ""

# ---------------------------------------------------------------------------
# Step 2: Run Alembic migrations
# Passes REPO_DIR as a positional arg to avoid nested quoting problems.
# Alembic upgrade head is idempotent — safe to run on every deploy.
# Expected output per migration: Running upgrade 007 -> 008_abeyance_decay ...
# ---------------------------------------------------------------------------
echo "━━━ Step 2: Run Alembic migrations ━━━"
ssh -o StrictHostKeyChecking=no "${SSH_USER}@${VM1_IP}" bash -s -- "${REPO_DIR}" <<'ENDSSH'
REPO_DIR="$1"
set -euo pipefail
cd "${REPO_DIR}"

echo "  Current DB head (before):"
docker compose -f docker-compose.cloud.yml run --rm \
  -e PYTHONPATH=/app \
  pedkai-backend \
  python -m alembic -c backend/alembic.ini current \
  || echo "    (could not determine — image may need rebuild first)"

echo "  Running: alembic upgrade head ..."
docker compose -f docker-compose.cloud.yml run --rm \
  -e PYTHONPATH=/app \
  pedkai-backend \
  python -m alembic -c backend/alembic.ini upgrade head

echo "  Current DB head (after):"
docker compose -f docker-compose.cloud.yml run --rm \
  -e PYTHONPATH=/app \
  pedkai-backend \
  python -m alembic -c backend/alembic.ini current
ENDSSH
echo "  ✓ Migrations complete"
echo ""

# ---------------------------------------------------------------------------
# Step 3: Rebuild and restart the backend container
# ---------------------------------------------------------------------------
echo "━━━ Step 3: Rebuild & restart backend ━━━"
ssh -o StrictHostKeyChecking=no "${SSH_USER}@${VM1_IP}" bash -s -- "${REPO_DIR}" <<'ENDSSH'
REPO_DIR="$1"
set -euo pipefail
cd "${REPO_DIR}"
docker compose -f docker-compose.cloud.yml build pedkai-backend
docker compose -f docker-compose.cloud.yml up -d --force-recreate pedkai-backend
ENDSSH
echo "  ✓ Backend container restarted"
echo ""

# ---------------------------------------------------------------------------
# Step 4: Health check
# ---------------------------------------------------------------------------
echo "━━━ Step 4: Health check ━━━"
sleep 8
ssh -o StrictHostKeyChecking=no "${SSH_USER}@${VM1_IP}" bash -s <<'ENDSSH'
set -euo pipefail
for i in 1 2 3 4 5; do
  STATUS=$(curl -sf http://localhost:8000/health || echo 'NOT_READY')
  if echo "$STATUS" | grep -qi 'ok\|healthy'; then
    echo "  ✓ Backend is healthy"
    exit 0
  fi
  echo "  Attempt $i/5: not ready yet — waiting 5s..."
  sleep 5
done
echo "  ✗ Health check failed after 5 attempts"
echo "  Logs:"
docker compose -f docker-compose.cloud.yml logs --tail=30 pedkai-backend
exit 1
ENDSSH

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✓ Deploy complete"
echo "  Backend: https://pedk.ai (or your domain)"
echo "  Migrations: 015_abeyance_parquet_schema_alignment (HEAD)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
