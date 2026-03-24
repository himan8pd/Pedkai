#!/bin/bash
TOKEN=$(curl -s -X POST https://pedk.ai/api/v1/auth/token \
  -d 'username=pedkai_admin&password=PedkaiAdmin2026%21' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
echo "$TOKEN" > /home/ubuntu/.pedkai_token
