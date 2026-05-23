#!/usr/bin/env bash
# test_abeyance_cloud.sh — End-to-end abeyance memory test against cloud API
#
# Usage:
#   ./test_abeyance_cloud.sh [base_url]
#
# Defaults to https://pedk.ai if no argument given.
# Requires: curl, jq

set -euo pipefail

BASE="${1:-https://pedk.ai}"
API="$BASE/api/v1"
TENANT="six_telecom"
USER="admin"
PASS="PedkaiAdmin2026%21"

PASS_COUNT=0
FAIL_COUNT=0
FRAGMENT_IDS=()

# ── Helpers ──────────────────────────────────────────────────────────────

pass() { ((PASS_COUNT++)); printf "  \033[32mPASS\033[0m %s\n" "$1"; }
fail() { ((FAIL_COUNT++)); printf "  \033[31mFAIL\033[0m %s\n" "$1"; }
section() { printf "\n\033[1m── %s ──\033[0m\n" "$1"; }

json_field() {
  echo "$1" | jq -r "$2" 2>/dev/null
}

assert_not_null() {
  local val="$1" label="$2"
  if [ -z "$val" ] || [ "$val" = "null" ]; then
    fail "$label (got null/empty)"
  else
    pass "$label = $val"
  fi
}

assert_eq() {
  local actual="$1" expected="$2" label="$3"
  if [ "$actual" = "$expected" ]; then
    pass "$label"
  else
    fail "$label (expected '$expected', got '$actual')"
  fi
}

assert_true() {
  local val="$1" label="$2"
  if [ "$val" = "true" ]; then
    pass "$label"
  else
    fail "$label (expected true, got '$val')"
  fi
}

assert_gt() {
  local actual="$1" threshold="$2" label="$3"
  if echo "$actual $threshold" | awk '{exit !($1 > $2)}'; then
    pass "$label ($actual > $threshold)"
  else
    fail "$label ($actual not > $threshold)"
  fi
}

# ── 1. Authenticate ─────────────────────────────────────────────────────

section "1. Authentication"

TOKEN_RESP=$(curl -s -X POST "$API/auth/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=${USER}&password=${PASS}")
TOKEN=$(json_field "$TOKEN_RESP" '.access_token')

if [ -z "$TOKEN" ] || [ "$TOKEN" = "null" ]; then
  echo "FATAL: Could not authenticate. Response:"
  echo "$TOKEN_RESP" | jq . 2>/dev/null || echo "$TOKEN_RESP"
  exit 1
fi
pass "Got auth token"

AUTH="Authorization: Bearer $TOKEN"

# ── 2. Discovery Status (T-VEC / TSLAM health) ──────────────────────────

section "2. Discovery Status (T-VEC / TSLAM health)"

STATUS_RESP=$(curl -s "$API/abeyance/discovery/status?tenant_id=$TENANT" \
  -H "$AUTH")

TVEC_LOADED=$(json_field "$STATUS_RESP" '.tvec.model_loaded // .tvec.loaded // .tvec.healthy // empty')
TSLAM_LOADED=$(json_field "$STATUS_RESP" '.tslam.model_loaded // .tslam.loaded // .tslam.healthy // empty')

echo "  T-VEC status: $(echo "$STATUS_RESP" | jq -c '.tvec' 2>/dev/null)"
echo "  TSLAM status: $(echo "$STATUS_RESP" | jq -c '.tslam' 2>/dev/null)"

if [ -n "$TVEC_LOADED" ] && [ "$TVEC_LOADED" != "null" ] && [ "$TVEC_LOADED" != "false" ]; then
  pass "T-VEC model loaded"
else
  fail "T-VEC model not loaded"
fi

# ── 3. Ingest Fragment A (ALARM — link failure) ─────────────────────────

section "3. Ingest Fragment A (ALARM — link failure)"

TS_A=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

FRAG_A_RESP=$(curl -s -X POST "$API/abeyance/ingest" \
  -H "$AUTH" \
  -H "Content-Type: application/json" \
  -d '{
    "content": "CRITICAL: Link DWDM-03 between NodeB-East-7734 and AGG-SW-CORE-12 is down. BER threshold exceeded 1e-3 for 47 minutes. Upstream alarms on 3 dependent eNodeBs: eNB-4401, eNB-4402, eNB-4403. Traffic rerouted via backup ring but capacity at 87%. NOC ticket TT-20260523-001 opened.",
    "source_type": "ALARM",
    "source_ref": "ALARM-DWDM03-20260523",
    "source_engineer_id": "noc-shift-b",
    "entity_refs": ["NodeB-East-7734", "AGG-SW-CORE-12", "DWDM-03"],
    "event_timestamp": "'"$TS_A"'",
    "metadata": {"severity": "CRITICAL", "region": "east", "domain": "transport"}
  }')

FRAG_A_ID=$(json_field "$FRAG_A_RESP" '.id')
FRAG_A_STATUS=$(json_field "$FRAG_A_RESP" '.snap_status')

if [ -z "$FRAG_A_ID" ] || [ "$FRAG_A_ID" = "null" ]; then
  echo "  Ingest response:"
  echo "$FRAG_A_RESP" | jq . 2>/dev/null || echo "$FRAG_A_RESP"
  fail "Fragment A ingest failed"
else
  pass "Fragment A ingested: $FRAG_A_ID"
  FRAGMENT_IDS+=("$FRAG_A_ID")
fi
assert_not_null "$FRAG_A_STATUS" "Fragment A snap_status"

# ── 4. Verify Fragment A enrichment ──────────────────────────────────────

section "4. Verify Fragment A enrichment (embeddings + masks)"

FRAG_A_DETAIL=$(curl -s "$API/abeyance/fragments/$FRAG_A_ID?tenant_id=$TENANT" \
  -H "$AUTH")

MASK_SEM=$(json_field "$FRAG_A_DETAIL" '.mask_semantic')
MASK_TOPO=$(json_field "$FRAG_A_DETAIL" '.mask_topological')
MASK_OPS=$(json_field "$FRAG_A_DETAIL" '.mask_operational')

echo "  Masks: semantic=$MASK_SEM, topological=$MASK_TOPO, operational=$MASK_OPS"

assert_true "$MASK_SEM" "mask_semantic = true (T-VEC generated embedding)"

ENTITIES=$(json_field "$FRAG_A_DETAIL" '.extracted_entities')
ENTITY_COUNT=$(echo "$ENTITIES" | jq 'length' 2>/dev/null || echo 0)
assert_gt "$ENTITY_COUNT" 0 "Entities extracted (count)"
echo "  Extracted entities: $ENTITIES"

DECAY=$(json_field "$FRAG_A_DETAIL" '.current_decay_score')
assert_not_null "$DECAY" "current_decay_score"

# ── 5. Ingest Fragment B (related TICKET — same incident) ────────────────

section "5. Ingest Fragment B (TICKET — correlated incident)"

sleep 2

TS_B=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

FRAG_B_RESP=$(curl -s -X POST "$API/abeyance/ingest" \
  -H "$AUTH" \
  -H "Content-Type: application/json" \
  -d '{
    "content": "Ticket TT-20260523-001: DWDM link between NodeB-East-7734 and AGG-SW-CORE-12 confirmed down. Root cause analysis: SFP module degradation on port Gi0/0/3 of AGG-SW-CORE-12. BER spike preceded by gradual optical power drop over 72h. Impact: 3 eNodeBs (eNB-4401, eNB-4402, eNB-4403) degraded, ~12000 subscribers affected. Backup ring absorbing traffic at 87% utilization. ETA for SFP replacement: 4 hours.",
    "source_type": "TICKET_TEXT",
    "source_ref": "TT-20260523-001",
    "source_engineer_id": "noc-shift-b",
    "entity_refs": ["NodeB-East-7734", "AGG-SW-CORE-12", "DWDM-03"],
    "event_timestamp": "'"$TS_B"'",
    "metadata": {"severity": "CRITICAL", "region": "east", "domain": "transport", "ticket_status": "open"}
  }')

FRAG_B_ID=$(json_field "$FRAG_B_RESP" '.id')
FRAG_B_STATUS=$(json_field "$FRAG_B_RESP" '.snap_status')

if [ -z "$FRAG_B_ID" ] || [ "$FRAG_B_ID" = "null" ]; then
  echo "  Ingest response:"
  echo "$FRAG_B_RESP" | jq . 2>/dev/null || echo "$FRAG_B_RESP"
  fail "Fragment B ingest failed"
else
  pass "Fragment B ingested: $FRAG_B_ID"
  FRAGMENT_IDS+=("$FRAG_B_ID")
fi

# ── 6. Check snap decisions ─────────────────────────────────────────────

section "6. Snap Decision Records"

SNAP_RESP=$(curl -s "$API/abeyance/snap-history?tenant_id=$TENANT&limit=10" \
  -H "$AUTH")

SNAP_COUNT=$(echo "$SNAP_RESP" | jq 'if type == "array" then length else 0 end' 2>/dev/null || echo 0)
echo "  Recent snap records: $SNAP_COUNT"

if [ "$SNAP_COUNT" -gt 0 ]; then
  LATEST_SNAP=$(echo "$SNAP_RESP" | jq '.[0]')
  FINAL_SCORE=$(json_field "$LATEST_SNAP" '.final_score')
  SCORE_SEM=$(json_field "$LATEST_SNAP" '.score_semantic')
  SCORE_TOPO=$(json_field "$LATEST_SNAP" '.score_topological')
  SCORE_TEMP=$(json_field "$LATEST_SNAP" '.score_temporal')
  SCORE_OPS=$(json_field "$LATEST_SNAP" '.score_operational')
  SCORE_ENT=$(json_field "$LATEST_SNAP" '.score_entity_overlap')
  THRESHOLD=$(json_field "$LATEST_SNAP" '.threshold_applied')

  echo "  Latest snap decision:"
  echo "    final_score:          $FINAL_SCORE"
  echo "    score_semantic:       $SCORE_SEM"
  echo "    score_topological:    $SCORE_TOPO"
  echo "    score_temporal:       $SCORE_TEMP"
  echo "    score_operational:    $SCORE_OPS"
  echo "    score_entity_overlap: $SCORE_ENT"
  echo "    threshold_applied:    $THRESHOLD"

  assert_not_null "$FINAL_SCORE" "final_score recorded"
  assert_not_null "$SCORE_SEM" "score_semantic recorded"
  assert_not_null "$SCORE_ENT" "score_entity_overlap recorded"

  if echo "$FINAL_SCORE" | awk '{exit !($1 >= 0.55)}' 2>/dev/null; then
    pass "Fragments A+B scored >= NEAR_MISS threshold (0.55)"
  else
    echo "  (Score below 0.55 — fragments may not be similar enough for snap)"
  fi
else
  fail "No snap decision records found"
fi

# ── 7. Ingest Fragment C via v3 Discovery Loop ──────────────────────────

section "7. Ingest Fragment C via v3 Discovery Loop (/ingest/v3)"

TS_C=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

FRAG_C_RESP=$(curl -s -w "\n%{http_code}" -X POST "$API/abeyance/ingest/v3" \
  -H "$AUTH" \
  -H "Content-Type: application/json" \
  -d '{
    "content": "CLI output from AGG-SW-CORE-12: show interface Gi0/0/3 — input errors 47823, CRC errors 12441, runts 0, giants 0. Optical power rx: -18.2 dBm (threshold: -14.0 dBm). SFP serial: FINISAR-FTLF8524P2BNV-APC4R21. Last flap: 2026-05-23T06:12:33Z. Interface administratively down per NOC instruction pending SFP replacement.",
    "source_type": "CLI_OUTPUT",
    "source_ref": "CLI-AGGSW12-GI003",
    "source_engineer_id": "noc-shift-b",
    "entity_refs": ["AGG-SW-CORE-12"],
    "event_timestamp": "'"$TS_C"'"
  }')

HTTP_CODE=$(echo "$FRAG_C_RESP" | tail -1)
BODY=$(echo "$FRAG_C_RESP" | sed '$d')

if [ "$HTTP_CODE" = "201" ]; then
  FRAG_C_ID=$(json_field "$BODY" '.fragment.id // .id // .fragment_id')
  pass "v3 Discovery Loop ingest succeeded (201)"
  echo "  Fragment C ID: $FRAG_C_ID"
  [ -n "$FRAG_C_ID" ] && [ "$FRAG_C_ID" != "null" ] && FRAGMENT_IDS+=("$FRAG_C_ID")

  STAGES=$(json_field "$BODY" '.stages // .pipeline // empty')
  if [ -n "$STAGES" ] && [ "$STAGES" != "null" ]; then
    echo "  Pipeline stages: $STAGES"
  fi
  DISCOVERIES=$(json_field "$BODY" '.discoveries // .discovery_count // empty')
  if [ -n "$DISCOVERIES" ] && [ "$DISCOVERIES" != "null" ]; then
    echo "  Discoveries: $DISCOVERIES"
  fi
elif [ "$HTTP_CODE" = "503" ]; then
  fail "Discovery loop not available (503) — check service wiring"
  echo "  Response: $BODY"
else
  fail "v3 ingest returned HTTP $HTTP_CODE"
  echo "  Response: $BODY"
fi

# ── 8. Accumulation Graph ───────────────────────────────────────────────

section "8. Accumulation Graph"

ACCUM_RESP=$(curl -s "$API/abeyance/accumulation-graph?tenant_id=$TENANT&limit=20" \
  -H "$AUTH")

EDGE_COUNT=$(echo "$ACCUM_RESP" | jq 'if type == "array" then length else 0 end' 2>/dev/null || echo 0)
echo "  Accumulation edges: $EDGE_COUNT"

if [ "$EDGE_COUNT" -gt 0 ]; then
  pass "Accumulation edges exist"
  echo "$ACCUM_RESP" | jq '.[0]' 2>/dev/null
else
  echo "  (No accumulation edges yet — may need more correlated fragments)"
fi

# ── 9. Run Background Discovery Jobs ────────────────────────────────────

section "9. Background Discovery Jobs"

DISC_RESP=$(curl -s -w "\n%{http_code}" -X POST \
  "$API/abeyance/discovery/background?tenant_id=$TENANT" \
  -H "$AUTH")

DISC_CODE=$(echo "$DISC_RESP" | tail -1)
DISC_BODY=$(echo "$DISC_RESP" | sed '$d')

if [ "$DISC_CODE" = "200" ]; then
  pass "Background discovery jobs completed"
  echo "$DISC_BODY" | jq -c '.results' 2>/dev/null || echo "  $DISC_BODY"
elif [ "$DISC_CODE" = "503" ]; then
  fail "Discovery loop not available (503)"
else
  fail "Background discovery returned HTTP $DISC_CODE"
  echo "  $DISC_BODY"
fi

# ── 10. Verify fragment list ────────────────────────────────────────────

section "10. Verify Fragment List (recent)"

LIST_RESP=$(curl -s "$API/abeyance/fragments?tenant_id=$TENANT&limit=5" \
  -H "$AUTH")

LIST_COUNT=$(echo "$LIST_RESP" | jq 'if type == "array" then length else 0 end' 2>/dev/null || echo 0)
assert_gt "$LIST_COUNT" 0 "Fragments returned from list endpoint"
echo "  Recent fragments:"
echo "$LIST_RESP" | jq -c '.[] | {id: .id, source_type: .source_type, snap_status: .snap_status}' 2>/dev/null

# ── Summary ─────────────────────────────────────────────────────────────

section "SUMMARY"

printf "\n  \033[32m%d passed\033[0m, \033[31m%d failed\033[0m\n" "$PASS_COUNT" "$FAIL_COUNT"

if [ ${#FRAGMENT_IDS[@]} -gt 0 ]; then
  echo ""
  echo "  Test fragment IDs (for manual inspection or cleanup):"
  for fid in "${FRAGMENT_IDS[@]}"; do
    echo "    $fid"
  done
fi

echo ""
if [ "$FAIL_COUNT" -gt 0 ]; then
  exit 1
fi
