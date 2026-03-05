# Telco2 Historic-Mode Implementation Brief

**Date:** 2026-03-04
**Author:** Engineering (handoff note for fresh implementation thread)
**Status:** Ready for implementation
**Prerequisite reading:** `docs/TELCO2_SCHEMA_ALIGNMENT_ANALYSIS.md`, `docs/TELCO2_HISTORIC_MODE_PLAN.md`

---

## Context

Pedkai has a full Telco2 dataset loaded into its production PostgreSQL (:5432) and TimescaleDB (:5433) databases under `tenant_id = 'pedkai_telco2_01'`. The dataset represents a realistic Indonesian converged operator with 784K network entities, 57M KPI time-series rows, 633K customers, 1.66M topology edges, 15K network alarms, and rich supplementary data (scenarios, divergence manifests, neighbour relations, etc.).

The data was bulk-loaded by `backend/app/scripts/load_telco2_tenant.py` directly into the database — exactly as a real customer would provide historical data for evaluation. Pedkai must now demonstrate its full feature set against this historical dataset in a **historic analysis / live-demo mode**.

The frontend is accessible. Auth works. Tenant selection works (`pedkai_telco2_01` is the sole tenant, auto-bound on login). But most pages are empty or broken because of ORM column mismatches and because downstream tables (incidents, decision_traces) were never populated — the bulk-loaded alarms were never processed through Pedkai's intelligence pipeline.

This brief describes every change needed, in priority order, with exact file paths, exact column names, and exact SQL. There is no ambiguity — implement exactly what is described here.

---

## Current Database State

### Tenant Configuration (already done — do NOT redo)

The `tenants` table has been fixed. It has:
- One row: `id='pedkai_telco2_01'`, `display_name='Telco2 — Indonesian Converged Operator'`, `is_active=true`
- The column was renamed from `name` to `display_name` and widened to `varchar(200)` to match `TenantORM`
- The `id` column was widened from `varchar(36)` to `varchar(100)` to match `TenantORM`

The `user_tenant_access` table has been created with 4 rows (one per user → `pedkai_telco2_01`).

All 4 users (admin, operator, shift_lead, engineer) can log in and are bound to `pedkai_telco2_01`.

**Do not touch the tenants table, user_tenant_access table, or users table.**

### Data Tables with Rows (tenant_id = 'pedkai_telco2_01')

| Table | Database | Rows | Has ORM |
|---|---|---|---|
| `network_entities` | Graph :5432 | 784,048 | Yes — `NetworkEntityORM` (column mismatch) |
| `topology_relationships` | Graph :5432 | 1,660,086 | Yes — `EntityRelationshipORM` |
| `entity_relationships` | Graph :5432 | 1,649,735 | No (bonus data, not blocking) |
| `customers` | Graph :5432 | 633,188 | Yes — `CustomerORM` |
| `bss_billing_accounts` | Graph :5432 | ~633K | Yes — `BillingAccountORM` (no tenant_id column) |
| `bss_service_plans` | Graph :5432 | unique plans | Yes — `ServicePlanORM` (no tenant_id column) |
| `telco_events_alarms` | Graph :5432 | 15,341 | **No** — raw DDL, no ORM |
| `scenario_manifest` | Graph :5432 | 7,181 | No |
| `scenario_kpi_overrides` | Graph :5432 | 6,407,752 | No |
| `divergence_manifest` | Graph :5432 | 459,769 | No |
| `gt_network_entities` | Graph :5432 | 811,064 | No |
| `gt_entity_relationships` | Graph :5432 | 1,970,387 | No |
| `neighbour_relations` | Graph :5432 | 926,475 | No |
| `vendor_naming_map` | Graph :5432 | 226 | No |
| `kpi_dataset_registry` | Graph :5432 | 6 | No |
| `kpi_metrics` | Metrics :5433 | 57,669,010 | Yes — `KPIMetricORM` (column mismatch) |

### Empty Downstream Tables (tenant_id = 'pedkai_telco2_01')

| Table | Database | Rows | Why Empty |
|---|---|---|---|
| `incidents` | Graph :5432 | **0** | Alarms were bulk-loaded, never processed through ingestion pipeline |
| `decision_traces` | Graph :5432 | **0** | Same reason — no alarm correlation ran |
| `action_executions` | Graph :5432 | **0** | No incidents → no autonomous actions |
| `security_events` | Graph :5432 | **0** | This table holds cybersecurity events (CasinoLimit domain); Telco2 has network alarms instead |

### Two Event Tables — This Is Correct, Not a Bug

`security_events` and `telco_events_alarms` are **different event domains**, not per-tenant tables:

- **`security_events`**: Cybersecurity detections (MITRE ATT&CK shaped — `technique_id`, `technique_name`, `machine_name`, `audit_event_ids`). Populated by the CasinoLimit security demo. Any tenant's security events would go here.
- **`telco_events_alarms`**: Network alarms (TMF-shaped — `alarm_type`, `severity`, `raised_at`, `cleared_at`, `probable_cause`, `domain`, `correlation_group_id`). Populated by the Telco2 data loader. Any tenant's network alarms would go here.

A real converged operator will have BOTH types simultaneously. The SSE alarm stream, alarm correlation engine, and incident creation pipeline must consume from both tables. The `tenant_id` column within each table provides multi-tenant isolation. Future work: the synthetic data generator should produce both security events and network alarms for every tenant.

### Telco2 Alarm Data Shape (reference for backfill script)

```sql
-- telco_events_alarms columns:
--   alarm_id (text PK), tenant_id (text), entity_id (text), entity_type (text),
--   alarm_type (text), severity (text), raised_at (timestamptz), cleared_at (timestamptz),
--   source_system (text), probable_cause (text), domain (text), scenario_id (text),
--   is_synthetic_scenario (boolean), additional_text (text), correlation_group_id (text),
--   created_at (timestamptz)

-- Sample row:
-- alarm_id:    'cf7e2218-afb5-42ba-a42b-316f21d81f39'
-- tenant_id:   'pedkai_telco2_01'
-- entity_id:   '89d5d39e-6549-40f7-b7cb-95cc800b99bb'
-- entity_type: (nullable)
-- alarm_type:  'RACH_FAILURE'
-- severity:    'minor'
-- raised_at:   '2024-01-30 23:31:00+00'
-- cleared_at:  (nullable)
-- source_system: (nullable)
-- probable_cause: (nullable)
-- domain:      (nullable)
-- scenario_id: (nullable)
-- is_synthetic_scenario: false
-- additional_text: (nullable)
-- correlation_group_id: (nullable)
```

### KPI Metrics Data Shape on TimescaleDB (reference for ORM fix)

```sql
-- kpi_metrics columns on TimescaleDB :5433:
--   timestamp (timestamptz NOT NULL)
--   tenant_id (varchar(64) NOT NULL, default 'default')
--   entity_id (varchar(128) NOT NULL)
--   metric_name (varchar(128) NOT NULL)
--   metric_value (double precision NOT NULL)    ← ORM expects 'value'
--   metadata (jsonb, default '{}')              ← ORM expects 'tags'
```

### Network Entities Data Shape (reference for ORM fix)

```sql
-- network_entities columns on Graph DB :5432:
--   id (uuid PK, default gen_random_uuid())
--   tenant_id (varchar(255) NOT NULL)
--   entity_type (varchar(50) NOT NULL)
--   name (varchar(255) NOT NULL)
--   external_id (varchar(255))
--   latitude (double precision)                 ← ORM expects 'geo_lat'
--   longitude (double precision)                ← ORM expects 'geo_lon'
--   operational_status (varchar(50))            ← ORM missing
--   created_at (timestamptz, default now())
--   updated_at (timestamptz)                    ← ORM missing
--   attributes (jsonb NOT NULL)                 ← ORM missing
-- Note: ORM has revenue_weight, sla_tier, embedding_provider, embedding_model,
--       last_seen_at — these columns do NOT exist in the DB.
```

### Customers Data Shape (reference for data_retention.py fix)

```sql
-- customers columns on Graph DB :5432:
--   id (uuid PK)
--   external_id (varchar(100) NOT NULL, UNIQUE)
--   name (varchar(255))
--   churn_risk_score (double precision)
--   associated_site_id (varchar(255))
--   tenant_id (varchar(50))
--   created_at (timestamp)
-- Note: there is NO msisdn_hash, email, or phone column.
-- The CustomerORM also has consent_proactive_comms (boolean) which may or
-- may not exist in the DB depending on migration state.
```

---

## Implementation Items (Priority Order)

### 1. Fix `KPIMetricORM` Column Mapping

**Priority:** P0 — blocks TMF628, sleeping cell, capacity engine
**File:** `backend/app/models/kpi_orm.py`
**Effort:** 10 minutes

The DB has `metric_value` and `metadata`. The ORM has `value` and `tags`. Use SQLAlchemy's `Column("db_column_name", ..., key="orm_attribute_name")` pattern so the ORM attribute name stays as `value`/`tags` (preserving all downstream Python code) but SQLAlchemy generates SQL with the correct DB column names.

**Current code (lines ~46-51):**
```python
# Metric value
value = Column(Float, nullable=False)

# Additional context
tags = Column(JSONB, nullable=False, default=dict)
```

**Change to:**
```python
# Metric value — DB column is 'metric_value', ORM attribute is 'value'
value = Column("metric_value", Float, nullable=False, key="value")

# Additional context — DB column is 'metadata', ORM attribute is 'tags'
tags = Column("metadata", JSONB, nullable=False, default=dict, key="tags")
```

This means all Python code (`r.value`, `r.tags`, `KPIMetricORM.value`, etc.) continues to work unchanged. SQLAlchemy translates to `metric_value` and `metadata` in SQL.

**Downstream files that use `.value` and `.tags` — verify they still work (they should, no changes needed):**
- `backend/app/api/tmf628.py` — `r.value` (line ~66)
- `backend/app/services/capacity_engine.py` — `.value`
- `backend/app/services/rl_evaluator.py` — `.value`
- `backend/app/services/sleeping_cell_detector.py` — `.value` (after fix #5 below)

**Also fix the `__table_args__` index:** The existing index `ix_kpi_metrics_timestamp` on `"timestamp"` should still work. But verify the composite PK columns use DB column names. The PK is `(tenant_id, entity_id, timestamp, metric_name)` — these column names match between ORM and DB, so no issue there.

---

### 2. Fix SSE Alarm Stream to Query Both Event Tables

**Priority:** P0 — blocks dashboard alarm feed
**File:** `backend/app/api/sse.py`
**Effort:** 10 minutes
**Status:** A UNION has already been applied in a previous session. Verify it is correct.

The SSE endpoint (`alarm_event_generator` function, around line 86) originally queried only `security_events`. It now needs to UNION `security_events` and `telco_events_alarms` with column mapping. Both are legitimate event domain tables (security vs network), not per-tenant tables. Any tenant may have data in either or both. The `tenant_id` filter applies to both.

**The UNION query should be (verify this is what's currently in the file):**
```sql
SELECT id, specific_problem, perceived_severity,
       alarmed_object_id, event_time
FROM (
    SELECT id, technique_name AS specific_problem,
           severity AS perceived_severity,
           machine_name AS alarmed_object_id,
           detected_at AS event_time
    FROM security_events
    WHERE tenant_id = :tid
    UNION ALL
    SELECT alarm_id AS id, alarm_type AS specific_problem,
           severity AS perceived_severity,
           entity_id AS alarmed_object_id,
           raised_at AS event_time
    FROM telco_events_alarms
    WHERE tenant_id = :tid
) combined
ORDER BY event_time DESC
LIMIT 20
```

If this is already applied, just verify correctness and move on.

---

### 3. Fix Dashboard Scorecard Auth Token

**Priority:** P1 — scorecard cards show N/A even when data exists
**File:** `frontend/app/dashboard/page.tsx`
**Effort:** 5 minutes

The dashboard page fetches the scorecard with a hardcoded `Authorization: "Bearer guest"` (around line 28-33). This fails auth silently. The real token is available from `useAuth()` — the component already destructures `tenantId` from it but doesn't use `token` for the scorecard fetch.

**Current code (approximately):**
```typescript
const scRes = await fetch(
  `${API_BASE_URL}/api/v1/autonomous/scorecard`,
  {
    headers: { Authorization: "Bearer guest" },
  },
).catch(() => null);
```

**Change to:**
```typescript
const scRes = await fetch(
  `${API_BASE_URL}/api/v1/autonomous/scorecard`,
  {
    headers: { Authorization: `Bearer ${token}` },
  },
).catch(() => null);
```

And destructure `token` alongside `tenantId` from `useAuth()`:
```typescript
const { tenantId, token } = useAuth();
```

Also move the scorecard fetch inside the SSE `useEffect` (or a separate effect that depends on `token`) so it doesn't fire before auth is ready.

---

### 4. Historic Backfill Script — Process Loaded Alarms into Incidents

**Priority:** P0-CRITICAL — without this, 4 out of 5 frontend pages are empty
**New file:** `backend/app/scripts/backfill_incidents_from_alarms.py`
**Effort:** 2-3 hours

This is the biggest piece. The 15,341 alarms in `telco_events_alarms` need to be processed through Pedkai's alarm correlation engine to produce `incidents` and `decision_traces`. This is exactly what a real customer would expect: "feed Pedkai my history and let it show me what it finds."

#### Design

The script should:

1. Read alarms from `telco_events_alarms` WHERE `tenant_id = 'pedkai_telco2_01'`, ordered by `raised_at ASC`
2. Feed them in batches through `AlarmCorrelationService.correlate_alarms()` (the same correlation engine used by the live pipeline in `backend/app/workers/handlers.py`)
3. For each resulting cluster, create an `IncidentORM` record (using `create_incident_from_cluster` from `backend/app/services/incident_service.py`, or directly constructing `IncidentORM` instances)
4. For each alarm, also create a `DecisionTraceORM` record so the TMF642 API, alarm clusters endpoint, and noise wall have data
5. Commit in batches (e.g. every 500 alarms)
6. Print a summary at the end

#### Key implementation details

**Batching strategy:** The alarm correlation service uses a 5-minute temporal window (`TEMPORAL_WINDOW_MINUTES = 5` in `alarm_correlation.py`). Process alarms in temporal order. Group alarms into 5-minute windows, feed each window to `correlate_alarms()`, and create incidents from the resulting clusters.

**Incident creation:** Use the existing severity-to-ITIL mapping from `backend/app/schemas/incidents.py`:
```python
from backend.app.schemas.incidents import SEVERITY_TO_ITIL, IncidentSeverity
# Map alarm severity to ITIL priority
severity_str = alarm_row.severity or "minor"
itil = SEVERITY_TO_ITIL.get(severity_str, SEVERITY_TO_ITIL["minor"])
impact, urgency, priority = itil
```

Set `IncidentORM.impact`, `IncidentORM.urgency`, and `IncidentORM.priority` accordingly.

**Decision traces:** For each alarm, create a `DecisionTraceORM` with:
- `id`: new UUID
- `tenant_id`: `'pedkai_telco2_01'`
- `trigger_type`: `'alarm'` or `'EXTERNAL_ALARM'`
- `trigger_id`: the `alarm_id` from `telco_events_alarms`
- `trigger_description`: the `alarm_type` + `probable_cause`
- `entity_id`: the `entity_id` from the alarm
- `entity_type`: the `entity_type` from the alarm (or `'NETWORK_ELEMENT'`)
- `decision_summary`: Something meaningful like `"Historic alarm: {alarm_type} on entity {entity_id}"`
- `domain`: `'anops'`
- `severity`: from the alarm
- `status`: `'raised'` (or `'cleared'` if `cleared_at IS NOT NULL`)
- `ack_state`: `'unacknowledged'`
- `created_at`: the `raised_at` from the alarm (preserve historical timestamps)
- `confidence_score`: 0.7 (reasonable default for historic correlation)

**Check `DecisionTraceORM` columns** before implementing — read the full model in `backend/app/models/decision_trace_orm.py`. It has fields like `title`, `decision_summary`, `tradeoff_rationale`, `action_taken`, `decision_maker`, `probable_cause`, `external_correlation_id`, `internal_correlation_id`, `feedback_score`, `ack_state`. Populate them sensibly.

**Database connections:** Use sync `psycopg2` for reading `telco_events_alarms` (bulk read performance) and async SQLAlchemy sessions for writing incidents and decision traces, similar to how `load_telco2_tenant.py` works. Or use fully async — implementer's choice. The script runs standalone, not inside the FastAPI process.

**Closing some incidents:** For alarms that have `cleared_at IS NOT NULL`, create the incident as already resolved/closed. Set `IncidentORM.status = 'closed'`, `IncidentORM.closed_at = alarm.cleared_at`. This gives the scorecard MTTR data (closed_at - created_at).

**Idempotency:** Before inserting, check if incidents already exist for this tenant (e.g. `SELECT COUNT(*) FROM incidents WHERE tenant_id = 'pedkai_telco2_01'`). If > 0, print a warning and offer a `--force` flag to delete and re-create.

#### What this unlocks

Once incidents and decision_traces are populated:

| Frontend Page | What Lights Up |
|---|---|
| **Dashboard** | Scorecard shows MTTR, incident count; alarm feed shows alarms |
| **Incidents** | Full incident list with ITIL priority, severity, entity references |
| **Scorecard** | MTTR, incident count, drift detections, value capture |
| **TMF642 API** | `GET /alarm` returns real alarm resources |
| **Service Impact** | Alarm clusters with noise reduction metrics |

---

### 5. Fix Sleeping Cell Detector — Wrong Table and Wrong DB

**Priority:** P1 — currently queries empty table on wrong database
**File:** `backend/app/services/sleeping_cell_detector.py`
**Effort:** 30 minutes (depends on item #1 being done first)

**Current state:** Imports and queries `KpiSampleORM` via `async_session_maker` (Graph DB :5432). The `kpi_samples` table has 0 rows for Telco2. The actual KPI data (57M rows) is in `kpi_metrics` on TimescaleDB :5433.

**Changes needed:**

1. Replace import: `from backend.app.models.kpi_sample_orm import KpiSampleORM` → `from backend.app.models.kpi_orm import KPIMetricORM`
2. Replace session factory: `from backend.app.core.database import async_session_maker` → `from backend.app.core.database import metrics_session_maker`
3. Replace all `KpiSampleORM` references with `KPIMetricORM`
4. Replace `async_session_maker` with `metrics_session_maker` in the `async with` block
5. The `.value` attribute stays the same (ORM attribute name is `value` after fix #1)
6. Remove the `.source` filter if present (KPIMetricORM has no `source` column)

**Historic mode consideration:** The detector compares latest KPI values against a 7-day baseline window relative to `datetime.now()`. For historical data (timestamped in Jan 2024), this means `now() - 7 days` finds no data. Add an optional `reference_time` parameter:
```python
async def scan(self, tenant_id: str, reference_time: datetime | None = None) -> List[SleepingCellDetectedEvent]:
    now = reference_time or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=self.window_days)
    idle_cutoff = now - timedelta(minutes=self.idle_minutes)
    # ... rest of logic uses 'now' variable instead of datetime.now()
```

In `main.py` lifespan where the sleeping cell scheduler is configured, the `_scan_sleeping_cells` function should determine the reference time. For historic mode, query: `SELECT MAX(timestamp) FROM kpi_metrics WHERE tenant_id = :tid` on the metrics DB and pass that as `reference_time`. For live mode (when data is fresh), `reference_time` is None and defaults to `now()`.

---

### 6. Fix `NetworkEntityORM` Column Mapping

**Priority:** P2 — topology works via raw SQL, but CX intelligence and future entity endpoints need this
**File:** `backend/app/models/network_entity_orm.py`
**Effort:** 30 minutes

Use the same `Column("db_name", ..., key="orm_name")` pattern as fix #1.

**Changes:**

```python
# Geography — DB columns are 'latitude'/'longitude', ORM attributes stay 'geo_lat'/'geo_lon'
geo_lat = Column("latitude", Float, nullable=True, key="geo_lat")
geo_lon = Column("longitude", Float, nullable=True, key="geo_lon")

# Add missing DB columns
operational_status = Column(String(50), nullable=True)
attributes = Column(JSONB, nullable=True, default=dict)  # Rich domain metadata
updated_at = Column(DateTime, nullable=True)

# Make columns that exist in ORM but not in DB nullable (they'll be NULL for loaded data)
revenue_weight = Column(Float, nullable=True)  # already nullable
sla_tier = Column(String(50), nullable=True)   # already nullable
embedding_provider = Column(String(50), nullable=True)  # already nullable
embedding_model = Column(String(100), nullable=True)     # already nullable
last_seen_at = Column(DateTime, nullable=True)           # already nullable
```

**Important:** The DB does NOT have columns `revenue_weight`, `sla_tier`, `embedding_provider`, `embedding_model`, `last_seen_at`. They exist in the current ORM but not in the DB. SQLAlchemy will generate SQL with these column names and PostgreSQL will error. Either:
- (a) Add these columns to the DB via ALTER TABLE (preferred — forward-compatible), or
- (b) Remove them from the ORM and add them later when data generation catches up

Option (a):
```sql
ALTER TABLE network_entities ADD COLUMN IF NOT EXISTS revenue_weight DOUBLE PRECISION;
ALTER TABLE network_entities ADD COLUMN IF NOT EXISTS sla_tier VARCHAR(50);
ALTER TABLE network_entities ADD COLUMN IF NOT EXISTS embedding_provider VARCHAR(50);
ALTER TABLE network_entities ADD COLUMN IF NOT EXISTS embedding_model VARCHAR(100);
ALTER TABLE network_entities ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMP;
```

Also add the JSONB import at the top of the file:
```python
from sqlalchemy.dialects.postgresql import JSONB
```

---

### 7. Fix Autonomous Action Executor — Wrong Table and Wrong DB

**Priority:** P3 — only relevant once incidents exist
**File:** `backend/app/services/autonomous_action_executor.py`
**Effort:** 15 minutes

Same issue as sleeping cell detector. The `_validate_post_execution` method (around line 226) imports and queries `KpiSampleORM` via the graph DB session. Change to `KPIMetricORM` via `metrics_session_maker`.

The changes mirror fix #5 exactly:
1. Replace `from backend.app.models.kpi_sample_orm import KpiSampleORM` → `from backend.app.models.kpi_orm import KPIMetricORM`
2. Replace all `KpiSampleORM` → `KPIMetricORM`
3. Replace `KpiSampleORM.value` → `KPIMetricORM.value` (works because of fix #1)
4. Use `metrics_session_maker` instead of the graph DB session for KPI queries

---

### 8. Fix `data_retention.py` — GDPR/Confidentiality Compliance Bugs

**Priority:** P2 — this is a compliance service; it must work correctly
**File:** `backend/app/services/data_retention.py`
**Effort:** 30 minutes

This service exists to ensure Pedkai does not retain customer-identifiable information beyond policy limits, in compliance with GDPR and telco customer confidentiality requirements. It has two bugs that make it silently fail.

#### Bug A: Wrong column name for `kpi_metrics` retention cleanup

**Current code (around line 60):**
```python
result = await s.execute(
    text(f"DELETE FROM {table} WHERE created_at < :cutoff"),
    {"cutoff": cutoff},
)
```

The `kpi_metrics` table has `timestamp`, not `created_at`. This DELETE silently fails (caught by the except handler), meaning KPI data is **never cleaned up** — a GDPR retention violation.

**Fix:**
```python
# GDPR/DPIA compliance: enforce rolling retention windows.
# Different tables use different timestamp columns.
# kpi_metrics (TimescaleDB) uses 'timestamp'; most other tables use 'created_at'.
TIMESTAMP_COLUMN_OVERRIDES: dict[str, str] = {
    "kpi_metrics": "timestamp",
}

# Then in run_retention_cleanup:
ts_col = TIMESTAMP_COLUMN_OVERRIDES.get(table, "created_at")
result = await s.execute(
    text(f"DELETE FROM {table} WHERE {ts_col} < :cutoff"),
    {"cutoff": cutoff},
)
```

**Additional consideration:** `kpi_metrics` lives on TimescaleDB (:5433), not the graph DB (:5432). The current code uses a single `session_factory` which connects to the graph DB. The retention cleanup for `kpi_metrics` needs to use the metrics session factory instead. Either:
- Accept a second session factory for metrics, or
- Use TimescaleDB's built-in retention policy (which is already configured: `add_retention_policy('kpi_metrics', INTERVAL '30 days')` — see `backend/app/core/init_db.py` around line 77). In that case, **remove `kpi_metrics` from `RETENTION_POLICIES`** and add a comment explaining that TimescaleDB handles it natively. This is the cleaner approach.

Recommended fix:
```python
# Tables eligible for automatic deletion (non-regulatory)
RETENTION_POLICIES: dict[str, timedelta] = {
    # NOTE: kpi_metrics retention is handled natively by TimescaleDB's
    # add_retention_policy (30-day rolling, configured in init_db.py).
    # Do NOT add kpi_metrics here — it lives on a separate DB instance
    # (TimescaleDB :5433) and the graph DB session cannot reach it.
    "llm_prompt_logs": timedelta(days=90),
}
```

#### Bug B: Wrong column names in `anonymise_customer`

**Current code (around line 82):**
```python
await s.execute(
    text("""
        UPDATE customers
        SET msisdn_hash = NULL,
            name        = '[REDACTED]',
            email       = NULL,
            phone       = NULL
        WHERE id = :cid
    """),
    {"cid": customer_id},
)
```

The `customers` table has NO `msisdn_hash`, `email`, or `phone` columns. The actual columns are: `id`, `external_id`, `name`, `churn_risk_score`, `associated_site_id`, `tenant_id`, `created_at`.

**Fix — anonymise the columns that actually exist and could contain PII:**
```python
async def anonymise_customer(self, customer_id: str, session: Optional[AsyncSession] = None) -> Dict:
    """
    Anonymise a customer record for right-to-erasure (GDPR Art. 17).

    Pedkai processes telco customer data for network intelligence and must
    support right-to-erasure requests. This method irreversibly redacts all
    personally identifiable fields while preserving the row for referential
    integrity (billing accounts, proactive care records, topology associations
    all FK to customers.id).

    Fields redacted:
    - name:           Customer name → '[REDACTED]'
    - external_id:    Vendor customer ID (may encode PII such as MSISDN or
                      account number) → anonymised hash
    - churn_risk_score: Behavioural profile derived from PII → NULL
    - associated_site_id: Could reveal customer location → NULL

    Fields preserved (non-PII):
    - id:             Internal UUID (not customer-facing)
    - tenant_id:      Organisational grouping
    - created_at:     Record metadata

    Note: If the schema evolves to include additional PII columns (e.g. msisdn,
    email, phone, address), they MUST be added to this method. Review this
    method whenever CustomerORM is modified.
    """
    try:
        async with self._get_session(session) as s:
            await s.execute(
                text("""
                    UPDATE customers
                    SET name              = '[REDACTED]',
                        external_id       = 'REDACTED-' || LEFT(md5(external_id::text), 12),
                        churn_risk_score  = NULL,
                        associated_site_id = NULL
                    WHERE id = :cid
                """),
                {"cid": customer_id},
            )
            logger.info(
                f"GDPR right-to-erasure: anonymised customer_id={customer_id} "
                f"(name, external_id, churn_risk_score, associated_site_id redacted)"
            )
            return {"anonymised": True, "customer_id": customer_id}
    except Exception as e:
        logger.error(f"GDPR anonymisation FAILED for customer_id={customer_id}: {e}")
        return {"error": str(e), "customer_id": customer_id}
```

**Note on `external_id`:** It has a UNIQUE constraint and NOT NULL. We can't set it to NULL or a fixed string (would collide across multiple redacted customers). Using `'REDACTED-' || LEFT(md5(external_id), 12)` produces a deterministic but irreversible anonymised value that preserves uniqueness.

#### Commentary to add at the top of the file

Update the module docstring to make the GDPR/confidentiality purpose explicit:
```python
"""
Data Retention Enforcement Service — Task 7.4 (Amendment #26)

PURPOSE: Ensures Pedkai does not retain customer-identifiable information
beyond mandated retention windows, and supports GDPR Article 17
right-to-erasure requests.

Pedkai ingests and processes telco customer data (names, identifiers,
location associations, behavioural scores) as part of its network
intelligence pipeline. This data is subject to:

  1. GDPR (General Data Protection Regulation) — right to erasure (Art. 17),
     purpose limitation (Art. 5(1)(b)), storage limitation (Art. 5(1)(e))
  2. Telco-specific regulations — customer confidentiality obligations under
     national telecom licences and ePrivacy Directive
  3. Internal DPIA (Data Protection Impact Assessment) — see docs/dpia_scope.md

Retention policies per DPIA:
  - KPI telemetry data:   30 days rolling (handled by TimescaleDB native policy)
  - LLM prompt logs:      90 days (auto-deleted by this service)
  - Incidents:            7 years (regulatory — NOT auto-deleted, archived only)
  - Audit trails:         7 years (regulatory — NOT auto-deleted, archived only)
  - Decision memory:      Indefinite (right-to-erasure via anonymisation)
  - Customer records:     Retained while active; anonymised on erasure request

IMPORTANT: When new PII-bearing columns are added to any ORM model, this
service MUST be updated. Reviewers should check data_retention.py in every
PR that modifies customer_orm.py, user_orm.py, or adds new tables with
customer-facing data.
"""
```

---

### 9. Historic Mode Indicator (UX Banner)

**Priority:** P2 — users must know they're looking at retrospective analysis
**Effort:** 1 hour

#### Backend: New endpoint to return data time range

**File:** `backend/app/api/health.py` (add new endpoint) or a new small router

Add a `GET /api/v1/tenant-info/{tenant_id}` or `GET /api/v1/data-status` endpoint that returns:
```json
{
  "tenant_id": "pedkai_telco2_01",
  "mode": "historic",
  "data_period": {
    "earliest": "2024-01-01T00:00:00Z",
    "latest": "2024-01-31T23:59:00Z"
  },
  "entity_count": 784048,
  "alarm_count": 15341,
  "kpi_row_count": 57669010
}
```

**Determine mode:** Query `MAX(raised_at)` from `telco_events_alarms` and/or `MAX(timestamp)` from `kpi_metrics` for the tenant. If the most recent data point is more than 24 hours old, mode is `"historic"`. Otherwise `"live"`.

The KPI query must go to TimescaleDB (metrics DB), so either use `metrics_session_maker` or a raw connection. The alarm query goes to the graph DB.

#### Frontend: Render banner in Navigation

**File:** `frontend/app/components/Navigation.tsx`

After the tenant badge, conditionally render a historic mode banner:
```tsx
{dataMode === "historic" && (
  <div className="hidden md:flex items-center space-x-1.5 px-3 py-1.5 rounded-lg bg-amber-900/50 border border-amber-600/50 text-xs text-amber-300">
    <Clock className="w-3.5 h-3.5" />
    <span>Historic Analysis — {dataPeriod}</span>
  </div>
)}
```

Fetch the data status on mount from the new endpoint.

---

### 10. Sleeping Cell Detector — Historic Time Reference

**Priority:** P3 — extends fix #5 for meaningful results against historical data
**File:** `backend/app/services/sleeping_cell_detector.py`, `backend/app/main.py`
**Effort:** 30 minutes

Described in fix #5. The key change is in `main.py` lifespan where the sleeping cell scheduler is set up:

```python
async def _scan_sleeping_cells():
    """Run sleeping cell scan. Uses data-driven reference time for historic mode."""
    try:
        # Determine reference time from actual data
        from backend.app.core.database import metrics_session_maker
        async with metrics_session_maker() as session:
            result = await session.execute(
                text("SELECT MAX(timestamp) FROM kpi_metrics WHERE tenant_id = :tid"),
                {"tid": settings.default_tenant_id},
            )
            max_ts = result.scalar()

        ref_time = max_ts if max_ts else None
        await detector.scan(settings.default_tenant_id, reference_time=ref_time)
    except Exception as e:
        logger.error(f"Sleeping cell scan error: {e}", exc_info=True)
```

**Note:** `settings.default_tenant_id` is currently `"casinolimit"`. For Telco2 testing, either change it in `.env` to `pedkai_telco2_01` or make the scheduler iterate over all active tenants.

---

## Pre-existing Bugs to Fix (Not Telco2-specific)

These are called out in `docs/TELCO2_SCHEMA_ALIGNMENT_ANALYSIS.md` and should be fixed as part of this work:

### 11. `test_full_platform.py` — Wrong attribute name

**File:** `tests/integration/test_full_platform.py`
Uses `metric_value=50.0` but `KpiSampleORM` has `value`. Change to `value=50.0`.

### 12. `test_live_data_topology.py` — References missing ORM attribute

**File:** `tests/validation/test_live_data_topology.py`
Uses `attributes={"importance": "high"}` on `NetworkEntityORM`. Will work once fix #6 adds `attributes` to the ORM.

---

## Checklist Summary

```
[ ] 1.  KPIMetricORM column mapping (value/tags)         — backend/app/models/kpi_orm.py
[ ] 2.  SSE UNION both event tables (verify)              — backend/app/api/sse.py
[ ] 3.  Dashboard scorecard auth token                    — frontend/app/dashboard/page.tsx
[ ] 4.  Historic backfill script (alarms → incidents)     — backend/app/scripts/backfill_incidents_from_alarms.py (NEW)
[ ] 5.  Sleeping cell → KPIMetricORM + metrics DB         — backend/app/services/sleeping_cell_detector.py
[ ] 6.  NetworkEntityORM column mapping + ALTER TABLE      — backend/app/models/network_entity_orm.py + SQL
[ ] 7.  Autonomous executor → KPIMetricORM + metrics DB   — backend/app/services/autonomous_action_executor.py
[ ] 8.  data_retention.py GDPR fixes + commentary         — backend/app/services/data_retention.py
[ ] 9.  Historic mode UX banner                           — backend + frontend
[ ] 10. Sleeping cell historic time reference              — sleeping_cell_detector.py + main.py
[ ] 11. test_full_platform.py fix                          — tests/integration/test_full_platform.py
[ ] 12. test_live_data_topology.py fix                     — tests/validation/test_live_data_topology.py
```

Items 1-4 together make the product demonstrable against Telco2 data. Items 5-10 make it complete. Items 11-12 are test fixes.

---

## What NOT to Change

- **Do not regenerate or reload the Telco2 dataset.** The machine does not have enough disk space and the data is correct as loaded.
- **Do not change tenant IDs in any data table.** All data uses `pedkai_telco2_01` and that's correct.
- **Do not modify the `tenants`, `users`, or `user_tenant_access` tables.** They are already correct.
- **Do not delete `security_events` or `telco_events_alarms`.** Both are legitimate domain-specific event tables.
- **Do not delete `kpi_samples` table or `KpiSampleORM` model.** Keep for backward compatibility. Just stop using it as the primary KPI store.
- **Do not modify `topology.py`** — it uses raw SQL and works perfectly against the loaded data.
- **Do not change TMF628/TMF642 Pydantic response models** (`tmf628_models.py`, `tmf642_models.py`). The external-facing TMF schemas are correct. Only the internal ORM↔DB column mapping needs fixing.

---

## Open Task Reminder

`docs/TASKS.md` contains **T-001**: Consolidate root-level documentation into a single Product Specification document. The Pedkai root directory has numerous overlapping docs (vision, roadmaps, reviews, audits). These need to be unified into one authoritative `PRODUCT_SPEC.md`. Do not action this in this implementation thread — it's a separate task.