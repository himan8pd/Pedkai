# Operations Runbook — Periodic Jobs

Operational reference for the Pedkai periodic job subsystem: the runner
(`backend/app/workers/periodic_jobs.py`), the per-job contract, the environment
variables that control each job, the log lines to expect, and the manual-trigger
API equivalents.

> **Implementation status (verified 2026-07-07).** The runner (INF-01) and all
> four job modules — `abeyance_maintenance` (INF-02), `data_retention` (INF-03),
> `abeyance_discovery` (INF-04), and `outcome_calibration` (INF-05) — are
> implemented and merged under `backend/app/workers/jobs/`. The env-var names,
> defaults, and intervals in §3 are verified against those modules.

---

## 1. The job-registry contract

The runner uses **package auto-discovery**. Any module dropped into
`backend/app/workers/jobs/` that exposes a module-level attribute named `JOB`
— an instance of `PeriodicJob` — is discovered and scheduled automatically at
startup. No wiring changes are required to add a job; it is purely file-additive.

`PeriodicJob` (defined in `backend/app/workers/periodic_jobs.py`) is a dataclass
with these fields:

| Field | Type | Meaning |
|-------|------|---------|
| `name` | `str` | Human-readable job name, used in log lines. |
| `interval_seconds` | `int` | Delay between successive `run()` invocations. |
| `enabled` | `bool` | If `False`, the job is discovered but not scheduled. |
| `run` | `Callable[[], Awaitable[None]]` | Async callable invoked on each tick. |

Discovery rules (`discover_jobs()`):

- Every module under the `jobs` package is imported. An import failure is logged
  (`Failed to import periodic job module ...`) and **skipped** — a broken module
  can never crash startup.
- A module without a `JOB` attribute is silently ignored.
- A module whose `JOB` is not a `PeriodicJob` instance is logged
  (`... defines JOB but it is not a PeriodicJob ...`) and skipped.

Each enabled job runs on its own asyncio task in an infinite loop: `run()` is
awaited, any exception it raises is logged and swallowed, then the loop sleeps
`interval_seconds` before the next tick. A raising `run()` therefore does not
kill the job — it is retried on the next tick.

By convention, each job module reads its own interval / enabled flags from
environment variables (see the table in §3) and constructs its `JOB` accordingly.

---

## 2. Global kill switch

```
PEDKAI_PERIODIC_JOBS_ENABLED=false
```

Setting `PEDKAI_PERIODIC_JOBS_ENABLED` to any value other than `true`
(case-insensitive) makes `start_periodic_jobs()` a **no-op**: no jobs are
scheduled, and the runner logs:

```
Periodic jobs disabled via PEDKAI_PERIODIC_JOBS_ENABLED
```

Default (unset) is `true` — the runner is enabled. This switch overrides every
per-job `*_ENABLED` flag: if the global switch is off, nothing runs regardless
of per-job settings.

---

## 3. Job inventory

All five jobs — the runner framework plus the four job modules.

| # | Name | Default interval (s) | Interval env var | Enabled env var (default) | What it does | How to disable |
|---|------|----------------------|------------------|---------------------------|--------------|----------------|
| 1 | `periodic_jobs.py` (runner / **INF-01**) | n/a (framework) | n/a | `PEDKAI_PERIODIC_JOBS_ENABLED` (`true`) | Auto-discovers `JOB` definitions under `workers/jobs/`, schedules each enabled job on its own asyncio task, logs start/stop and per-job errors. Global kill switch for the whole subsystem. | `PEDKAI_PERIODIC_JOBS_ENABLED=false` (disables everything). |
| 2 | `abeyance_maintenance` | `21600` (6 h) | `ABEYANCE_MAINTENANCE_INTERVAL_SECONDS` | `ABEYANCE_MAINTENANCE_ENABLED` (`true`) | Full abeyance maintenance pass — memory decay, pruning, expiry, orphan cleanup. Server-side equivalent of the `POST /abeyance/maintenance` endpoint. | `ABEYANCE_MAINTENANCE_ENABLED=false`, or global switch. |
| 3 | `data_retention` | `86400` (24 h) | `DATA_RETENTION_INTERVAL_SECONDS` | `DATA_RETENTION_ENABLED` (`true`) | Enforces data-retention policy — deletes / ages out records past their retention window (see `backend/app/services/data_retention.py`). | `DATA_RETENTION_ENABLED=false`, or global switch. |
| 4 | `abeyance_discovery` | `21600` (6 h) | `ABEYANCE_DISCOVERY_INTERVAL_SECONDS` | `ABEYANCE_DISCOVERY_ENABLED` (**`false`** — opt-in) | Runs periodic background discovery jobs (ignorance mapping, bridge detection, pattern-conflict scan, causal analysis, pattern compression, counterfactual simulation, evolutionary patterns, hypothesis expiration). Server-side equivalent of `POST /abeyance/discovery/background`. **Disabled by default** — must be explicitly enabled. | Leave `ABEYANCE_DISCOVERY_ENABLED` unset/`false` (default), or global switch. To enable: `ABEYANCE_DISCOVERY_ENABLED=true`. |
| 5 | `outcome_calibration` | `86400` (24 h) | `OUTCOME_CALIBRATION_INTERVAL_SECONDS` | `OUTCOME_CALIBRATION_ENABLED` (`true`) | Recalibrates discovered pattern / hypothesis confidence against observed outcomes (see `backend/app/services/abeyance/discovery/outcome_calibration.py`). | `OUTCOME_CALIBRATION_ENABLED=false`, or global switch. |

**Disabling any job — two levers:**

1. **Per-job:** set that job's `*_ENABLED` env var to `false`. The job is still
   discovered but not scheduled; the runner logs
   `Periodic job '<name>' discovered but disabled; skipping`.
2. **Global:** set `PEDKAI_PERIODIC_JOBS_ENABLED=false`. Nothing is scheduled at
   all. Use this to take the entire subsystem offline (e.g. during a migration).

---

## 4. Log lines to expect

The runner (`backend.app.workers.periodic_jobs`) emits:

**At startup:**

```
Periodic jobs disabled via PEDKAI_PERIODIC_JOBS_ENABLED           # only if global switch is off
Periodic job '<name>' discovered but disabled; skipping           # one per per-job-disabled job
Periodic job '<name>' started (interval=<n>s)                     # one per scheduled job
```

**Discovery failures (non-fatal):**

```
Failed to import periodic job module backend.app.workers.jobs.<mod>
Module backend.app.workers.jobs.<mod> defines JOB but it is not a PeriodicJob (got <type>); skipping
```

**Per-tick runtime error (non-fatal — job retries next tick):**

```
Periodic job '<name>' raised
```

Each job module additionally logs its own **one-line summary** per successful
run (e.g. counts of records decayed / pruned / expired / recalibrated). Grep the
job name to trace an individual job's activity.

**Shutdown:** `stop_periodic_jobs()` cancels and awaits all job tasks; cancellation
is swallowed and does not log by default.

---

## 5. Manual-trigger API equivalents

Two of the jobs have on-demand HTTP endpoints (verified in
`backend/app/api/abeyance.py`; the router is mounted at prefix
`/api/v1/abeyance`, so the full paths are below). Both require an authenticated
user with the `INCIDENT_READ` scope and accept an optional `tenant_id` query
parameter.

| Job | Endpoint (full path) | Source | Notes |
|-----|----------------------|--------|-------|
| `abeyance_maintenance` | `POST /api/v1/abeyance/maintenance` | `abeyance.py:403` (`run_maintenance`) | Runs a full maintenance pass (decay, prune, expire, orphan cleanup) synchronously and returns its result. |
| `abeyance_discovery` | `POST /api/v1/abeyance/discovery/background` | `abeyance.py:460` (`run_discovery_background`) | Runs the background discovery jobs synchronously; returns `{"tenant_id": ..., "results": ...}`. Returns `503` if the discovery loop service is unavailable. |

Use these to force a run without waiting for the next scheduled tick, or when the
corresponding periodic job is disabled. There are no manual endpoints for
`data_retention` or `outcome_calibration`.

---

## Discrepancies (verification against source, 2026-07-07)

- **All four job modules implemented and verified.** `backend/app/workers/jobs/`
  contains `abeyance_maintenance.py` (INF-02), `data_retention.py` (INF-03),
  `abeyance_discovery.py` (INF-04), and `outcome_calibration.py` (INF-05), plus
  the runner `periodic_jobs.py` (INF-01). Every env-var name and default in §3
  was confirmed against these modules on 2026-07-07.
- Note: a `data_retention.py` exists at `backend/app/services/data_retention.py`
  and an `outcome_calibration.py` at
  `backend/app/services/abeyance/discovery/outcome_calibration.py`. These are the
  underlying **service** implementations, not the `workers/jobs/` wrappers that
  expose `JOB`; they do not define a `PeriodicJob`.
- **Runner behaviour, global switch, discovery rules, and log lines** in §1, §2,
  and §4 are all verified directly against
  `backend/app/workers/periodic_jobs.py`.
- **Manual-trigger routes** in §5 are verified against
  `backend/app/api/abeyance.py`. The endpoint paths given in the task
  (`POST /abeyance/maintenance`, `POST /abeyance/discovery/background`) are
  correct relative to the router; the fully-qualified paths include the
  `/api/v1/abeyance` mount prefix (`settings.api_prefix = "/api/v1"`,
  `backend/app/core/config.py:41`).
