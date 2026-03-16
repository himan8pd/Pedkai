# T2.5 — Decay Engine: Accelerated Decay Interface

**Task:** T2.5
**Phase:** 2 — Core Engine Reconstruction
**Generated:** 2026-03-16
**Status:** Specification complete — ready for implementation

---

## 1. Purpose and Scope

### 1.1 Problem Statement

Finding F-4.4 (Moderate) from the v2 forensic audit:

> No negative evidence mechanism to mark fragments as irrelevant beyond time-based decay. The system can only corroborate or snap; no operator-driven reclassification or accelerated decay for investigated non-relevant evidence.

The current `DecayEngine` is time-only: a fragment's decay score is a deterministic function of its age, source type, and near-miss count. There is no path for an external signal — human operator judgment, automated diagnostic pipeline, or Phase 3's Negative Evidence mechanism — to inform the decay engine that a fragment has been investigated and found irrelevant.

This means fragments that are known irrelevant survive in the ACTIVE/NEAR_MISS pool and continue to pollute snap evaluations until natural time-based decay clears them. At typical `TICKET_TEXT` tau of 270 days, a fragment found irrelevant on day 10 remains materially present for months.

### 1.2 This Task: Interface Only

This specification adds the **interface** by which external callers accelerate a fragment's decay. It does not design who calls the interface or under what logic. That is Phase 3 T3.3 (Negative Evidence mechanism).

Concretely, this task defines:

- `apply_accelerated_decay(fragment_id, acceleration_factor, reason, provenance)` — the new public method on `DecayEngine`
- The acceleration model (how `acceleration_factor` maps to a new score)
- Bounding constraints on `acceleration_factor`
- Provenance contract (what gets logged, mandatory fields)
- Invariant preservation analysis (monotonicity, boundedness, tenant isolation)
- Failure modes and their handling

### 1.3 Out of Scope

The following are explicitly NOT part of this task:

- The Negative Evidence ingestion pathway (Phase 3 T3.3)
- Any UI or API endpoint for operator-triggered acceleration
- Changes to `run_decay_pass` scheduling or batch logic
- Changes to `apply_near_miss_boost`
- The `FragmentHistoryORM` schema (assumed sufficient; assessed in §7)

---

## 2. Conceptual Model

### 2.1 What "Accelerated Decay" Means

Exponential decay at rate `1/tau` governs the baseline trajectory. An `acceleration_factor` of `k` means the fragment is treated as if it has aged `k` times faster than it actually has. Formally, the effective age used for score computation becomes:

```
effective_age_days = actual_age_days * acceleration_factor
```

This maps cleanly to the existing formula:

```
decay_score = base_relevance * boost_factor * exp(-effective_age_days / tau)
            = base_relevance * boost_factor * exp(-actual_age_days * k / tau)
            = base_relevance * boost_factor * exp(-actual_age_days / (tau / k))
```

Acceleration is equivalent to using a compressed time constant `tau_eff = tau / k`.

This framing has two important properties:

1. **Continuity**: The result is still a valid exponential decay score, satisfying INV-8 (output in `[0.0, 1.0]`) by the same clamping already in `compute_decay_score`.
2. **Interpretability**: An operator or audit trail reader can understand the effect as "this fragment was treated as `k` times older than it is."

### 2.2 Acceleration Factor Bounds

The factor is bounded to the range `[MIN_ACCELERATION_FACTOR, MAX_ACCELERATION_FACTOR]`.

| Constant | Value | Rationale |
|---|---|---|
| `MIN_ACCELERATION_FACTOR` | `2.0` | Below 2x has negligible effect; caller should not call for trivial adjustments |
| `MAX_ACCELERATION_FACTOR` | `10.0` | 10x compresses even a 270-day TICKET_TEXT tau to 27 days effective; sufficient for any operational need without the risks of instant expiration |

**Why not allow 1.0?** A factor of 1.0 is a no-op and indicates a caller logic error. It is rejected.

**Why not allow arbitrarily large values?** Arbitrary values (e.g., 1000x) effectively force immediate expiration without giving the fragment a chance to be observed in a low-but-nonzero state. This bypasses the natural expiration pipeline and could be abused to retroactively eliminate fragments from audit trails. The 10x cap ensures the mechanism is a decay accelerator, not an instant-delete button.

**Why not allow fractional values (< 1.0)?** A factor below 1.0 would decelerate decay (make a fragment appear younger than it is). This would reverse the natural decay trajectory, violating INV-2 monotonicity. It is rejected by the validation logic.

### 2.3 Monotonicity Preservation

The existing `run_decay_pass` enforces INV-2 via:

```python
new_score = min(new_score, old_score)
```

The accelerated decay method must make the same guarantee. The computed accelerated score will be lower than the natural score (because `effective_age > actual_age`), so it will trivially be `<= old_score`. The method explicitly clamps `new_score = min(new_score, frag.current_decay_score)` after computation as a defense-in-depth measure, identical to the pattern in `run_decay_pass`.

**Important edge case**: If a near-miss boost was applied between the last decay pass and this accelerated decay call, `old_score` may be higher than the natural trajectory. The accelerated decay method must still preserve the monotonicity invariant relative to `current_decay_score` at the time of the call. It does not need to retroactively correct for boost history.

---

## 3. Method Specification

### 3.1 Signature

```python
async def apply_accelerated_decay(
    self,
    session: AsyncSession,
    fragment_id: UUID,
    tenant_id: str,
    acceleration_factor: float,
    reason: str,
    provenance: AcceleratedDecayProvenance,
) -> AcceleratedDecayResult:
```

### 3.2 Parameters

| Parameter | Type | Constraints | Description |
|---|---|---|---|
| `session` | `AsyncSession` | Required | SQLAlchemy async session; caller owns transaction boundary |
| `fragment_id` | `UUID` | Required | ID of the fragment to accelerate |
| `tenant_id` | `str` | Required | Tenant owning the fragment; enforces INV-7 |
| `acceleration_factor` | `float` | `[2.0, 10.0]` inclusive | How many times faster the fragment should decay |
| `reason` | `str` | Non-empty, max 500 chars | Human-readable reason for acceleration; stored verbatim in provenance log |
| `provenance` | `AcceleratedDecayProvenance` | Required; see §3.3 | Structured provenance block: who, what subsystem, trace reference |

### 3.3 AcceleratedDecayProvenance Dataclass

```python
@dataclass
class AcceleratedDecayProvenance:
    triggered_by: str          # "OPERATOR:<user_id>" | "SYSTEM:<subsystem_name>"
    subsystem: str             # e.g., "NegativeEvidence", "OperatorAPI", "DiagnosticPipeline"
    trace_id: Optional[str]    # Optional correlation ID linking to originating event/request
    external_reference: Optional[str]  # Optional ticket/incident ID for human-triggered calls
```

**Field rules:**

- `triggered_by` must match pattern `(OPERATOR|SYSTEM):[a-zA-Z0-9_\-]{1,128}`. Callers that do not conform receive a `ValueError` at validation time, not a database error.
- `subsystem` is a free string, max 128 characters, non-empty. It is the Phase 3 mechanism's identity.
- `trace_id` and `external_reference` are optional. When supplied, they must be non-empty strings if present (empty string is treated as `None`).

### 3.4 AcceleratedDecayResult Dataclass

```python
@dataclass
class AcceleratedDecayResult:
    fragment_id: UUID
    tenant_id: str
    old_score: float
    new_score: float
    old_status: str
    new_status: str
    effective_age_days: float     # actual_age * acceleration_factor
    actual_age_days: float
    acceleration_factor: float
    applied_at: datetime          # UTC timestamp of application
    skipped: bool                 # True if fragment not found or already expired
    skip_reason: Optional[str]    # Populated when skipped=True
```

Returning a typed result rather than a bare float aligns with the provenance and audit requirements: the caller (especially Phase 3 T3.3) needs to know the old and new states to construct its own downstream logic.

### 3.5 New Constants

```python
MIN_ACCELERATION_FACTOR: float = 2.0
MAX_ACCELERATION_FACTOR: float = 10.0
```

These are module-level constants in `decay_engine.py`, alongside existing constants.

---

## 4. Algorithm

```
function apply_accelerated_decay(session, fragment_id, tenant_id,
                                  acceleration_factor, reason, provenance):

  1. VALIDATE inputs
     a. acceleration_factor in [MIN_ACCELERATION_FACTOR, MAX_ACCELERATION_FACTOR]
        → raise ValueError if not
     b. reason is non-empty string, len <= 500
        → raise ValueError if not
     c. provenance.triggered_by matches pattern (OPERATOR|SYSTEM):[...]
        → raise ValueError if not
     d. provenance.subsystem is non-empty, len <= 128
        → raise ValueError if not

  2. FETCH fragment
     SELECT ... WHERE id = fragment_id AND tenant_id = tenant_id  // INV-7
     → if not found: return AcceleratedDecayResult(skipped=True,
                        skip_reason="FRAGMENT_NOT_FOUND")

  3. GUARD: reject non-actionable states
     if snap_status in ("EXPIRED", "SNAPPED"):
        → return AcceleratedDecayResult(skipped=True,
               skip_reason="STATUS_NOT_ACCELERATABLE:<status>")
     // No-op. These fragments are already terminal.
     // Caller should not be attempting acceleration on them.

  4. COMPUTE accelerated score
     now = datetime.now(UTC)
     event_time = frag.event_timestamp or frag.created_at
     actual_age_days = max(0.0, (now - event_time).total_seconds() / 86400.0)
     effective_age_days = actual_age_days * acceleration_factor

     new_score = compute_decay_score(
         base_relevance  = frag.base_relevance,
         near_miss_count = frag.near_miss_count,
         age_days        = effective_age_days,   // <-- effective, not actual
         source_type     = frag.source_type or "ALARM",
     )
     // compute_decay_score already clamps output to [0.0, 1.0] (INV-8)

  5. ENFORCE monotonicity (INV-2 defense-in-depth)
     new_score = min(new_score, frag.current_decay_score)
     // Accelerated score must not exceed current score.
     // (This should always be true given effective_age > actual_age,
     //  but the explicit clamp defends against floating-point edge cases.)

  6. DETERMINE new status
     Apply same threshold logic as run_decay_pass:
       if new_score < EXPIRATION_THRESHOLD → try EXPIRED transition
       elif new_score < STALE_THRESHOLD    → try STALE transition
     Use VALID_TRANSITIONS lookup; if transition not permitted, keep old status.

  7. PERSIST
     frag.current_decay_score = new_score
     frag.snap_status = new_status
     frag.updated_at = now

  8. LOG PROVENANCE (INV-10)
     await self._provenance.log_state_change(session, FragmentStateChange(
         fragment_id   = fragment_id,
         tenant_id     = tenant_id,
         event_type    = "ACCELERATED_DECAY",
         old_state     = { "decay_score": old_score, "status": old_status },
         new_state     = { "decay_score": new_score, "status": new_status },
         event_detail  = {
             "acceleration_factor":  acceleration_factor,
             "actual_age_days":      round(actual_age_days, 4),
             "effective_age_days":   round(effective_age_days, 4),
             "reason":               reason,
             "triggered_by":         provenance.triggered_by,
             "subsystem":            provenance.subsystem,
             "trace_id":             provenance.trace_id,
             "external_reference":   provenance.external_reference,
         },
     ))

  9. FLUSH
     await session.flush()
     // session.flush() (not commit): caller owns the transaction.
     // This is consistent with apply_near_miss_boost.

  10. NOTIFY (INV-12: after PostgreSQL persist, best-effort)
      await self._notifier.notify_accelerated_decay(tenant_id, fragment_id,
                                                     old_score, new_score)

  11. RETURN AcceleratedDecayResult(
          fragment_id       = fragment_id,
          tenant_id         = tenant_id,
          old_score         = old_score,
          new_score         = new_score,
          old_status        = old_status,
          new_status        = new_status,
          effective_age_days = effective_age_days,
          actual_age_days   = actual_age_days,
          acceleration_factor = acceleration_factor,
          applied_at        = now,
          skipped           = False,
          skip_reason       = None,
      )
```

---

## 5. Invariant Analysis

### 5.1 INV-2: Monotonic Decay

**Claim:** `apply_accelerated_decay` never increases a fragment's decay score.

**Proof sketch:**
- `effective_age_days = actual_age_days * acceleration_factor`
- `acceleration_factor >= MIN_ACCELERATION_FACTOR = 2.0`, so `effective_age_days >= 2 * actual_age_days`
- `compute_decay_score` is strictly decreasing in `age_days` (exponential with negative exponent)
- Therefore `compute_decay_score(..., effective_age_days, ...) <= compute_decay_score(..., actual_age_days, ...)`
- The natural score at `actual_age_days` is already `<= old_score` (enforced by `run_decay_pass`)
- The accelerated score is `<= natural score <= old_score`
- Step 5 of the algorithm applies `min(new_score, frag.current_decay_score)` as defense-in-depth

**INV-2 preserved.** Monotonicity holds.

### 5.2 INV-3 / INV-8: Bounded Domains

- `compute_decay_score` clamps output to `[0.0, 1.0]` (existing behavior, unchanged)
- `acceleration_factor` is validated to `[2.0, 10.0]` before reaching the computation
- No arithmetic path produces out-of-bounds scores

**INV-3 and INV-8 preserved.**

### 5.3 INV-6: Hard Lifetime and Idle Bounds

The accelerated decay method computes a score based on effective age. It does NOT bypass or disable the hard lifetime and idle expiration checks in `run_decay_pass`. Those checks run independently on the next scheduled decay pass.

However: if a caller supplies an `acceleration_factor` that drives `effective_age_days` beyond `max_lifetime_days`, the computed score will be very close to zero (but not forced to exactly zero the way `run_decay_pass` forces it). The next `run_decay_pass` will then observe `actual_age_days > max_lifetime_days` (or not) independently.

**Design decision:** The accelerated decay method does NOT replicate the hard lifetime override (`new_score = 0.0 if age > max_lifetime`). That override is a maintenance-pass concern. The accelerated decay interface is a scoring adjustment, not a lifecycle management tool.

**INV-6 preserved** (no lifetime/idle check is removed; scheduled maintenance still runs).

### 5.4 INV-7: Tenant Isolation

The SELECT query includes `AND tenant_id = tenant_id` exactly as `apply_near_miss_boost` does. Cross-tenant calls return `skipped=True, skip_reason="FRAGMENT_NOT_FOUND"` (no information leakage about whether the fragment exists in another tenant).

**INV-7 preserved.**

### 5.5 INV-10: Provenance

The `event_detail` block logged to `FragmentHistoryORM` via `ProvenanceLogger` captures:

- `acceleration_factor` — numeric, bounded
- `actual_age_days` — pre-acceleration age at time of call
- `effective_age_days` — age used for score computation
- `reason` — human-readable explanation
- `triggered_by` — typed identifier of the caller (human or system)
- `subsystem` — which subsystem triggered the acceleration
- `trace_id` — optional correlation to originating event
- `external_reference` — optional link to ticket or incident

This is sufficient for an auditor to reconstruct: who triggered the acceleration, what factor was applied, what the score moved from and to, and why.

**INV-10 preserved and extended.**

### 5.6 INV-12: Notification Order

Redis notification via `self._notifier.notify_accelerated_decay(...)` is called after `session.flush()`, which persists to PostgreSQL within the caller's transaction. This matches the existing pattern in `apply_near_miss_boost` and `run_decay_pass`.

**INV-12 preserved.**

---

## 6. Failure Modes

| Failure | Detection Point | Handling | Observable Signal |
|---|---|---|---|
| `acceleration_factor` out of range | Validation, step 1a | `ValueError` raised before DB touch | Exception propagates to caller |
| `reason` empty or too long | Validation, step 1b | `ValueError` raised before DB touch | Exception propagates to caller |
| `provenance.triggered_by` malformed | Validation, step 1c | `ValueError` raised before DB touch | Exception propagates to caller |
| Fragment not found (or wrong tenant) | SELECT, step 2 | Return `skipped=True, skip_reason="FRAGMENT_NOT_FOUND"` | Caller inspects result |
| Fragment in terminal state (EXPIRED, SNAPPED) | Guard, step 3 | Return `skipped=True, skip_reason="STATUS_NOT_ACCELERATABLE:<status>"` | Caller inspects result |
| `compute_decay_score` returns out-of-range value | Step 5 `min()` clamp | Defends INV-2; value already clamped by `compute_decay_score` itself | No observable error |
| `session.flush()` fails | Step 9 | Exception propagates to caller; no partial state written to DB | Caller's transaction rollback |
| Redis notification fails | Step 10 | Log warning, swallow exception (best-effort, same as existing methods) | Log entry only |

### 6.1 What This Method Does Not Handle

- **Batch acceleration**: This method operates on a single fragment. A caller needing to accelerate many fragments (e.g., a diagnostic sweep) calls it in a loop, potentially within a single database transaction if the caller manages that.
- **Idempotency**: Calling this method twice with the same arguments applies acceleration twice. The second call will see a lower `old_score` (from the first call) and compute an even lower score from the already-accelerated position. This is not a bug — it is the correct behavior for repeated negative evidence signals. Callers that want idempotency must check the result's `old_score` and decide whether to proceed.

---

## 7. Schema and Provenance Infrastructure

### 7.1 FragmentHistoryORM

The method logs via `ProvenanceLogger.log_state_change(session, FragmentStateChange(...))` with `event_type="ACCELERATED_DECAY"`. This is a new event type alongside existing types ("DECAY_UPDATE", "NEAR_MISS").

`FragmentHistoryORM.event_detail` is a JSONB column. The new `event_detail` fields are additive; no schema migration is required.

The new `event_type` value `"ACCELERATED_DECAY"` must be added to any enumeration or allowlist that validates `event_type` values in `FragmentHistoryORM` or `ProvenanceLogger`. If `event_type` is a free string (no constraint), no change is needed.

**Action for implementer:** Check `FragmentHistoryORM` definition and `ProvenanceLogger.log_state_change` for event_type validation. Add `"ACCELERATED_DECAY"` to any enum or CHECK constraint.

### 7.2 RedisNotifier

The method calls `self._notifier.notify_accelerated_decay(tenant_id, fragment_id, old_score, new_score)`. This is a new notification method. The implementer must add this method to `RedisNotifier` (or its interface/stub) alongside existing methods `notify_decay_batch` and similar.

The method should be best-effort (log-and-swallow on failure), matching the pattern of existing notifier calls.

---

## 8. Interface Placement

The new method, the two new dataclasses (`AcceleratedDecayProvenance`, `AcceleratedDecayResult`), and the two new constants (`MIN_ACCELERATION_FACTOR`, `MAX_ACCELERATION_FACTOR`) all live in:

```
backend/app/services/abeyance/decay_engine.py
```

No new files are required. The dataclasses are defined at module level (not nested in the class), following the pattern of `FragmentStateChange` in `events.py`.

---

## 9. Phase 3 T3.3 Consumption Contract

This section is informational for the Phase 3 implementer.

Phase 3 T3.3 (Negative Evidence mechanism) will call `apply_accelerated_decay`. The expected call pattern is:

```python
result = await decay_engine.apply_accelerated_decay(
    session=session,
    fragment_id=fragment_id,
    tenant_id=tenant_id,
    acceleration_factor=<determined by negative evidence strength>,
    reason=<natural language description of the negative evidence event>,
    provenance=AcceleratedDecayProvenance(
        triggered_by="SYSTEM:NegativeEvidence",
        subsystem="NegativeEvidence",
        trace_id=<correlation_id from the originating event>,
        external_reference=None,
    ),
)
if result.skipped:
    # log and continue; do not treat as error
    ...
```

The `acceleration_factor` selected by T3.3 must be in `[2.0, 10.0]`. T3.3 is responsible for mapping the strength or confidence of negative evidence to a specific factor value. Suggested guidance (not enforced by this interface):

| Negative Evidence Strength | Suggested Factor |
|---|---|
| Weak (correlated but not conclusive) | 2.0 – 3.0 |
| Moderate (investigated, not relevant) | 4.0 – 6.0 |
| Strong (definitively ruled out) | 7.0 – 10.0 |

---

## 10. Implementation Checklist

Items that must be completed for this specification to be fully implemented:

- [ ] Define `AcceleratedDecayProvenance` dataclass in `decay_engine.py`
- [ ] Define `AcceleratedDecayResult` dataclass in `decay_engine.py`
- [ ] Add `MIN_ACCELERATION_FACTOR = 2.0` constant to `decay_engine.py`
- [ ] Add `MAX_ACCELERATION_FACTOR = 10.0` constant to `decay_engine.py`
- [ ] Implement `DecayEngine.apply_accelerated_decay(...)` following algorithm in §4
- [ ] Add `notify_accelerated_decay(tenant_id, fragment_id, old_score, new_score)` to `RedisNotifier` (best-effort, log-and-swallow)
- [ ] Verify `"ACCELERATED_DECAY"` is a valid `event_type` value in `FragmentHistoryORM` / `ProvenanceLogger`; add to enum/constraint if needed
- [ ] Unit tests:
  - [ ] Factor below minimum raises `ValueError`
  - [ ] Factor above maximum raises `ValueError`
  - [ ] Factor = 5.0, young fragment: new score strictly less than old score
  - [ ] Factor = 10.0, old fragment near expiration threshold: transitions to EXPIRED
  - [ ] Fragment not found: returns `skipped=True`
  - [ ] Fragment in EXPIRED state: returns `skipped=True, skip_reason="STATUS_NOT_ACCELERATABLE:EXPIRED"`
  - [ ] Fragment in SNAPPED state: returns `skipped=True, skip_reason="STATUS_NOT_ACCELERATABLE:SNAPPED"`
  - [ ] Provenance log entry contains all required fields
  - [ ] Monotonicity invariant: result.new_score <= result.old_score for all valid inputs
  - [ ] Tenant isolation: cross-tenant call returns `skipped=True` (no 500, no data leak)
