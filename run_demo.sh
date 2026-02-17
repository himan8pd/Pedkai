#!/bin/bash
# Set Python path to include current directory
export PYTHONPATH=$PYTHONPATH:$(pwd)

# Configure environment for local SQLite demo (override via .env if desired)
export DATABASE_URL="${DATABASE_URL:-sqlite+aiosqlite:///./pedkai_demo.db}"
export PEDKAI_POLICY_PATH="${PEDKAI_POLICY_PATH:-$(pwd)/backend/app/policies/global_policies.yaml}"
# Optional: Disable checksum enforcement for easy demo (empty by default)
export PEDKAI_POLICY_CHECKSUM="${PEDKAI_POLICY_CHECKSUM:-}"

# Port configuration
BACKEND_PORT="${PEDKAI_BACKEND_PORT:-8000}"
FRONTEND_PORT="${PEDKAI_FRONTEND_PORT:-3000}"

# Handle existing processes on ports
cleanup_port() {
    local port=$1
    local pids=$(lsof -t -i :$port 2>/dev/null || true)
    if [ -n "$pids" ]; then
        echo "⚠️  Port $port is in use. Killing PID(s): $pids..."
        kill -9 $pids 2>/dev/null || true
        sleep 2
    fi
}

cleanup_port $BACKEND_PORT
cleanup_port $FRONTEND_PORT

echo "=================================================="
echo "🚀 Starting Pedkai API (Local Demo Environment)"
echo "=================================================="
echo "Database: ./pedkai_demo.db (Seeded)"
echo "Policies: backend/app/policies/global_policies.yaml"
echo "URL:      http://localhost:$BACKEND_PORT"
echo "Docs:     http://localhost:$BACKEND_PORT/docs"
echo "Status:   READY (OpenAPI Schema Fixed)"
echo "=================================================="
echo "Press Ctrl+C to stop."
echo ""

# Launch Uvicorn
if command -v uvicorn &> /dev/null; then
    uvicorn backend.app.main:app --host 0.0.0.0 --port "$BACKEND_PORT" --reload --reload-dir backend
else
    python3 -m uvicorn backend.app.main:app --host 0.0.0.0 --port "$BACKEND_PORT" --reload --reload-dir backend
fi

echo "=================================================="
echo "🚀 Starting Pedkai NOC Dashboard (Frontend)"
echo "=================================================="
echo "Directory: ./frontend"

# Frontend / Backend URLs (env-overridable, local defaults)
FRONTEND_URL="${FRONTEND_URL:-http://localhost:$FRONTEND_PORT}"
BACKEND_URL="${BACKEND_URL:-http://localhost:$BACKEND_PORT}"

echo "URL:       ${FRONTEND_URL}"
echo "Backend:   ${BACKEND_URL} (Must be running!)"
echo "=================================================="

# Check if node_modules exists, if not install
if [ ! -d "frontend/node_modules" ]; then
    echo "📦 Dependencies not found. Installing..."
    cd frontend && npm install && cd ..
fi

# Navigate and start dev server
cd frontend
PORT="$FRONTEND_PORT" npm run dev
