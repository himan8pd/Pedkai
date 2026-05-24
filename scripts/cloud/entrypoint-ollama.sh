#!/bin/bash
# Ollama container entrypoint — starts the server then auto-imports TSLAM on first run.
set -e

GGUF_FILE="/opt/tslam/tslam-mini-2b-q4km.gguf"
MODEL_NAME="tslam-mini-2b"
MODELFILE="/opt/pedkai/tslam-mini-2b.Modelfile"

ollama serve &
SERVE_PID=$!

echo "[ollama-init] Waiting for server..."
until curl -sf http://localhost:11434/api/tags > /dev/null 2>&1; do
    sleep 2
done
echo "[ollama-init] Server ready."

if ollama list 2>/dev/null | grep -q "^${MODEL_NAME}"; then
    echo "[ollama-init] Model '${MODEL_NAME}' already imported, skipping."
elif [ -f "${GGUF_FILE}" ]; then
    echo "[ollama-init] Importing ${MODEL_NAME} from ${GGUF_FILE} ..."
    ollama create "${MODEL_NAME}" -f "${MODELFILE}"
    echo "[ollama-init] Import complete."
else
    echo "[ollama-init] WARNING: ${GGUF_FILE} not found. Ollama running without model."
    echo "[ollama-init] Upload the GGUF to /opt/tslam/ on the host and restart to import."
fi

# Warm up the model — first inference loads weights into RAM (~30s on ARM).
# Without this, the first real request from the backend would block.
if ollama list 2>/dev/null | grep -q "^${MODEL_NAME}"; then
    echo "[ollama-init] Warming up ${MODEL_NAME} (loading weights into RAM)..."
    curl -sf http://localhost:11434/api/generate \
        -d "{\"model\":\"${MODEL_NAME}\",\"prompt\":\"hello\",\"stream\":false}" \
        > /dev/null 2>&1 && \
        echo "[ollama-init] Warmup complete." || \
        echo "[ollama-init] Warmup failed (model will load on first request)."
fi

wait $SERVE_PID
