#!/bin/bash
# Set Python path to include current directory
export PYTHONPATH=$PYTHONPATH:$(pwd)

# Configure environment for local SQLite demo
export DATABASE_URL="sqlite+aiosqlite:///./pedkai_demo.db"
export PEDKAI_POLICY_PATH="$(pwd)/backend/app/policies/global_policies.yaml"
# Optional: Disable checksum enforcement for easy demo
export PEDKAI_POLICY_CHECKSUM="" 
export SECRET_KEY="demo-secret-key-insecure-only-for-local-playpen"

# Handle existing processes on port 8000
EXISTING_PID=$(lsof -t -i :8000)
if [ ! -z "$EXISTING_PID" ]; then
    echo "⚠️  Port 8000 is in use. Killing process $EXISTING_PID..."
    kill -9 $EXISTING_PID
fi

echo "=================================================="
echo "🚀 Starting Pedkai API (Local Demo Environment)"
echo "=================================================="
echo "Database: ./pedkai_demo.db (Seeded)"
echo "Policies: backend/app/policies/global_policies.yaml"
echo "URL:      http://localhost:8000"
echo "Docs:     http://localhost:8000/docs"
echo "Status:   READY (OpenAPI Schema Fixed)"
echo "=================================================="
echo "Press Ctrl+C to stop."
echo ""

# Launch Uvicorn
if command -v uvicorn &> /dev/null; then
    uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload
else
    python3 -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload
fi
