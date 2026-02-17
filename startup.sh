# Pedkai startup script updated on 16-Feb-26 
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
# Port configuration
# =============================================================================
BACKEND_PORT="${PEDKAI_BACKEND_PORT:-8000}"
FRONTEND_PORT="${PEDKAI_FRONTEND_PORT:-3000}"

# =============================================================================
# Kill any existing processes on configured ports
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

cleanup_port $BACKEND_PORT
cleanup_port $FRONTEND_PORT

# =============================================================================
# Start backend in background
# =============================================================================
echo "=================================================="
echo "🚀 Starting Pedkai API (Local Demo Environment)"
echo "=================================================="
echo "Python:     $VENV_PYTHON"
echo "Database:   ./pedkai_demo.db (Seeded)"
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

# Give backend a moment to start (helps frontend connect faster)
sleep 2

# =============================================================================
# Start frontend in foreground (or background — see notes)
# =============================================================================
echo "=================================================="
echo "🚀 Starting Pedkai NOC Dashboard (Frontend)"
echo "=================================================="
FRONTEND_URL="${FRONTEND_URL:-http://localhost:$FRONTEND_PORT}"
BACKEND_URL="${BACKEND_URL:-http://localhost:$BACKEND_PORT}"
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
PORT="$FRONTEND_PORT" npm run dev &
FRONTEND_PID=$!

echo "Frontend started (PID: $FRONTEND_PID)"
echo ""

# Verification step
echo "--------------------------------------------------"
echo "🔍 Verifying Service Connectivity..."
echo "--------------------------------------------------"

# Wait for backend to be ready
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
    echo "❌ Backend failed to start or is not responding (Code: $status_code)"
    # We don't exit immediately, let's check frontend too
fi

# Wait for frontend to be ready (Next.js can be slow on first run)
MAX_FRONTEND_RETRIES=60
RETRIES=0
FRONTEND_UP=false

while [ $RETRIES -lt $MAX_FRONTEND_RETRIES ]; do
    # Use -L to follow redirects if any, -s for silent
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
    echo "❌ Frontend failed to start or is not responding (Code: $status_code)"
fi

echo "--------------------------------------------------"

if [ "$BACKEND_UP" = "true" ] && [ "$FRONTEND_UP" = "true" ]; then
    echo "✨ All services are running correctly."
    echo " → Backend: http://localhost:$BACKEND_PORT"
    echo " → Docs:    http://localhost:$BACKEND_PORT/docs"
    echo " → Frontend: http://localhost:$FRONTEND_PORT"
    echo ""
    echo "Press Ctrl+C to stop both services..."
    echo ""
else
    echo "🔴 Startup failed. Some services are not responding correctly."
    echo "Check the logs above for errors."
    echo ""
    echo "Cleaning up processes and exiting..."
    kill $BACKEND_PID $FRONTEND_PID 2>/dev/null || true
    exit 1
fi

# =============================================================================
# Keep script alive + clean shutdown on Ctrl+C
# =============================================================================
trap 'echo ""; echo "Shutting down Services..."; kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; wait; echo "All services stopped."; exit 0' INT TERM

# Wait forever (until Ctrl+C)
wait