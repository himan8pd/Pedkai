# Telco2 Historic-Mode Integration Plan

**Date:** 2026-03-04
**Status:** Ready for Implementation
**Context:** Pedkai has a full Telco2 dataset loaded. The goal is to make every frontend page and backend service work against this data in a **historic analysis / live-demo mode**, not against live telemetry. This document maps every frontend page → backend endpoint → database table, identifies what works and what's broken, and specifies the minimal changes needed.

---

## Loaded Data Inventory (tenant_id = `pedkai_telco2_01`)

### Graph DB (PostgreSQL :5432)

| Table | Rows | Has ORM | Used by Endpoints |
|---|---|---|---|
| `network_entities` | 784,048 | `NetworkEntityORM` (column mismatch) | Topology, Service Impact |
| `topology_relationships` | 1,660,086 | `EntityRelationshipORM` | Topology (raw SQL) |
| `entity_relationships` | 1,649,735 | None | Nothing (bonus data) |
| `customers` | 633,188 | `CustomerORM` | Service Impact, CX |
| `bss_billing_accounts` | ~633K | `BillingAccountORM` | Service Impact (revenue-at-risk) |
| `bss_service_plans` | unique plans | `ServicePlanORM` | CX, BSS adapter |
| `telco_events_alarms` | 15,341 | None (raw DDL) | SSE alarm stream (after fix) |
| `scenario_manifest` | 7,181 | None (raw DDL) | Nothing yet |
| `scenario_kpi_overrides` | 6,407,752 | None (raw DDL) | Nothing yet |
| `divergence_manifest` | 459,769 | None (raw DDL) | Nothing yet |
| `gt_network_entities` | 811,064 | None (raw DDL) | Nothing yet |
| `gt_entity_relationships` | 1,970,387 | None (raw DDL) | Nothing yet |
| `neighbour_relations` | 926,475 | None (raw DDL) | Nothing yet |
| `vendor_naming_map` | 226 | None (raw DDL) | Nothing yet |
| `kpi_dataset_registry` | 6 | None (raw DDL) | Nothing yet |
| `incidents` | **0** | `IncidentORM` | Incidents page, Scorecard |
| `decision_traces` | **0** | `DecisionTraceORM` | TMF642, Alarm Clusters, Noise Wall |
| `security_events` | **0** | None (raw DDL) | SSE alarm stream (CasinoLimit only) |
| `action_executions` | **0** | `ActionExecutionORM` | Autonomous actions |

### Metrics DB (TimescaleDB :5433)

| Table | Rows | Has ORM | Used by Endpoints |
|---|---|---|---|
| `kpi_metrics` | 57,669,010 | `KPIMetricORM` (column mismatch) | TMF628, Sleeping Cell, Capacity |

### External Parquet Datasets (registered in `kpi_dataset_registry`)

| Dataset | Rows | Columns | Size |
|---|---|---|---|
| `kpi_radio_wide` | 47,480,399 | 44 | 8,720 MB |
| `kpi_transport_wide` | 21,409,920 | 20 | 1,287 MB |
| `kpi_fixed_bb_wide` | 4,776,480 | 19 | 400 MB |
| `kpi_enterprise_wide` | 1,440,000 | 15 | 84 MB |
| `kpi_core_wide` | 299,520 | 25 | 21 MB |
| `kpi_power_env` | 15,192,000 | 12 | 641 MB |

---

## Frontend Page → Backend Endpoint → Data Table Map

### 1. Dashboard (`/dashboard`)

| Data Source | Endpoint | Table Queried | Telco2 Rows | Status |
|---|---|---|---|---|
| Alarm Feed (SSE) | `GET /api/v1/stream/alarms?tenant_id=` | `security_events` | **0** | **BROKEN** — no data |
| Scorecard (REST) | `GET /api/v1/autonomous/scorecard` | `incidents` | **0** | **BROKEN** — no data; also uses hardcoded `Bearer guest` |

**Root Cause:** The SSE stream polls `security_events` (CasinoLimit cybersecurity data). Telco2 network alarms are in `telco_events_alarms`. Both tables are legitimate — they represent different event types (security vs network). The SSE needs to query both.

The scorecard queries `incidents` which requires incidents to have been created from alarm correlation. No incidents exist for Telco2 because the alarm data was bulk-loaded historically, not ingested through the live alarm pipeline.

### 2. Incidents (`/incidents`)

| Data Source | Endpoint | Table Queried | Telco2 Rows | Status |
|---|---|---|---|---|
| Incident list | `GET /api/v1/incidents/` | `incidents` | **0** | **BROKEN** — no data |

**Root Cause:** Same as above. Incidents are created by the alarm correlation engine processing live alarm events. Historical bulk data was never processed through that pipeline.

### 3. Scorecard (`/scorecard`)

| Data Source | Endpoint | Table Queried | Telco2 Rows | Status |
|---|---|---|---|---|
| Scorecard | `GET /api/v1/autonomous/scorecard` | `incidents` | **0** | **BROKEN** — no data |
| Detections | `GET /api/v1/autonomous/detections` | `customers` (for entity names only) | 633,188 | Works (synthetic drift) |
| Value Capture | `GET /api/v1/autonomous/value-capture` | `incidents` (closed) | **0** | Returns zeros |

### 4. Topology (`/topology`)

| Data Source | Endpoint | Table Queried | Telco2 Rows | Status |
|---|---|---|---|---|
| Graph | `GET /api/v1/topology/{tenant_id}` | `topology_relationships` (raw SQL) | 1,660,086 | **WORKS** |
| Entity detail | `GET /api/v1/topology/{tenant_id}/entity/{id}` | `topology_relationships` (raw SQL) | 1,660,086 | **WORKS** |
| Impact tree | `GET /api/v1/topology/{tenant_id}/impact/{id}` | `topology_relationships` (raw SQL) | 1,660,086 | **WORKS** |
| Health | `GET /api/v1/topology/{tenant_id}/health` | `topology_relationships` (raw SQL) | 1,660,086 | **WORKS** |

**Note:** Topology endpoints use raw SQL, not the ORM. They query `topology_relationships` directly. This means the `NetworkEntityORM` column mismatches (`geo_lat` vs `latitude`, etc.) do NOT affect topology. Topology is the one page that works perfectly today.

### 5. API-Only Endpoints (no dedicated frontend page)

| Endpoint | Table Queried | Telco2 Rows | Status |
|---|---|---|---|
| `GET /tmf-api/performanceManagement/v4/performanceMeasurement` | `kpi_metrics` via `KPIMetricORM` | 57,669,010 | **BROKEN** — ORM column mismatch (`value` vs `metric_value`, `tags` vs `metadata`) |
| `GET /tmf-api/alarmManagement/v4/alarm` | `decision_traces` via `DecisionTraceORM` | **0** | No data |
| `GET /api/v1/service-impact/customers` | `customers` (raw SQL) | 633,188 | **WORKS** |
| `GET /api/v1/service-impact/clusters` | `decision_traces` (raw SQL) | **0** | No data |
| Sleeping cell detector (background) | `kpi_samples` via `KpiSampleORM` | **0** (data is in `kpi_metrics` on TimescaleDB) | **BROKEN** — wrong table, wrong DB |

---

## The Core Problem

Pedkai's live-operational features (dashboard alarms, incidents, scorecard, sleeping cell detection) expect data to arrive through the **ingestion pipeline** (alarm webhook → event bus → correlation engine → incident creation → decision traces). This is correct for production.

But in **historic/demo mode**, the data has been bulk-loaded directly into the database. The ingestion pipeline was never run against it. So the downstream tables (`incidents`, `decision_traces`, `action_executions`) are empty.

This is exactly how a real customer deployment would work: they hand Pedkai a dataset of historical alarms/KPIs and say "show me what you can do with this." Pedkai needs a **historic analysis mode** that processes bulk-loaded data through its intelligence pipeline, or queries the source tables directly.

---

## What Needs to Change

### Category A: ORM ↔ DB Column Mismatches (Code Changes)

These prevent SQLAlchemy from querying tables that have data.

#### A-1. `KPIMetricORM` — `kpi_metrics` on TimescaleDB

| ORM Column | DB Column | Fix |
|---|---|---|
| `value` | `metric_value` | Rename ORM column or add `Column("metric_value", ..., key="value")` |
| `tags` | `metadata` | Rename ORM column or add `Column("metadata", ..., key="tags")` |

**Files:** `backend/app/models/kpi_orm.py`
**Impact:** Fixes TMF628, capacity engine, RL evaluator, sleeping cell (once pointed at correct DB)

#### A-2. `NetworkEntityORM` — `network_entities` on Graph DB

| ORM Column | DB Column | Fix |
|---|---|---|
| `geo_lat` | `latitude` | Add column mapping |
| `geo_lon` | `longitude` | Add column mapping |
| (missing) | `operational_status` | Add column to ORM |
| (missing) | `attributes` (JSONB) | Add column to ORM |
| (missing) | `updated_at` | Add column to ORM |
| `revenue_weight` | (not in DB) | Make nullable, or extract from `attributes` JSONB |
| `sla_tier` | (not in DB) | Make nullable, or extract from `attributes` JSONB |
| `embedding_provider` | (not in DB) | Make nullable |
| `embedding_model` | (not in DB) | Make nullable |
| `last_seen_at` | (not in DB) | Make nullable |

**Files:** `backend/app/models/network_entity_orm.py`
**Impact:** Currently no endpoint uses the ORM directly (topology is raw SQL), but CX intelligence service and future entity-detail endpoints will need this.

### Category B: Wrong Data Source (Code Changes)

These are services querying the wrong table or wrong database.

#### B-1. SSE Alarm Stream — Query Both Event Tables

The SSE endpoint (`sse.py`) queries only `security_events`. It must also query `telco_events_alarms`. Both tables are legitimate — they represent different event domains (security events vs network alarms). The query should UNION them with column mapping and filter by `tenant_id`. This is not a per-tenant hack — any tenant may have data in either or both tables.

**File:** `backend/app/api/sse.py`
**Change:** UNION `security_events` and `telco_events_alarms` with column aliasing. Already applied.

#### B-2. Sleeping Cell Detector — Wrong Table and Wrong DB

The sleeping cell detector queries `kpi_samples` on the Graph DB (`async_session_maker`). The actual KPI data is in `kpi_metrics` on TimescaleDB (`metrics_session_maker`).

**File:** `backend/app/services/sleeping_cell_detector.py`
**Change:** Replace `KpiSampleORM` → `KPIMetricORM`, replace `async_session_maker` → `metrics_session_maker`. Depends on A-1 being fixed first.

#### B-3. Autonomous Action Executor — Same Issue as B-2

**File:** `backend/app/services/autonomous_action_executor.py`
**Change:** Same switch as B-2.

### Category C: Empty Downstream Tables (Historic Analysis Mode)

These tables are empty because bulk-loaded alarm data was never processed through the ingestion pipeline. This is the biggest gap.

| Empty Table | What Should Populate It | Source Data Available |
|---|---|---|
| `incidents` | Alarm correlation engine | `telco_events_alarms` (15,341 rows) |
| `decision_traces` | Incident creation + AI reasoning | `telco_events_alarms` (15,341 rows) |
| `action_executions` | Autonomous shield recommendations | Needs incidents first |

#### Option C-1: Historic Backfill Script (Recommended)

Create a script that reads `telco_events_alarms` and processes each alarm through the same correlation/incident-creation logic that the live pipeline uses, but in batch mode. This populates `incidents` and `decision_traces` from historical data.

This is the correct approach because:
- It exercises the real correlation engine against real alarm data
- It produces real incidents with real severity, priority, entity references
- It's exactly what a customer would expect: "feed Pedkai my history and let it show me what it finds"
- The scorecard, incident list, alarm clusters, and noise wall all light up from real derived data

**New file:** `backend/app/scripts/backfill_incidents_from_alarms.py`
**Inputs:** `telco_events_alarms` WHERE `tenant_id = 'pedkai_telco2_01'`
**Outputs:** `incidents`, `decision_traces`

#### Option C-2: Historic KPI Analysis (Sleeping Cell Scan)

Run the sleeping cell detector against the historical KPI window in `kpi_metrics` rather than expecting live telemetry. The detector already has a configurable `window_days` parameter — it just needs to scan relative to the **data's time range** rather than `datetime.now()`.

**File:** `backend/app/services/sleeping_cell_detector.py`
**Change:** Accept an optional `reference_time` parameter. In historic mode, pass the max timestamp from the loaded KPI data instead of `now()`.

### Category D: Dashboard Scorecard Auth Issue (Frontend Fix)

The dashboard page (`frontend/app/dashboard/page.tsx`) fetches the scorecard with `Authorization: "Bearer guest"`. This fails auth silently, so the scorecard cards show N/A even when data exists.

**File:** `frontend/app/dashboard/page.tsx`
**Change:** Use the real auth token from `useAuth()` context.

### Category E: Historic Mode Indicator (UX)

Pedkai should clearly indicate to the user that it's running in historic analysis mode, not against live telemetry. This is a UX requirement — users must know they're looking at retrospective analysis.

**Approach:**
- Detect historic mode by checking if the loaded data's time range is in the past (max timestamp in `kpi_metrics` or `telco_events_alarms` is > N hours old)
- Display a banner in the Navigation bar or Dashboard: "Historic Analysis Mode — Data period: 2024-01-01 to 2024-01-31"
- Colour-code the banner distinctly (e.g. amber/blue) so it cannot be confused with live operations

**Files:**
- `backend/app/api/health.py` or new endpoint — return data time range for current tenant
- `frontend/app/components/Navigation.tsx` — render banner when in historic mode

---

## Implementation Priority

| # | Category | Item | Effort | Impact | Unlocks |
|---|---|---|---|---|---|
| 1 | A-1 | Fix `KPIMetricORM` column mapping | 10 min | HIGH | TMF628 API, sleeping cell, capacity |
| 2 | B-1 | SSE UNION both event tables | 10 min | HIGH | Dashboard alarm feed |
| 3 | D | Fix dashboard scorecard auth token | 5 min | MEDIUM | Scorecard cards on dashboard |
| 4 | C-1 | Historic backfill script (alarms → incidents) | 2-3 hrs | **CRITICAL** | Incidents page, Scorecard, TMF642, Alarm Clusters, Noise Wall |
| 5 | B-2 | Sleeping cell → `kpi_metrics` on TimescaleDB | 30 min | HIGH | Sleeping cell detection |
| 6 | A-2 | Fix `NetworkEntityORM` column mapping | 30 min | MEDIUM | Entity detail, CX intelligence |
| 7 | C-2 | Historic-mode time reference for sleeping cell | 30 min | MEDIUM | Meaningful sleeping cell results |
| 8 | E | Historic mode banner/indicator | 1 hr | MEDIUM | User trust, demo clarity |
| 9 | B-3 | Autonomous executor → metrics DB | 15 min | LOW | Autonomous action KPI checks |

Items 1-4 together make the product demonstrable. Items 5-9 make it complete.

---

## Pre-existing Bugs (Not Telco2-specific)

These exist regardless of tenant and should be fixed:

1. **`data_retention.py`** — Deletes from `kpi_metrics WHERE created_at < :cutoff` but the column is `timestamp`, not `created_at`.
2. **`data_retention.py`** — `anonymise_customer` sets columns (`msisdn_hash`, `email`, `phone`) that don't exist on `CustomerORM`.
3. **`test_full_platform.py`** — Uses `metric_value=` kwarg but `KpiSampleORM` has `value`.
4. **`test_live_data_topology.py`** — References `attributes` on `NetworkEntityORM` which doesn't exist (yet).

---

## Design Principle: Two Event Tables Is Correct

`security_events` and `telco_events_alarms` represent fundamentally different event domains:

- **`security_events`**: Cybersecurity detections (MITRE ATT&CK shaped — `technique_id`, `technique_name`, `machine_name`, `audit_event_ids`). Relevant for security operations.
- **`telco_events_alarms`**: Network alarms (TMF-shaped — `alarm_type`, `severity`, `raised_at`, `cleared_at`, `probable_cause`, `domain`, `correlation_group_id`). Relevant for network operations.

In a real deployment, both exist simultaneously. A converged operator will have security events AND network alarms. The SSE stream, alarm correlation engine, and incident creation pipeline should consume from both tables. This is not a per-tenant table — it's a per-domain table. The `tenant_id` column within each table provides multi-tenant isolation.

The synthetic data generator should be enhanced to produce both security events AND network alarms for any tenant, covering both NOC and SOC use cases.

---

## Appendix: Data Time Ranges

For historic mode detection, the loaded data covers:

```sql
-- Check with:
SELECT MIN(raised_at), MAX(raised_at) FROM telco_events_alarms WHERE tenant_id = 'pedkai_telco2_01';
SELECT MIN(timestamp), MAX(timestamp) FROM kpi_metrics WHERE tenant_id = 'pedkai_telco2_01';  -- on TimescaleDB
```

These ranges determine the "analysis window" displayed to the user in historic mode.