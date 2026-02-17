#!/bin/bash

echo "=================================================="
echo "🚀 Starting Pedkai NOC Dashboard (Frontend)"
echo "=================================================="
echo "Directory: ./frontend"

# Frontend / Backend URLs (env-overridable, local defaults)
FRONTEND_PORT="${PEDKAI_FRONTEND_PORT:-3000}"
BACKEND_PORT="${PEDKAI_BACKEND_PORT:-8000}"
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
