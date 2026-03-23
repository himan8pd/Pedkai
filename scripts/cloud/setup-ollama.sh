#!/usr/bin/env bash
# ------------------------------------------------------------------
# setup-ollama.sh — Install Ollama + TSLAM-Mini-2B on Oracle Cloud ARM VM
#
# Usage:  sudo bash setup-ollama.sh
# Prereq: VM 1 (App VM) already provisioned via setup-backend-vm.sh
#
# This script:
#   1. Installs Ollama for ARM64 Linux
#   2. Creates systemd service for auto-start
#   3. Imports TSLAM-Mini-2B model from GGUF
# ------------------------------------------------------------------
set -euo pipefail

MODEL_NAME="tslam-mini-2b"
GGUF_DIR="/opt/tslam"
GGUF_FILE="${GGUF_DIR}/tslam-mini-2b-q4km.gguf"

echo "=== Step 1: Install Ollama ==="
if command -v ollama &>/dev/null; then
    echo "Ollama already installed: $(ollama --version)"
else
    curl -fsSL https://ollama.com/install.sh | sh
    echo "Ollama installed: $(ollama --version)"
fi

echo ""
echo "=== Step 2: Enable and start Ollama service ==="
systemctl enable ollama
systemctl start ollama
sleep 3
systemctl is-active ollama

echo ""
echo "=== Step 3: Prepare model directory ==="
mkdir -p "${GGUF_DIR}"

if [ ! -f "${GGUF_FILE}" ]; then
    echo "ERROR: GGUF file not found at ${GGUF_FILE}"
    echo ""
    echo "Upload the quantized model to the VM first:"
    echo "  scp /Volumes/Projects/TSLAM-Mini-2B/tslam-mini-2b-q4km.gguf ubuntu@<vm-ip>:/tmp/"
    echo "  sudo mv /tmp/tslam-mini-2b-q4km.gguf ${GGUF_FILE}"
    echo ""
    echo "Then re-run this script."
    exit 1
fi

echo "GGUF file found: $(ls -lh ${GGUF_FILE})"

echo ""
echo "=== Step 4: Create Modelfile and import into Ollama ==="
cat > "${GGUF_DIR}/Modelfile" <<'MODELFILE'
FROM ./tslam-mini-2b-q4km.gguf

TEMPLATE """{{ if .System }}<|system|>{{ .System }}<|end|>{{ end }}{{ if .Prompt }}<|user|>{{ .Prompt }}<|end|>{{ end }}<|assistant|>{{ .Response }}<|end|>"""

PARAMETER stop "<|end|>"
PARAMETER stop "<|assistant|>"
PARAMETER stop "<|user|>"
PARAMETER num_ctx 4096
PARAMETER temperature 0.3
PARAMETER top_p 0.9

SYSTEM """You are TSLAM-Mini-2B, a telecom network operations AI assistant. You analyze network alarms, incidents, topology divergences, and performance metrics for NOC engineers. Be concise, technical, and actionable."""
MODELFILE

cd "${GGUF_DIR}"
ollama create "${MODEL_NAME}" -f Modelfile

echo ""
echo "=== Step 5: Verify ==="
ollama list | grep "${MODEL_NAME}"

# Quick smoke test
echo ""
echo "Running smoke test..."
RESULT=$(curl -s http://localhost:11434/api/generate -d "{
  \"model\": \"${MODEL_NAME}\",
  \"prompt\": \"What is a HIGH_TEMPERATURE alarm in telecom?\",
  \"stream\": false
}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('response','FAIL')[:200])" 2>&1)

echo "Smoke test result: ${RESULT}"

echo ""
echo "=== Done ==="
echo "Ollama is running with ${MODEL_NAME} on port 11434."
echo ""
echo "For Docker containers to reach Ollama, set in .env:"
echo "  PEDKAI_LLM_PROVIDER=on-prem"
echo "  PEDKAI_ONPREM_URL=http://host.docker.internal:11434"
echo "  PEDKAI_ONPREM_MODEL=${MODEL_NAME}"
echo "  PEDKAI_ONPREM_EMBED_MODEL=${MODEL_NAME}"
echo ""
echo "If host.docker.internal doesn't resolve, use the VM's private IP instead."
