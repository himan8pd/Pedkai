#!/usr/bin/env bash
set -euo pipefail   # Fail fast on errors, treat unset variables as errors

# =============================================================================
# Project-local Python & virtual environment
# =============================================================================

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
  $VENV_PYTHON -m pip install fastapi "uvicorn[standard]"   # or -r requirements.txt

Then try again.
EOF
    exit 1
fi

# =============================================================================
# Environment setup
# =============================================================================
export PYTHONPATH="${PYTHONPATH:-}${PYTHONPATH:+:}$SCRIPT_DIR"

export DATABASE_URL="${DATABASE_URL:-sqlite+aiosqlite:///./pedkai_demo.db}"
export METRICS_DATABASE_URL="${METRICS_DATABASE_URL:-sqlite+aiosqlite:///./pedkai_metrics_demo.db}"
export PEDKAI_POLICY_PATH="${PEDKAI_POLICY_PATH:-$SCRIPT_DIR/backend/app/policies/global_policies.yaml}"
export PEDKAI_POLICY_CHECKSUM="${PEDKAI_POLICY_CHECKSUM:-}"

# =============================================================================
# Kill any existing processes on ports 8000 and 3000
# =============================================================================
cleanup_port() {
    local port=$1
    local pids=$(lsof -t -i :$port 2>/dev/null || true)
    if [ -n "$pids" ]; then
        echo "⚠️  Port $port is in use by PID(s): $pids. Killing..."
        kill -9 $pids 2>/dev/null || true
        sleep 2
    fi
}

cleanup_port 8000
cleanup_port 3000

# =============================================================================
# Start backend in background
# =============================================================================
echo "=================================================="
echo "🚀 Starting Pedkai API (Local Demo Environment)"
echo "=================================================="
echo "Python:     $VENV_PYTHON"
echo "Database:   ./pedkai_demo.db (Seeded)"
echo "Policies:   backend/app/policies/global_policies.yaml"
echo "URL:        http://localhost:8000"
echo "Docs:       http://localhost:8000/docs"
echo "=================================================="

"$VENV_PYTHON" -m uvicorn backend.app.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --reload &
BACKEND_PID=$!

echo "Backend started (PID: $BACKEND_PID)"
echo ""

# Give backend a moment to start (helps frontend connect faster)
sleep 2

# =============================================================================
# Start frontend in foreground (or background — see notes)
# =============================================================================
echo "=================================================="
echo "🚀 Starting Pedkai NOC Dashboard (Frontend)"
echo "=================================================="
FRONTEND_URL="${FRONTEND_URL:-http://localhost:3000}"
BACKEND_URL="${BACKEND_URL:-http://localhost:8000}"
echo "URL:       ${FRONTEND_URL}"
echo "Backend:   ${BACKEND_URL}"
echo "=================================================="

if [ ! -d "$SCRIPT_DIR/frontend/node_modules" ]; then
    echo "📦 Dependencies not found. Installing..."
    cd "$SCRIPT_DIR/frontend" && npm install && cd "$SCRIPT_DIR"
fi

# Clean up stale frontend process & lock
echo "🧹 Cleaning up stale frontend processes..."
EXISTING_FRONTEND_PID=$(ps aux | grep 'next-server' | grep -v grep | awk '{print $2}' || true)
if [ -n "$EXISTING_FRONTEND_PID" ]; then
    echo "⚠️  Found stale frontend process(es): $EXISTING_FRONTEND_PID. Killing..."
    kill -9 $EXISTING_FRONTEND_PID 2>/dev/null || true
    sleep 1
fi
rm -rf "$SCRIPT_DIR/frontend/.next/dev/lock" 2>/dev/null || true

# We run frontend in foreground so logs are visible and Ctrl+C stops everything cleanly
cd "$SCRIPT_DIR/frontend"
npm run dev &
FRONTEND_PID=$!

echo "Frontend started (PID: $FRONTEND_PID)"
echo ""

# Verification step
sleep 5
echo "--------------------------------------------------"
echo "🔍 Verifying Service Connectivity..."
echo "--------------------------------------------------"

backend_status=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/health || echo "fail")
if [ "$backend_status" = "200" ]; then
    echo "✅ Backend is UP (http://localhost:8000)"
else
    echo "❌ Backend is NOT responding (Code: $backend_status)"
fi

frontend_status=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:3000/ || echo "fail")
if [ "$frontend_status" = "200" ]; then
    echo "✅ Frontend is UP (http://localhost:3000)"
else
    echo "❌ Frontend is NOT responding (Code: $frontend_status)"
fi
echo "--------------------------------------------------"

echo "Both services are running."
echo " → Backend → http://localhost:8000 / docs: http://localhost:8000/docs"
echo " → Frontend → http://localhost:3000"
echo ""
echo "Press Ctrl+C to stop both services..."
echo ""

# =============================================================================
# Keep script alive + clean shutdown on Ctrl+C
# =============================================================================
trap 'echo ""; echo "Shutting down..."; kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; wait; echo "All services stopped."; exit 0' INT TERM

# Wait forever (until Ctrl+C)
wait