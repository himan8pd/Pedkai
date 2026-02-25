#!/usr/bin/env bash
# =============================================================================
# startup_prod.sh — Production-like Environment
# Starts PostgreSQL (pgvector) + TimescaleDB + Kafka via Docker Compose,
# runs Alembic migrations, then launches the Pedkai backend and frontend.
#
# Prerequisites:
#   - Docker Desktop running
#   - Python venv at ./venv with requirements.txt installed
#   - Node.js / npm installed
#   - .env file present (copy from .env.example and fill in values)
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/venv"
VENV_PYTHON="$VENV_DIR/bin/python"

# =============================================================================
# Guard: virtual environment
# =============================================================================
if [ ! -f "$VENV_PYTHON" ]; then
    cat <<EOF
Error: Project virtual environment not found.
Expected location: $VENV_DIR

Please create it and install dependencies:
  python3 -m venv venv
  $VENV_PYTHON -m pip install --upgrade pip
  $VENV_PYTHON -m pip install -r requirements.txt

Then try again.
EOF
    exit 1
fi

# =============================================================================
# Guard: Docker
# =============================================================================
if ! docker info >/dev/null 2>&1; then
    echo "❌ Docker is not running. Please start Docker Desktop and try again."
    exit 1
fi

# =============================================================================
# Guard: .env file
# =============================================================================
if [ ! -f "$SCRIPT_DIR/.env" ]; then
    echo "❌ .env file not found at $SCRIPT_DIR/.env"
    echo "   Copy .env.example to .env and fill in your values, then try again."
    exit 1
fi

# =============================================================================
# Load environment — source .env so all variables are available to this script
# (docker-compose also reads .env automatically, but we need them here too)
# =============================================================================
# shellcheck disable=SC2046
export $(grep -v '^#' "$SCRIPT_DIR/.env" | grep -v '^$' | xargs)
export PYTHONPATH="${PYTHONPATH:-}${PYTHONPATH:+:}$SCRIPT_DIR"

# Ensure required Docker Compose variables exist, fall back to inline defaults
export POSTGRES_USER="${POSTGRES_USER:-postgres}"
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-postgres}"

# Honour the DATABASE_URL from .env (PostgreSQL), do NOT override with SQLite
export DATABASE_URL="${DATABASE_URL:-postgresql+asyncpg://postgres:postgres@localhost:5432/pedkai}"
export METRICS_DATABASE_URL="${METRICS_DATABASE_URL:-postgresql+asyncpg://postgres:postgres@localhost:5433/pedkai_metrics}"

BACKEND_PORT="${PEDKAI_BACKEND_PORT:-8000}"
FRONTEND_PORT="${PEDKAI_FRONTEND_PORT:-3000}"

# =============================================================================
# Start infrastructure via Docker Compose
# =============================================================================
echo "=================================================="
echo "🐳 Starting Infrastructure (Docker Compose)"
echo "=================================================="
echo "  • PostgreSQL + pgvector  → localhost:5432"
echo "  • TimescaleDB            → localhost:5433"
echo "  • Kafka                  → localhost:9092"
echo "=================================================="

cd "$SCRIPT_DIR"
docker compose up -d postgres timescaledb kafka

# =============================================================================
# Wait for PostgreSQL to be healthy
# =============================================================================
echo ""
echo "⏳ Waiting for PostgreSQL (port 5432) to be ready..."
MAX_PG_RETRIES=30
PG_RETRIES=0
PG_READY=false

while [ $PG_RETRIES -lt $MAX_PG_RETRIES ]; do
    if docker compose exec -T postgres pg_isready -U "$POSTGRES_USER" -d pedkai >/dev/null 2>&1; then
        echo "✅ PostgreSQL is ready."
        PG_READY=true
        break
    fi
    echo "   Still waiting... ($((PG_RETRIES+1))/$MAX_PG_RETRIES)"
    sleep 2
    PG_RETRIES=$((PG_RETRIES+1))
done

if [ "$PG_READY" = "false" ]; then
    echo "❌ PostgreSQL did not become ready in time. Check 'docker compose logs postgres'."
    exit 1
fi

# =============================================================================
# Wait for TimescaleDB to be healthy
# =============================================================================
echo ""
echo "⏳ Waiting for TimescaleDB (port 5433) to be ready..."
MAX_TS_RETRIES=30
TS_RETRIES=0
TS_READY=false

while [ $TS_RETRIES -lt $MAX_TS_RETRIES ]; do
    if docker compose exec -T timescaledb pg_isready -U "$POSTGRES_USER" -d pedkai_metrics >/dev/null 2>&1; then
        echo "✅ TimescaleDB is ready."
        TS_READY=true
        break
    fi
    echo "   Still waiting... ($((TS_RETRIES+1))/$MAX_TS_RETRIES)"
    sleep 2
    TS_RETRIES=$((TS_RETRIES+1))
done

if [ "$TS_READY" = "false" ]; then
    echo "❌ TimescaleDB did not become ready in time. Check 'docker compose logs timescaledb'."
    exit 1
fi

# =============================================================================
# Run Alembic migrations
# =============================================================================
echo ""
echo "=================================================="
echo "🗄️  Running Alembic Migrations"
echo "=================================================="
cd "$SCRIPT_DIR"
PYTHONPATH="$SCRIPT_DIR" "$VENV_PYTHON" -m alembic -c backend/alembic.ini upgrade head
echo "✅ Migrations applied."

# =============================================================================
# Kill any existing processes on configured ports
# =============================================================================
cleanup_port() {
    local port=$1
    local pids
    pids=$(lsof -t -i :"$port" 2>/dev/null || true)
    if [ -n "$pids" ]; then
        echo "⚠️  Port $port is in use by PID(s): $pids. Killing..."
        kill -9 $pids 2>/dev/null || true
        sleep 2
    fi
}

cleanup_port "$BACKEND_PORT"
cleanup_port "$FRONTEND_PORT"

# =============================================================================
# Start backend
# =============================================================================
echo ""
echo "=================================================="
echo "🚀 Starting Pedkai API (Production Mode)"
echo "=================================================="
echo "Python:     $VENV_PYTHON"
echo "Database:   $DATABASE_URL"
echo "Policies:   backend/app/policies/global_policies.yaml"
echo "URL:        http://localhost:$BACKEND_PORT"
echo "Docs:       http://localhost:$BACKEND_PORT/docs"
echo "=================================================="

"$VENV_PYTHON" -m uvicorn backend.app.main:app \
    --host 0.0.0.0 \
    --port "$BACKEND_PORT" \
    --workers 2 \
    --no-access-log &
BACKEND_PID=$!

echo "Backend started (PID: $BACKEND_PID)"
echo ""

sleep 3

# =============================================================================
# Start frontend
# =============================================================================
echo "=================================================="
echo "🚀 Starting Pedkai NOC Dashboard (Frontend)"
echo "=================================================="
echo "URL:       http://localhost:$FRONTEND_PORT"
echo "Backend:   http://localhost:$BACKEND_PORT"
echo "=================================================="

if [ ! -d "$SCRIPT_DIR/frontend/node_modules" ]; then
    echo "📦 Node dependencies not found. Installing..."
    cd "$SCRIPT_DIR/frontend" && npm install && cd "$SCRIPT_DIR"
fi

echo "🧹 Cleaning up stale frontend processes..."
EXISTING_FRONTEND_PID=$(ps aux | grep 'next-server' | grep -v grep | awk '{print $2}' || true)
if [ -n "$EXISTING_FRONTEND_PID" ]; then
    echo "⚠️  Found stale frontend process(es): $EXISTING_FRONTEND_PID. Killing..."
    kill -9 $EXISTING_FRONTEND_PID 2>/dev/null || true
    sleep 1
fi
rm -rf "$SCRIPT_DIR/frontend/.next/dev/lock" 2>/dev/null || true

cd "$SCRIPT_DIR/frontend"
PORT="$FRONTEND_PORT" npm run dev &
FRONTEND_PID=$!

echo "Frontend started (PID: $FRONTEND_PID)"
echo ""

# =============================================================================
# Verify services
# =============================================================================
echo "--------------------------------------------------"
echo "🔍 Verifying Service Connectivity..."
echo "--------------------------------------------------"

MAX_RETRIES=15
RETRIES=0
BACKEND_UP=false

while [ $RETRIES -lt $MAX_RETRIES ]; do
    status_code=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:$BACKEND_PORT/health" || echo "000")
    if [ "$status_code" = "200" ]; then
        echo "✅ Backend is UP (http://localhost:$BACKEND_PORT)"
        BACKEND_UP=true
        break
    fi
    echo "⏳ Waiting for Backend... (Attempt $((RETRIES+1))/$MAX_RETRIES)"
    sleep 2
    RETRIES=$((RETRIES+1))
done

if [ "$BACKEND_UP" = "false" ]; then
    echo "❌ Backend failed to start (Code: $status_code)"
fi

MAX_FRONTEND_RETRIES=60
RETRIES=0
FRONTEND_UP=false

while [ $RETRIES -lt $MAX_FRONTEND_RETRIES ]; do
    status_code=$(curl -s -L -o /dev/null -w "%{http_code}" "http://127.0.0.1:$FRONTEND_PORT/" || echo "000")
    if [ "$status_code" = "200" ]; then
        echo "✅ Frontend is UP (http://localhost:$FRONTEND_PORT)"
        FRONTEND_UP=true
        break
    fi
    echo "⏳ Waiting for Frontend... (Attempt $((RETRIES+1))/$MAX_FRONTEND_RETRIES)"
    sleep 2
    RETRIES=$((RETRIES+1))
done

if [ "$FRONTEND_UP" = "false" ]; then
    echo "❌ Frontend failed to start (Code: $status_code)"
fi

echo "--------------------------------------------------"

if [ "$BACKEND_UP" = "true" ] && [ "$FRONTEND_UP" = "true" ]; then
    echo "✨ All services are running correctly."
    echo ""
    echo " → Backend:      http://localhost:$BACKEND_PORT"
    echo " → API Docs:     http://localhost:$BACKEND_PORT/docs"
    echo " → Frontend:     http://localhost:$FRONTEND_PORT"
    echo " → Postgres:     localhost:5432  (db: pedkai)"
    echo " → TimescaleDB:  localhost:5433  (db: pedkai_metrics)"
    echo " → Kafka UI:     http://localhost:8080  (if enabled)"
    echo ""
    echo "Press Ctrl+C to stop the application (Docker containers keep running)."
    echo "To also stop Docker: docker compose down"
    echo ""
else
    echo "🔴 Startup failed. Cleaning up application processes..."
    echo "   Docker containers left running — inspect with 'docker compose logs'"
    kill $BACKEND_PID $FRONTEND_PID 2>/dev/null || true
    exit 1
fi

# =============================================================================
# Clean shutdown: Ctrl+C stops app but leaves Docker containers running
# (use 'docker compose down' to fully tear down)
# =============================================================================
trap 'echo ""; echo "Shutting down application services..."; kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; wait; echo "App stopped. Docker containers still running — use: docker compose down"; exit 0' INT TERM
wait
