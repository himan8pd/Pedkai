#!/bin/bash
# Fetch a JWT token for the pedkai_admin user.
# Password is read from PEDKAI_ADMIN_PASSWORD env var (never hardcode credentials).
if [ -z "$PEDKAI_ADMIN_PASSWORD" ]; then
  echo "Error: PEDKAI_ADMIN_PASSWORD environment variable is not set." >&2
  exit 1
fi

TOKEN=$(curl -s -X POST https://pedk.ai/api/v1/auth/token \
  -d "username=pedkai_admin&password=${PEDKAI_ADMIN_PASSWORD}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
echo "$TOKEN" > /home/ubuntu/.pedkai_token
