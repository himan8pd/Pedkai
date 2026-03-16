# T-VEC / TSLAM Serving Architecture

**Task:** T1.1 -- Model Loading, Serving, Batching, Resource Isolation, Async Integration
**Status:** Design Specification
**Date:** 2026-03-16

---

## 1. Overview

The Abeyance Memory v3.0 enrichment pipeline requires two locally-served models:

| Model | Purpose | Size | Hardware | Output Dim | License |
|-------|---------|------|----------|------------|---------|
| **T-VEC 1.5B** | Embedding generation (semantic, topological, operational) | ~3 GB RAM | CPU only | 1536 | MIT |
| **TSLAM-8B** | Text generation (entity extraction, text summarisation) | ~16 GB VRAM | GPU (preferred) | N/A (text) | Llama 3.1 |
| **TSLAM-4B** | Text generation fallback | ~8 GB VRAM / ~6 GB RAM (quantised) | CPU or GPU | N/A (text) | Llama 3.1 |

Both models run inside the same FastAPI process boundary (or as co-located sidecar processes). Zero cloud LLM dependency. Zero marginal cost per call.

---

## 2. T-VEC 1.5B Serving (Embedding Model)

### 2.1 Model Loading

T-VEC is a SentenceTransformer-compatible model hosted on HuggingFace (`NetoAISolutions/T-VEC`). Loading strategy:

**Lazy singleton with async-safe initialisation:**

```
Global: _tvec_model: Optional[SentenceTransformer] = None
Global: _tvec_lock: asyncio.Lock

async def get_tvec_model() -> SentenceTransformer:
    async with _tvec_lock:
        if _tvec_model is None:
            model = await loop.run_in_executor(
                _tvec_executor,
                lambda: SentenceTransformer("NetoAISolutions/T-VEC")
            )
            _tvec_model = model
    return _tvec_model
```

**Key decisions:**
- Load on first call, not at app startup. Rationale: the FastAPI lifespan runs before workers are ready; a 30-60s model load blocks the startup sequence. Lazy loading allows the health probe to report "loading" state.
- The `asyncio.Lock` prevents concurrent duplicate loads if multiple requests arrive simultaneously during cold start.
- Model files are cached locally by HuggingFace Hub in `~/.cache/huggingface/`. First load downloads ~3 GB; subsequent loads are instant from disk.

**Startup pre-warm (optional):** A background task in the lifespan handler can call `get_tvec_model()` after yield to begin loading without blocking readiness. This is advisory, not blocking.

### 2.2 Inference Wrapping

SentenceTransformer.encode() is a blocking CPU call. It must never run on the asyncio event loop.

**Dedicated ThreadPoolExecutor:**

```
_tvec_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=2,
    thread_name_prefix="tvec"
)
```

Worker count rationale:
- T-VEC on CPU is memory-bound and compute-bound. Each inference occupies ~3 GB resident + per-batch activation memory.
- 2 workers allows one batch to be preparing (tokenising) while another is in the forward pass, without doubling memory pressure.
- On the target VM (12 GB RAM shared with Postgres on VM2, or 12 GB on VM1 shared with Caddy/Kafka/FastAPI), 2 concurrent T-VEC inferences would consume ~7 GB (model shared, activations per-thread). This is the safe ceiling.

**Async interface:**

```python
class TVecService:
    async def embed(self, text: str) -> Optional[list[float]]:
        """Single text -> 1536-dim vector. Returns None on failure."""

    async def embed_batch(self, texts: list[str]) -> list[Optional[list[float]]]:
        """Batch texts -> list of 1536-dim vectors. Per-item failure returns None at that index."""
```

Implementation routes through:
```python
result = await asyncio.get_running_loop().run_in_executor(
    _tvec_executor,
    lambda: model.encode(texts, batch_size=batch_size, normalize_embeddings=True)
)
```

### 2.3 Batch Strategy

SentenceTransformer.encode() natively supports batching. Internal tokenisation and forward pass are vectorised across the batch.

**Micro-batching within a single enrichment call:**

Each fragment enrichment requires 3 T-VEC calls (semantic, topological, operational). These 3 texts are independent and can be batched into a single `model.encode([text_sem, text_topo, text_oper])` call, reducing overhead by ~40% vs 3 serial calls.

**Cross-fragment batching:**

When multiple fragments arrive in a burst (e.g., alarm storm ingestion), a request coalescer can accumulate texts over a short window:

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| `max_batch_size` | 32 | SentenceTransformer throughput plateaus beyond ~32 on CPU |
| `max_wait_ms` | 50 | Latency ceiling for coalescing; most enrichments are single-fragment |
| `coalesce_enabled` | `False` (default) | Enable via env var `TVEC_BATCH_COALESCE=1` for high-throughput ingestion |

Implementation: an `asyncio.Queue` collects `(text, Future)` pairs. A background coroutine drains the queue every `max_wait_ms` or when `max_batch_size` is reached, calls `model.encode(batch)`, and resolves each Future with its corresponding result.

When coalescing is disabled (default), each `embed()` / `embed_batch()` call goes directly to `run_in_executor` without queuing.

### 2.4 Throughput Estimate (CPU)

Based on SentenceTransformer benchmarks for 1.5B parameter models on ARM CPU (Oracle A1, Ampere Altra):

| Scenario | Batch Size | Tokens/text (avg) | Throughput | Latency (p50) |
|----------|------------|-------------------|------------|---------------|
| Single text | 1 | 128 | ~2-3 texts/sec | ~400ms |
| Micro-batch (3 texts per fragment) | 3 | 128 | ~5-7 texts/sec | ~500ms |
| Coalesced batch | 32 | 128 | ~15-20 texts/sec | ~2.0s |

For the enrichment pipeline: 3 T-VEC calls per fragment at ~500ms micro-batched = ~0.5s embedding time per fragment. At steady-state ingestion of 1 fragment/sec, T-VEC utilisation is ~50%. Burst capacity: ~2 fragments/sec sustained, ~4 fragments/sec with coalescing.

These are conservative estimates. Actual numbers depend on the A1 CPU's NEON SIMD throughput with the 1.5B model. Benchmark on target hardware during deployment.

---

## 3. TSLAM-8B Serving (Text Generation Model)

### 3.1 Serving Strategy Selection

TSLAM-8B is a fine-tuned Llama-3.1-8B. For text generation models of this size, three serving options exist:

| Option | Pros | Cons | Verdict |
|--------|------|------|---------|
| **vLLM sidecar** | PagedAttention, continuous batching, OpenAI-compatible API, production-grade | Separate process, needs GPU, 16 GB VRAM minimum | **Primary (GPU path)** |
| **llama.cpp / llama-cpp-python** | CPU-friendly, GGUF quantisation, low VRAM, in-process | Lower throughput than vLLM on GPU, manual batching | **Fallback (CPU path)** |
| **run_in_executor + transformers** | Simple, no sidecar | Blocks a thread, no KV-cache optimisation, poor throughput | Not recommended |

**Decision:** Use vLLM as the primary serving backend for TSLAM-8B when a GPU is available. Use llama-cpp-python (GGUF Q4_K_M quantisation) as the CPU fallback path.

### 3.2 vLLM Integration (GPU Path)

**Deployment:**

vLLM runs as a separate process (sidecar), started before or alongside the FastAPI application. It exposes an OpenAI-compatible HTTP API on a local port.

```
# Startup command (systemd unit or docker-compose service)
python -m vllm.entrypoints.openai.api_server \
    --model NetoAISolutions/TSLAM-8B \
    --port 8100 \
    --max-model-len 4096 \
    --gpu-memory-utilization 0.85 \
    --dtype float16 \
    --disable-log-requests
```

**FastAPI client:**

```python
class TSLAMService:
    def __init__(self):
        self._base_url = os.getenv("TSLAM_VLLM_URL", "http://localhost:8100")
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(connect=5.0, read=30.0, write=5.0, pool=5.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )

    async def generate(self, prompt: str, max_tokens: int = 512, temperature: float = 0.1) -> Optional[str]:
        """Single generation request via OpenAI-compatible API."""

    async def generate_batch(self, prompts: list[str], max_tokens: int = 512) -> list[Optional[str]]:
        """Concurrent generation via asyncio.gather on individual requests.
        vLLM handles batching internally via continuous batching."""
```

Key design points:
- **No run_in_executor needed.** vLLM is accessed over HTTP via httpx.AsyncClient, which is natively async. No thread pool required for TSLAM when using the vLLM path.
- **vLLM handles batching internally.** Continuous batching means concurrent HTTP requests are automatically coalesced into GPU batches. No application-level batching logic needed.
- **Connection pooling** is handled by httpx.Limits. 20 max connections is generous for a localhost sidecar; in practice, TSLAM concurrency is bounded by the enrichment pipeline's parallelism (see Section 6).

### 3.3 vLLM Resource Configuration

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| `--gpu-memory-utilization` | 0.85 | Reserve 15% for CUDA overhead and OS |
| `--max-model-len` | 4096 | Entity extraction prompts are short (~500 tokens input, ~200 tokens output). 4096 is generous. |
| `--dtype` | float16 | Standard for 8B models on consumer/datacenter GPUs with 16+ GB VRAM |
| `--max-num-seqs` | 8 | Max concurrent sequences. Limits memory pressure from KV cache. |
| `--enforce-eager` | (set if GPU < 24 GB) | Disables CUDA graph capture to save VRAM at the cost of ~10% throughput |

### 3.4 Throughput Estimate (GPU)

For TSLAM-8B on a single GPU (e.g., RTX 3090/4090, A10G, L4):

| Scenario | Input tokens | Output tokens | Throughput | Latency (p50) |
|----------|-------------|---------------|------------|---------------|
| Single request (entity extraction) | ~400 | ~150 | ~50-80 tokens/sec output | ~2-3s |
| 4 concurrent requests | ~400 | ~150 | ~150-250 tokens/sec aggregate | ~3-4s |

For enrichment: 1 TSLAM call per fragment (entity extraction) at ~2.5s = ~0.4 fragments/sec on a single request. With 4 concurrent enrichments, ~1.5 fragments/sec. This is adequate for steady-state ingestion.

---

## 4. TSLAM-4B Fallback (CPU Path)

### 4.1 When to Switch

The TSLAM-4B fallback activates under these conditions:

| Condition | Detection Method | Fallback Action |
|-----------|-----------------|-----------------|
| No GPU available at startup | `torch.cuda.is_available() == False` | Start llama-cpp-python with TSLAM-4B GGUF |
| vLLM sidecar unreachable | Health check fails 3 consecutive times | Switch TSLAMService to llama-cpp-python backend |
| vLLM OOM / crash | HTTP 503 or connection refused | Switch TSLAMService to llama-cpp-python backend |
| Explicit configuration | `TSLAM_BACKEND=llama_cpp` env var | Skip vLLM entirely |

**Switching is one-directional within a process lifetime.** Once fallen back to TSLAM-4B, the service does not automatically switch back to vLLM. Rationale: if vLLM crashed due to OOM, restarting it risks the same failure. Recovery requires operator intervention (restart the vLLM sidecar, then restart FastAPI or send a reload signal).

### 4.2 llama-cpp-python Integration

```python
class TSLAMLlamaCppBackend:
    def __init__(self):
        self._model_path = os.getenv(
            "TSLAM_GGUF_PATH",
            "models/tslam-4b-q4_k_m.gguf"
        )
        self._llm = None  # Lazy loaded
        self._lock = asyncio.Lock()
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="tslam-cpu"
        )

    async def _get_model(self):
        async with self._lock:
            if self._llm is None:
                from llama_cpp import Llama
                self._llm = await asyncio.get_running_loop().run_in_executor(
                    self._executor,
                    lambda: Llama(
                        model_path=self._model_path,
                        n_ctx=4096,
                        n_threads=4,  # Leave remaining cores for T-VEC and FastAPI
                        verbose=False,
                    )
                )
        return self._llm

    async def generate(self, prompt: str, max_tokens: int = 512) -> Optional[str]:
        model = await self._get_model()
        result = await asyncio.get_running_loop().run_in_executor(
            self._executor,
            lambda: model(prompt, max_tokens=max_tokens, temperature=0.1)
        )
        return result["choices"][0]["text"]
```

Key decisions:
- **1 worker thread only.** llama-cpp on CPU is not thread-safe for concurrent inference on the same model instance. Serialise all generation through a single thread.
- **n_threads=4:** On a 4-OCPU ARM VM, reserve 4 threads for TSLAM-4B inference, leaving remaining capacity for T-VEC and the event loop. On machines with more cores, increase proportionally.
- **Q4_K_M quantisation:** Best quality/size tradeoff for 4B models. ~2.5 GB on disk, ~3-4 GB resident RAM.

### 4.3 Throughput Estimate (CPU, TSLAM-4B)

| Scenario | Input tokens | Output tokens | Throughput | Latency (p50) |
|----------|-------------|---------------|------------|---------------|
| Single request (entity extraction) | ~400 | ~150 | ~8-12 tokens/sec output | ~12-18s |

This is significantly slower than GPU TSLAM-8B. At 15s per entity extraction, fragment enrichment throughput drops to ~0.07 fragments/sec (one every ~15s). Acceptable for low-volume environments or degraded operation, not for burst ingestion.

---

## 5. Connection Pooling and Request Queuing

### 5.1 Architecture Overview

```
                    +------------------+
  Enrichment ------>| TVecService      |----> ThreadPoolExecutor(2) ----> SentenceTransformer
  Chain             | (in-process)     |      (CPU-bound)
                    +------------------+

                    +------------------+
  Enrichment ------>| TSLAMService     |----> httpx.AsyncClient ---------> vLLM sidecar (GPU)
  Chain             | (facade)         |      (async HTTP, no threads)
                    |                  |
                    |  [fallback]      |----> ThreadPoolExecutor(1) ----> llama-cpp (CPU)
                    +------------------+
```

### 5.2 Request Queuing

**T-VEC queuing:** The ThreadPoolExecutor with `max_workers=2` implicitly queues requests. When both workers are busy, subsequent `run_in_executor` calls queue in the executor's internal unbounded FIFO. This is acceptable because:
- T-VEC latency is low (~500ms per micro-batch), so queue depth stays shallow.
- If queue depth becomes a concern, wrap with an `asyncio.Semaphore(max_concurrent_tvec_requests)` to apply backpressure to the enrichment pipeline.

**TSLAM queuing (vLLM path):** vLLM's continuous batching handles queuing internally. The httpx connection pool (20 connections) bounds the maximum concurrent in-flight requests. Beyond 20 concurrent requests, httpx will queue at the connection pool level. In practice, the enrichment pipeline's own concurrency limiter (Section 6) prevents this.

**TSLAM queuing (llama-cpp path):** The single-threaded executor serialises all requests. Queue depth can grow during bursts. Mitigation: an `asyncio.Semaphore(4)` in the TSLAMService facade limits the number of waiting callers. Beyond 4, the enrichment pipeline receives backpressure (the semaphore acquire blocks the coroutine).

### 5.3 Backpressure Design

The enrichment pipeline must not queue unbounded work against the model services. The following semaphores gate concurrency:

| Semaphore | Default Value | Controls |
|-----------|---------------|----------|
| `TVEC_CONCURRENCY` | 4 | Max concurrent T-VEC embed calls (queued beyond this) |
| `TSLAM_CONCURRENCY` | 8 (vLLM) / 2 (llama-cpp) | Max concurrent TSLAM generate calls |
| `ENRICHMENT_CONCURRENCY` | 4 | Max fragments being enriched in parallel |

`ENRICHMENT_CONCURRENCY` is the outer bound. Even if T-VEC and TSLAM semaphores allow more, at most 4 fragments undergo enrichment simultaneously. This prevents memory exhaustion from too many partially-enriched fragments in flight.

### 5.4 Timeout Policy

| Operation | Timeout | Action on Timeout |
|-----------|---------|-------------------|
| T-VEC single embed | 10s | Return None, set mask=FALSE for that dimension |
| T-VEC batch embed | 30s | Return None for entire batch, set masks=FALSE |
| TSLAM generate (vLLM) | 30s | Return None, fall back to regex entity extraction |
| TSLAM generate (llama-cpp) | 60s | Return None, fall back to regex entity extraction |
| Model loading (either) | 120s | Raise, health check reports NOT_READY |

Timeouts are implemented via `asyncio.wait_for()` wrapping the `run_in_executor` or `httpx` call.

---

## 6. Resource Isolation

### 6.1 CPU vs GPU Separation

T-VEC (CPU) and TSLAM-8B (GPU via vLLM) are naturally isolated:

- **T-VEC** runs in-process in a dedicated `ThreadPoolExecutor("tvec")`. It consumes CPU cores and RAM. It does not touch the GPU.
- **TSLAM-8B via vLLM** runs as a separate OS process. It consumes GPU VRAM and a small amount of CPU for preprocessing. Its CPU footprint is negligible relative to T-VEC.
- **TSLAM-4B via llama-cpp** runs in-process in a dedicated `ThreadPoolExecutor("tslam-cpu")`. This DOES compete with T-VEC for CPU.

### 6.2 CPU Contention Mitigation (Fallback Mode)

When both T-VEC and TSLAM-4B run on CPU:

| Resource | T-VEC Allocation | TSLAM-4B Allocation | Remaining |
|----------|-----------------|---------------------|-----------|
| CPU threads | 2 (executor workers) | 4 (n_threads in llama-cpp) | FastAPI event loop, OS |
| RAM | ~3 GB (model) + ~0.5 GB (activations) | ~4 GB (GGUF Q4_K_M) | ~4.5 GB on 12 GB VM |

On the 4-OCPU Oracle ARM VM, this means:
- T-VEC and TSLAM-4B will time-share CPU cores. Performance degrades for both.
- `ENRICHMENT_CONCURRENCY` should be reduced to 2 in CPU-only mode to prevent thrashing.
- The `TSLAM_CONCURRENCY` semaphore is automatically set to 2 (not 8) when the llama-cpp backend is active.

### 6.3 Memory Isolation

- T-VEC model weights are loaded once (shared across threads via GIL-protected read-only access). Per-inference activation memory is ~200-500 MB depending on batch size.
- TSLAM-8B via vLLM: separate process, separate memory space. No shared state.
- TSLAM-4B via llama-cpp: separate thread, but shares process memory. The GGUF file is mmap'd, so the OS can page it if under memory pressure.

### 6.4 Process Affinity (Optional, Production Hardening)

On Linux/ARM (Oracle Cloud), `taskset` or cgroup CPU affinity can pin:
- T-VEC executor threads to cores 0-1
- TSLAM-4B llama-cpp threads to cores 2-3
- FastAPI event loop to core 0 (shared with T-VEC; event loop is I/O-bound, not CPU-bound)

This is optional and should be configured via systemd unit files, not in application code.

---

## 7. Async Integration

### 7.1 Event Loop Safety

**Invariant: No blocking call ever runs on the asyncio event loop.**

| Operation | Blocking? | Wrapping |
|-----------|-----------|----------|
| T-VEC model load | Yes (30-60s) | `run_in_executor(_tvec_executor, ...)` |
| T-VEC inference | Yes (0.1-2s) | `run_in_executor(_tvec_executor, ...)` |
| TSLAM vLLM HTTP call | No (native async) | Direct `await httpx_client.post(...)` |
| TSLAM llama-cpp inference | Yes (2-60s) | `run_in_executor(_tslam_executor, ...)` |
| TSLAM llama-cpp model load | Yes (5-30s) | `run_in_executor(_tslam_executor, ...)` |

### 7.2 Service Interface Contract

Both services expose the same async interface to the enrichment chain:

```python
# Embedding service (T-VEC)
class TVecService:
    async def embed(self, text: str) -> Optional[list[float]]
    async def embed_batch(self, texts: list[str]) -> list[Optional[list[float]]]
    async def health(self) -> dict  # {"status": "ready"|"loading"|"error", "model": "T-VEC-1.5B", ...}

# Generation service (TSLAM)
class TSLAMService:
    async def generate(self, prompt: str, max_tokens: int = 512, temperature: float = 0.1) -> Optional[str]
    async def generate_structured(self, prompt: str, schema: dict, max_tokens: int = 512) -> Optional[dict]
    async def health(self) -> dict  # {"status": "ready"|"loading"|"error"|"fallback", "model": "TSLAM-8B"|"TSLAM-4B", "backend": "vllm"|"llama_cpp"}
```

The enrichment chain calls these interfaces. It never imports SentenceTransformer, vLLM, or llama-cpp directly. This allows backend swapping without changing the enrichment logic.

### 7.3 Dependency Injection

Services are instantiated in the FastAPI lifespan and stored on `app.state`:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ... existing startup ...

    # Model services (lazy-loaded internally, but registered here)
    app.state.tvec_service = TVecService()
    app.state.tslam_service = TSLAMService()

    # Optional: pre-warm in background (non-blocking)
    asyncio.create_task(_prewarm_models(app.state.tvec_service, app.state.tslam_service))

    yield

    # Shutdown: cleanup executors
    app.state.tvec_service.shutdown()
    app.state.tslam_service.shutdown()
```

The enrichment chain receives these services via constructor injection (matching the existing `llm_service` parameter pattern in `EnrichmentChain.__init__`):

```python
chain = EnrichmentChain(
    provenance=provenance_logger,
    llm_service=app.state.tslam_service,      # replaces old cloud LLM
    embedding_service=app.state.tvec_service,  # new: dedicated embedding service
    shadow_topology=shadow_topo_service,
)
```

### 7.4 Replacing Existing Services

The current codebase has:
- `EmbeddingService` (Gemini cloud API with MiniLM-L6-v2 local fallback) in `backend/app/services/embedding_service.py`
- `LocalEmbeddingService` (MiniLM-L6-v2, 384-dim) in `backend/app/services/embedding_local.py`

These are used by the non-abeyance parts of the application (decision traces, autonomous actions). They are NOT replaced by T-VEC. The T-VEC service is exclusively for the Abeyance Memory subsystem. The two embedding services coexist:

| Service | Consumer | Model | Dimensions |
|---------|----------|-------|------------|
| `EmbeddingService` / `LocalEmbeddingService` | Decision traces, autonomous actions | Gemini / MiniLM-L6-v2 | 768 / 384 |
| `TVecService` | Abeyance Memory enrichment chain | T-VEC 1.5B | 1536 |

Similarly, the existing `LLMService` (cloud LLM via `llm_adapter.py`) continues to serve the explanation/reasoning layer. `TSLAMService` is exclusively for Abeyance Memory entity extraction.

---

## 8. Health Checks and Readiness Probes

### 8.1 Per-Model Health

Each service exposes a `health()` method returning a structured status:

```python
{
    "status": "ready" | "loading" | "error" | "not_configured",
    "model": "T-VEC-1.5B",
    "backend": "sentence_transformers",
    "load_time_seconds": 42.3,       # Time taken to load model (null if not yet loaded)
    "last_inference_at": "2026-...",  # ISO timestamp of last successful inference
    "total_inferences": 1234,        # Counter since process start
    "error_count": 2,                # Errors since process start
    "last_error": "...",             # Last error message (null if none)
}
```

TSLAM health additionally includes:

```python
{
    "status": "ready" | "loading" | "error" | "fallback",
    "model": "TSLAM-8B",
    "backend": "vllm" | "llama_cpp",
    "vllm_url": "http://localhost:8100",  # Only when backend=vllm
    "fallback_reason": "vLLM unreachable after 3 retries",  # Only when status=fallback
}
```

### 8.2 API Endpoint

A dedicated health endpoint aggregates both model statuses:

```
GET /api/v1/abeyance/models/health

Response:
{
    "tvec": { ... },
    "tslam": { ... },
    "overall": "ready" | "degraded" | "unavailable"
}
```

**Overall status logic:**
- `ready`: both T-VEC and TSLAM report `ready`
- `degraded`: T-VEC is `ready` but TSLAM is in `fallback` (TSLAM-4B on CPU), OR either model has `error_count > 0` in the last 5 minutes
- `unavailable`: T-VEC is `error` or `loading` (no embeddings possible = no enrichment possible)

Note: TSLAM being unavailable does NOT make the system `unavailable`. Entity extraction falls back to regex (existing behaviour). Only T-VEC unavailability blocks enrichment (embeddings cannot be computed).

### 8.3 Kubernetes/Systemd Probes

For the Oracle Cloud deployment (systemd, not Kubernetes), health is checked by:
1. The Caddy reverse proxy's health check (`/api/v1/health` existing endpoint).
2. A dedicated systemd timer that curls `/api/v1/abeyance/models/health` and logs warnings if `overall != "ready"`.

If Kubernetes is adopted later, map to:
- **Liveness:** `/api/v1/health` (existing; process alive)
- **Readiness:** `/api/v1/abeyance/models/health` with `overall != "unavailable"` (accepts `degraded`)
- **Startup:** `/api/v1/abeyance/models/health` with `tvec.status == "ready"` (wait for model load)

---

## 9. Failure Modes

### 9.1 Model OOM

**T-VEC OOM (CPU/RAM):**
- Symptom: `MemoryError` or OS OOM killer terminates the FastAPI process.
- Prevention: `ENRICHMENT_CONCURRENCY` semaphore limits concurrent activations. With batch_size=32 max and 2 executor workers, peak T-VEC RAM is ~4.5 GB (model 3 GB + 2 x 0.75 GB activations). On the 12 GB VM, this leaves ~7.5 GB for everything else.
- Recovery: If OOM kills the process, systemd restarts it. On restart, the `ENRICHMENT_CONCURRENCY` can be automatically reduced by setting `TVEC_MAX_BATCH_SIZE` lower.
- Detection: Monitor RSS via `/proc/self/status` and log warnings at 80% of available RAM.

**TSLAM-8B OOM (GPU/VRAM):**
- Symptom: vLLM returns HTTP 503 or the sidecar process crashes.
- Prevention: `--gpu-memory-utilization 0.85` and `--max-num-seqs 8` bound VRAM usage.
- Recovery: TSLAMService detects 3 consecutive health check failures and switches to TSLAM-4B llama-cpp backend. vLLM sidecar must be manually restarted by operator.
- Detection: vLLM logs CUDA OOM errors. The TSLAMService health endpoint reports `status: "fallback"`.

**TSLAM-4B OOM (CPU/RAM, fallback mode):**
- Symptom: `MemoryError` when loading GGUF file.
- Prevention: TSLAM-4B Q4_K_M is ~2.5 GB on disk, ~3-4 GB resident. Combined with T-VEC (~3.5 GB), total is ~7 GB. On 12 GB VM, this is tight but feasible.
- Recovery: If OOM, TSLAMService reports `status: "error"`. Entity extraction falls back to regex-only (no LLM entity extraction). Enrichment continues with degraded quality.

### 9.2 Model Loading Failure

| Failure | Cause | Handling |
|---------|-------|----------|
| T-VEC model not found | HuggingFace cache miss + no internet | Health reports `error`. Enrichment chain cannot produce embeddings. All mask flags = FALSE, embedding columns = NULL. System logs CRITICAL. |
| T-VEC model corrupted | Partial download, disk error | Same as above. Delete `~/.cache/huggingface/...T-VEC...` and retry. |
| TSLAM GGUF not found | File path misconfigured | Health reports `error`. Entity extraction falls back to regex. |
| vLLM fails to start | Wrong model path, CUDA version mismatch | TSLAMService detects via health check, falls back to llama-cpp. |

**Partial availability is acceptable.** The enrichment chain is designed to handle per-dimension failures (mask=FALSE, column=NULL). A fragment with no semantic embedding but valid topological embedding is still stored and participatable in snap scoring (with reduced weight on the missing dimension).

### 9.3 Inference Timeout

Handled by `asyncio.wait_for()` with the timeout policy from Section 5.4.

On timeout:
1. The `run_in_executor` future is NOT cancelled (Python ThreadPoolExecutor does not support cancelling running threads). The thread completes eventually and its result is discarded.
2. The calling coroutine receives `None` and sets the corresponding mask to `FALSE`.
3. A warning is logged with the text length and timeout duration.
4. A metrics counter `tvec_timeout_total` / `tslam_timeout_total` is incremented for monitoring.

**Repeated timeouts:** If the timeout counter exceeds 10 in a 5-minute window, the health endpoint reports `degraded` and a structured log event is emitted for alerting. This may indicate the model is stuck (e.g., infinite loop in tokenisation, deadlocked thread).

### 9.4 vLLM Sidecar Crash/Restart

If the vLLM process exits unexpectedly:
1. TSLAMService's next HTTP request gets `ConnectionRefused`.
2. After 3 consecutive connection failures (with 2-second intervals), TSLAMService switches to llama-cpp fallback.
3. Health endpoint reports `status: "fallback", fallback_reason: "vLLM unreachable"`.
4. If vLLM is restarted externally, a manual API call `POST /api/v1/abeyance/models/reset-tslam` re-checks vLLM availability and switches back if reachable.

---

## 10. Configuration Reference

All configuration is via environment variables, consistent with the existing Pedkai config pattern (`backend/app/core/config.py`).

| Variable | Default | Description |
|----------|---------|-------------|
| `TVEC_MODEL_NAME` | `NetoAISolutions/T-VEC` | HuggingFace model ID for T-VEC |
| `TVEC_MAX_WORKERS` | `2` | ThreadPoolExecutor worker count |
| `TVEC_MAX_BATCH_SIZE` | `32` | Max texts per encode() call |
| `TVEC_BATCH_COALESCE` | `0` | Enable cross-request batching (0=off, 1=on) |
| `TVEC_COALESCE_WAIT_MS` | `50` | Max wait time for batch coalescing |
| `TVEC_TIMEOUT_SECONDS` | `10` | Per-call inference timeout |
| `TVEC_CONCURRENCY` | `4` | Max concurrent embed calls (semaphore) |
| `TSLAM_BACKEND` | `auto` | `auto` (try vLLM then llama-cpp), `vllm`, `llama_cpp` |
| `TSLAM_VLLM_URL` | `http://localhost:8100` | vLLM sidecar URL |
| `TSLAM_GGUF_PATH` | `models/tslam-4b-q4_k_m.gguf` | Path to TSLAM-4B GGUF file |
| `TSLAM_LLAMA_CPP_THREADS` | `4` | n_threads for llama-cpp inference |
| `TSLAM_TIMEOUT_SECONDS` | `30` (vLLM) / `60` (llama-cpp) | Per-call generation timeout |
| `TSLAM_CONCURRENCY` | `8` (vLLM) / `2` (llama-cpp) | Max concurrent generate calls (semaphore) |
| `ENRICHMENT_CONCURRENCY` | `4` | Max fragments enriched in parallel |

---

## 11. Startup Sequence

```
1. FastAPI lifespan begins
2. Existing services start (event bus, consumer, executor, sleeping cell)
3. TVecService() instantiated (no model loaded yet)
4. TSLAMService() instantiated (no model loaded yet, backend=auto)
5. Background pre-warm task created:
   a. TVecService: calls get_tvec_model() -> downloads/loads T-VEC (~30-60s)
   b. TSLAMService: pings vLLM health endpoint
      - If reachable: backend=vllm, status=ready
      - If unreachable: loads TSLAM-4B GGUF via llama-cpp (~10-30s)
6. Health endpoint responds:
   - During step 5: overall=unavailable (T-VEC loading)
   - After T-VEC loaded: overall=ready or overall=degraded (if TSLAM fell back)
7. Enrichment chain accepts requests
   - If T-VEC not yet loaded, first enrichment triggers synchronous load (blocks that request, not the event loop)
```

---

## 12. Shutdown Sequence

```
1. FastAPI lifespan exit
2. TVecService.shutdown():
   a. Shutdown _tvec_executor (wait=True, allow in-flight to complete)
   b. Release model reference (GC reclaims ~3 GB)
3. TSLAMService.shutdown():
   a. If llama-cpp backend: shutdown _tslam_executor, release model
   b. If vLLM backend: close httpx client (vLLM sidecar lifecycle managed externally)
4. Existing services shut down
```

---

## 13. Migration from Current Embedding Architecture

The current codebase uses:
- `EmbeddingService` -> Gemini cloud API (768-dim) or `LocalEmbeddingService` -> MiniLM-L6-v2 (384-dim)
- `LLMService` -> Cloud LLM via `llm_adapter.py`

For the Abeyance Memory subsystem:
1. `EnrichmentChain.__init__` gains a new `embedding_service` parameter (type: `TVecService`).
2. The existing `llm_service` parameter type changes from the cloud `LLMService` to `TSLAMService`.
3. `_compute_embeddings()` calls `embedding_service.embed_batch()` instead of constructing hash-based embeddings.
4. `_llm_extract_entities()` calls `llm_service.generate_structured()` instead of the cloud LLM.
5. `_regex_extract_entities()` remains as the fallback when TSLAM is unavailable.
6. Embedding dimensions change: SEMANTIC_DIM=1536, TOPOLOGICAL_DIM=1536, OPERATIONAL_DIM=1536 (all T-VEC native dim). TEMPORAL_DIM=256 (unchanged, sinusoidal).

The non-abeyance embedding and LLM services (`EmbeddingService`, `LLMService`) are untouched.

---

## Appendix A: Decision Log

| Decision | Alternatives Considered | Rationale |
|----------|------------------------|-----------|
| Lazy model loading (not startup) | Eager load in lifespan | 30-60s blocking startup unacceptable; lazy with background pre-warm gives best of both |
| vLLM sidecar (not in-process) | transformers in-process, TGI | vLLM continuous batching is critical for GPU utilisation; sidecar isolates GPU memory from FastAPI process |
| llama-cpp-python for CPU fallback (not ONNX, not ctransformers) | ONNX Runtime, ctransformers | llama-cpp has the best ARM CPU support, GGUF ecosystem, and active maintenance |
| Dedicated executors per model (not shared) | Single shared ThreadPoolExecutor | Prevents T-VEC and TSLAM-4B from starving each other; allows independent tuning |
| Semaphore-based backpressure (not queue depth limits) | Bounded queues with rejection | Semaphores integrate cleanly with asyncio; the enrichment pipeline can await without exception handling for queue-full |
| One-directional fallback (no auto-recovery to vLLM) | Auto-retry vLLM periodically | OOM crashes are likely to recur; manual recovery is safer than retry loops |
