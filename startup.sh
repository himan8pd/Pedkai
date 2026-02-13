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
export PEDKAI_POLICY_PATH="${PEDKAI_POLICY_PATH:-$SCRIPT_DIR/backend/app/policies/global_policies.yaml}"
export PEDKAI_POLICY_CHECKSUM="${PEDKAI_POLICY_CHECKSUM:-}"

# =============================================================================
# Kill any existing process on port 8000
# =============================================================================
EXISTING_PID=$(lsof -t -i :8000 2>/dev/null || true)
if [ -n "$EXISTING_PID" ]; then
    echo "⚠️  Port 8000 is in use by PID $EXISTING_PID. Killing..."
    kill -9 "$EXISTING_PID" 2>/dev/null || true
    sleep 1
fi

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

# We run frontend in foreground so logs are visible and Ctrl+C stops everything cleanly
cd "$SCRIPT_DIR/frontend"
npm run dev &
FRONTEND_PID=$!

echo "Frontend started (PID: $FRONTEND_PID)"
echo ""
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