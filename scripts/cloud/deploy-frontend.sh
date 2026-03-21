#!/usr/bin/env bash
set -euo pipefail

# One-command frontend deploy: pull → build → serve
# Usage: ./scripts/cloud/deploy-frontend.sh

cd ~/Pedkai

echo "==> Pulling latest code..."
git pull origin main

echo "==> Building frontend (this takes ~60s)..."
docker compose -f docker-compose.cloud.yml build --no-cache pedkai-frontend

echo "==> Restarting frontend container..."
docker compose -f docker-compose.cloud.yml up -d --force-recreate pedkai-frontend

echo "==> Waiting for files to copy..."
sleep 3

echo "==> Copying static files to Caddy..."
sudo docker cp pedkai-frontend:/srv/frontend/. /srv/frontend/

echo "==> Done! Verify with:"
echo "    curl -sI https://pedk.ai | grep last-modified"
