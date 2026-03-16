# T2.4 — Telemetry Aligner: Remove Hash Fallback

**Task:** T2.4
**Phase:** 2 — Code Bug Remediation
**Addresses:** F-3.3 (Severe)
**File:** `backend/app/services/abeyance/telemetry_aligner.py`
**Generated:** 2026-03-16

---

## Problem Statement

Finding F-3.3 (Severe): In the current implementation, `embed_anomaly()` contains a
`loop.is_running()` guard that was intended to detect a blocking context before calling
an async embedding service. In async FastAPI, `loop.is_running()` is always `True` at
every call site. The consequence is that the async branch always takes the `if
loop.is_running()` early-exit path, silently returning `_hash_embedding(text)` without
ever reaching the real embedding service.

The hash embedding path (`_hash_embedding`) produces a 64-dimensional pseudo-random
vector seeded from the text SHA-256 hash. This vector is semantically meaningless:
it has no spatial relationship to any text embedding model's output space. Any fragment
stored with a hash embedding will produce nonsense cosine similarity scores against all
other fragments in cold storage.

This is not a degraded mode — it is a silent correctness failure. The system appears
to function (no exception, no log error at WARNING or above after the first warning) but
produces incoherent retrieval for every telemetry fragment in production.

The v2.0 design explicitly removed the hash fallback. The code re-introduced it during
implementation without tracking the invariant.

---

## Root Cause (Precise)

```python
# Current embed_anomaly() — lines 82–89
if asyncio.iscoroutinefunction(self._embedding_service.generate_embedding):
    loop = asyncio.get_event_loop()
    if loop.is_running():          # <-- always True in FastAPI async context
        logger.warning("async embedding service can't block; using fallback embedding")
        return self._hash_embedding(text)   # <-- always reached
```

`asyncio.get_event_loop().is_running()` is always `True` inside any coroutine running
under an active event loop, which is the runtime state for every FastAPI route handler
and every background task started via `asyncio.create_task`. The `else` branch
(`loop.run_until_complete(...)`) is structurally unreachable in production.

---

## What Must Be Removed

The following must be deleted entirely from `telemetry_aligner.py`:

1. **The `_hash_embedding` method** (lines 105–111). No callers outside
   `embed_anomaly` exist. After removal of `embed_anomaly`'s fallback path, this
   method has no call site and no legitimate use.

2. **The entire `loop.is_running()` guard block** in `embed_anomaly` (lines 82–89
   inclusive). This includes the `asyncio` import inside `embed_anomaly`, the
   `asyncio.iscoroutinefunction` branch, the `get_event_loop()` call, and the
   `_hash_embedding` invocation.

3. **The `loop.run_until_complete(...)` branch** (lines 91–95). This branch was
   unreachable in production and is superseded by the T-VEC integration point below.

4. **The `numpy` dependency on the embedding path.** `np.array(result, dtype=float)`
   conversion remains necessary only if the T-VEC serving layer returns a raw list.
   The `_hash_embedding` method's use of `np.random`, `rng.standard_normal`, and
   vector normalization must be removed in full. If `numpy` is no longer used anywhere
   else in the file after this removal, the `import numpy as np` at module level must
   also be removed.

---

## T-VEC Integration Point Specification

### Caller Contract

`TelemetryAligner` must be initialised with a T-VEC client that exposes an async
`generate_embedding` coroutine. The serving layer itself is designed in T1.1 and is
out of scope for this task. This specification defines only what `TelemetryAligner`
requires from that layer.

**Required interface (structural, not a hard import):**

```python
class TVecClient(Protocol):
    async def generate_embedding(self, text: str) -> list[float] | None:
        """Return embedding vector, or None if the serving layer is unavailable."""
        ...
```

The return type is either:
- A `list[float]` of dimensionality matching the model configured in T1.1 (e.g. 768
  for a 768-dim T-VEC model). The exact dimensionality is an operational parameter
  owned by T1.1 and must not be hard-coded in `TelemetryAligner`.
- `None` when the serving layer has declared itself unavailable (circuit open,
  model not loaded, etc.).

### Revised `__init__` Signature

```python
def __init__(self, tvec_client=None):
    """
    Args:
        tvec_client: Async T-VEC embedding client implementing generate_embedding().
                     If None, TelemetryAligner operates in text-only mode:
                     store_anomaly_fragment() sets embedding=None and
                     embedding_valid=False on every fragment.
    """
    self._tvec_client = tvec_client
```

The parameter is renamed from `embedding_service` to `tvec_client` to make the
dependency on the T-VEC serving layer explicit and prevent accidental injection of a
different embedding service that does not follow the T-VEC contract.

### Revised `embed_anomaly` Signature and Semantics

```python
async def embed_anomaly(self, anomaly: AnomalyFinding) -> tuple[list[float] | None, bool]:
    """Convert anomaly text to T-VEC embedding.

    Returns:
        (embedding, valid) where:
          - embedding is list[float] from T-VEC, or None if unavailable.
          - valid is True iff embedding is present and semantically usable.

    Never returns a zero-filled vector. Never returns a hash-based vector.
    If T-VEC is unavailable, returns (None, False).
    """
```

`embed_anomaly` becomes a coroutine (`async def`) because it must `await` the T-VEC
call directly on the running event loop. The synchronous adapter pattern
(`run_until_complete`, `run_in_executor` wrapping the async call) must not be used:
it is incompatible with FastAPI's event loop and was the root cause of F-3.3.

### Failure Path: T-VEC Unavailable

The failure path has exactly two causes:

1. `self._tvec_client is None` — no client was injected at construction time.
2. `self._tvec_client.generate_embedding(text)` raises any exception, or returns
   `None`.

In both cases the return value is `(None, False)`. There is no third path.

**What must not happen:**
- A zero-filled vector (`np.zeros(dim)`) must not be returned. A zero vector has a
  cosine similarity of zero against everything and a cosine similarity of NaN against
  itself (0/0 after normalisation). It corrupts any ranking that uses it.
- A hash-based pseudo-random vector must not be returned. It is semantically
  meaningless in the T-VEC embedding space.
- An exception must not propagate out of `embed_anomaly`. Embedding failure is
  expected operational behaviour (network partition, model reload). Callers handle
  it via the `valid` flag.

Exception handling inside `embed_anomaly`:

```python
try:
    result = await self._tvec_client.generate_embedding(text)
    if result is None:
        logger.warning("T-VEC returned None for telemetry embedding; fragment will be unembedded")
        return None, False
    return list(result), True
except Exception as exc:
    logger.warning("T-VEC unavailable during telemetry alignment: %s", exc)
    return None, False
```

### Revised `store_anomaly_fragment` Semantics

`store_anomaly_fragment` must become a coroutine (`async def`) because it calls
`embed_anomaly`.

When `embed_anomaly` returns `(None, False)`, the fragment must be stored with:
- `embedding = None` — not an empty list, not zeros, not a hash vector.
- `embedding_valid = False` — the mask field defined in the enrichment chain
  specification (task T1.3 scope).

The fragment is stored in this unembedded state. It is retained for provenance and
decay purposes. It participates in entity-based and temporal searches. It must not
participate in cosine similarity searches. Enforcement of that exclusion is the
responsibility of the cold storage query layer (T1.1/T1.3 scope), not `TelemetryAligner`.

The `store_anomaly_fragment` return type does not change: it still returns
`AbeyanceFragment`.

---

## Invariants After Remediation

| Invariant | Statement |
|-----------|-----------|
| INV-TA-1 | `embed_anomaly` never returns a hash-based vector under any execution path. |
| INV-TA-2 | `embed_anomaly` never returns a zero-filled vector under any execution path. |
| INV-TA-3 | `embed_anomaly` never raises an exception to its caller regardless of T-VEC state. |
| INV-TA-4 | `embed_anomaly` returns `(None, False)` whenever T-VEC is unavailable; the caller decides what to do with the fragment. |
| INV-TA-5 | `_hash_embedding` does not exist in the codebase after this remediation. |
| INV-TA-6 | `embed_anomaly` is a coroutine (`async def`) and must be awaited by all callers. |

---

## Out of Scope for This Task

The following are explicitly not specified here:

- **T-VEC serving layer design** (connection pooling, circuit breaker, model loading,
  request batching, caching) — owned by T1.1.
- **Enrichment chain integration** (how `embedding_valid` propagates through the
  enrichment pipeline) — owned by T1.3.
- **Cold storage query exclusion** (how fragments with `embedding=None` are excluded
  from cosine similarity searches) — owned by T1.1.
- **Backfill strategy** for existing fragments stored with hash embeddings. Those
  fragments have corrupted embeddings and must be identified and re-embedded or
  expired; that is an operational migration, not a code change.

---

## Changes to Existing Public Interface

| Method | Before | After |
|--------|--------|-------|
| `__init__(embedding_service=None)` | sync, accepts any embedding object | sync, parameter renamed `tvec_client=None`; semantics narrowed to T-VEC contract |
| `embed_anomaly(anomaly)` | sync, returns `np.ndarray` always | async, returns `tuple[list[float] \| None, bool]` |
| `store_anomaly_fragment(anomaly, storage=None)` | sync, returns `AbeyanceFragment` | async, returns `AbeyanceFragment`; embedding field may be None |
| `_hash_embedding(text, dim=64)` | private, returns `np.ndarray` | **deleted** |

All call sites that currently call `embed_anomaly` or `store_anomaly_fragment`
synchronously must be updated to `await` these methods. No call sites outside
`telemetry_aligner.py` are known at time of writing (the codebase support document
shows no external callers), but the change must be verified before merging.

---

## Test Impact

Tests that inject a mock `embedding_service` and verify that `embed_anomaly` returns
a non-None `np.ndarray` will fail after this remediation. They must be updated to:

1. Inject a mock `tvec_client` (async, implements `generate_embedding`).
2. `await` the call to `embed_anomaly`.
3. Assert on `(list[float], True)` for the success path.
4. Assert on `(None, False)` for the T-VEC-unavailable path (inject a client that
   raises, or inject `None` as the client).

No test should pass a mock that returns a hash-based or zero-filled vector and assert
that the result is accepted. If such a test exists, it must be deleted.
