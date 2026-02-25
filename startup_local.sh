#!/usr/bin/env bash
# =============================================================================
# startup_local.sh — Local / Demo Environment
# Uses SQLite file-based databases (no Docker, no PostgreSQL required).
# Intended for: rapid local iteration, demos, and CI without infrastructure.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/venv"
VENV_PYTHON="$VENV_DIR/bin/python"

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
# Environment — force SQLite so no external DB is needed
# =============================================================================
export PYTHONPATH="${PYTHONPATH:-}${PYTHONPATH:+:}$SCRIPT_DIR"

export DATABASE_URL="sqlite+aiosqlite:///./pedkai_demo.db"
export METRICS_DATABASE_URL="sqlite+aiosqlite:///./pedkai_metrics_demo.db"
export PEDKAI_POLICY_PATH="${PEDKAI_POLICY_PATH:-$SCRIPT_DIR/backend/app/policies/global_policies.yaml}"
export PEDKAI_POLICY_CHECKSUM="${PEDKAI_POLICY_CHECKSUM:-}"

# =============================================================================
# Port configuration
# =============================================================================
BACKEND_PORT="${PEDKAI_BACKEND_PORT:-8000}"
FRONTEND_PORT="${PEDKAI_FRONTEND_PORT:-3000}"

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
echo "=================================================="
echo "🚀 Starting Pedkai API (Local / SQLite Mode)"
echo "=================================================="
echo "Python:     $VENV_PYTHON"
echo "Database:   ./pedkai_demo.db (SQLite)"
echo "Policies:   backend/app/policies/global_policies.yaml"
echo "URL:        http://localhost:$BACKEND_PORT"
echo "Docs:       http://localhost:$BACKEND_PORT/docs"
echo "=================================================="

"$VENV_PYTHON" -m uvicorn backend.app.main:app \
    --host 0.0.0.0 \
    --port "$BACKEND_PORT" \
    --reload \
    --reload-dir backend &
BACKEND_PID=$!

echo "Backend started (PID: $BACKEND_PID)"
echo ""

sleep 2

# =============================================================================
# Start frontend
# =============================================================================
echo "=================================================="
echo "🚀 Starting Pedkai NOC Dashboard (Frontend)"
echo "=================================================="
FRONTEND_URL_DISPLAY="${FRONTEND_URL:-http://localhost:$FRONTEND_PORT}"
BACKEND_URL_DISPLAY="${BACKEND_URL:-http://localhost:$BACKEND_PORT}"
echo "URL:       ${FRONTEND_URL_DISPLAY}"
echo "Backend:   ${BACKEND_URL_DISPLAY}"
echo "=================================================="

if [ ! -d "$SCRIPT_DIR/frontend/node_modules" ]; then
    echo "📦 Dependencies not found. Installing..."
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

MAX_RETRIES=10
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
    echo " → Backend:  http://localhost:$BACKEND_PORT"
    echo " → Docs:     http://localhost:$BACKEND_PORT/docs"
    echo " → Frontend: http://localhost:$FRONTEND_PORT"
    echo ""
    echo "Press Ctrl+C to stop both services..."
else
    echo "🔴 Startup failed. Cleaning up..."
    kill $BACKEND_PID $FRONTEND_PID 2>/dev/null || true
    exit 1
fi

trap 'echo ""; echo "Shutting down..."; kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; wait; echo "All services stopped."; exit 0' INT TERM
wait
