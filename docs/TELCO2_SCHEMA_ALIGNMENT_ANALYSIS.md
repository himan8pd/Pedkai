# Telco2 Schema Alignment Analysis

**Date:** 2026-03-03
**Status:** Decision Pending — Recommendation Recorded
**Context:** Phase 11 data loader (`load_telco2_tenant.py`) loaded the full Telco2 dataset into the live database using an older version of the codebase. The current codebase has since evolved its schema. This document records the full analysis of both directions and the recommendation.

---

## Background

The Phase 11 data loader was executed against the live database (PostgreSQL :5432 for graph, TimescaleDB :5433 for metrics). The script that **actually ran** was an older version of the codebase — confirmed by the log output showing a UUID tenant ID and `name=` column (not `display_name=`):

```
2026-03-03 14:46:44 [INFO]   ✓ Tenant already exists: id=be84d2c2-d369-4cc0-bf0a-cf1f24f01e58, name=Telco2 — Indonesian Converged Operator
```

The current codebase expects `TENANT_ID = "pedkai_telco2_01"` (slug string) and `display_name` on the tenants table.

### Data Loaded (Live Database State)

| Table | Database | Row Count | Notes |
|---|---|---|---|
| `tenants` | Graph DB :5432 | 1 row | `id=be84d2c2-...`, column `name` (not `display_name`) |
| `network_entities` | Graph DB :5432 | 784,048 | Columns: `latitude`, `longitude`, `operational_status`, `attributes` (JSONB) |
| `entity_relationships` | Graph DB :5432 | 1,649,735 | No ORM exists for this table |
| `topology_relationships` | Graph DB :5432 | 1,660,086 | Matches `EntityRelationshipORM` |
| `customers` | Graph DB :5432 | 633,188 | Deduplicated from 1M source rows |
| `bss_service_plans` | Graph DB :5432 | ~unique plans | Matches `ServicePlanORM` |
| `bss_billing_accounts` | Graph DB :5432 | ~633K | Matches `BillingAccountORM` |
| `gt_network_entities` | Graph DB :5432 | 811,064 | Supplementary table (raw DDL, no ORM) |
| `gt_entity_relationships` | Graph DB :5432 | 1,970,387 | Supplementary table (raw DDL, no ORM) |
| `divergence_manifest` | Graph DB :5432 | 459,769 | Supplementary table (raw DDL, no ORM) |
| `scenario_manifest` | Graph DB :5432 | 7,181 | Supplementary table (raw DDL, no ORM) |
| `scenario_kpi_overrides` | Graph DB :5432 | 6,407,752 | Supplementary table (raw DDL, no ORM) |
| `telco_events_alarms` | Graph DB :5432 | 15,341 | Supplementary table (raw DDL, no ORM) |
| `neighbour_relations` | Graph DB :5432 | 926,475 | Supplementary table (raw DDL, no ORM) |
| `vendor_naming_map` | Graph DB :5432 | 226 | Supplementary table (raw DDL, no ORM) |
| `kpi_dataset_registry` | Graph DB :5432 | 6 entries | External Parquet file references |
| `kpi_metrics` | Metrics DB :5433 | 57,669,010 | Columns: `metric_value`, `metadata` (JSONB) |

### Registered External Parquet Datasets (Step 11)

| Dataset Name | Source File | Rows | Columns | Size |
|---|---|---|---|---|
| `kpi_radio_wide` | `kpi_metrics_wide.parquet` | 47,480,399 | 44 | 8,720 MB |
| `kpi_transport_wide` | `transport_kpis_wide.parquet` | 21,409,920 | 20 | 1,287 MB |
| `kpi_fixed_bb_wide` | `fixed_broadband_kpis_wide.parquet` | 4,776,480 | 19 | 400 MB |
| `kpi_enterprise_wide` | `enterprise_circuit_kpis_wide.parquet` | 1,440,000 | 15 | 84 MB |
| `kpi_core_wide` | `core_element_kpis_wide.parquet` | 299,520 | 25 | 21 MB |
| `kpi_power_env` | `power_environment_kpis.parquet` | 15,192,000 | 12 | 641 MB |

---

## Bug Found During Investigation

### Infinite Loop in Step 12 (KPI Sample Loader)

The loop in `step_12_load_kpi_sample` had a placeholder `pass` where a break condition should have been:

```python
# BEFORE (broken):
if wide_rows_processed > 0 and batch_num > 0:
    # Check if we've gone past the cutoff window
    # The data is ordered, so once we stop seeing rows, we're done
    pass
```

The 47.5M-row file has ~9,496 batches (at batch_size=5000). Only ~350 batches contained data within the 24-hour time window. The remaining ~9,146 batches were scanned uselessly — every row past the cutoff was skipped by `if ts > cutoff: continue`, but the loop never broke.

**Fix applied:** Replaced `pass` with a break condition that detects when a full batch yields zero qualifying rows:

```python
# AFTER (fixed):
if wide_rows_processed > 0 and n > 0 and loaded > 0:
    if batch_num > 1 and wide_rows_processed == _prev_wide:
        log.info(f"    All rows in batch {batch_num} past {sample_hours}h cutoff — stopping scan.")
        break
_prev_wide = wide_rows_processed
```

**Impact:** Step 12 runtime drops from ~65+ minutes to ~5-6 minutes. The loaded data (57,669,010 rows) is intact — the fix only prevents scanning empty batches.

**Safe to Ctrl+C:** Yes. The script commits every 50 batches, all 57.7M rows were committed by batch ~400, and the `KeyboardInterrupt` handler in `main()` calls `metrics_conn.rollback()` (which rolls back nothing since there are no uncommitted rows).

---

## Direction A: Adapt Code to Match Loaded Data (Old Schema)

### Full Mismatch Inventory

#### 1. `tenants` — Tenant ID & Column Names

| Aspect | Live DB (Old) | Current Code (New) |
|---|---|---|
| PK (`id`) | `be84d2c2-d369-4cc0-bf0a-cf1f24f01e58` (UUID) | `pedkai_telco2_01` (slug string) |
| Display column | `name` | `display_name` |
| Active flag | *(unknown — may not exist)* | `is_active` (Boolean) |

#### 2. `kpi_metrics` — Column Names

| Aspect | Live DB (Old) | Current ORM (`KPIMetricORM`) |
|---|---|---|
| Value column | `metric_value` | `value` |
| Tags column | `metadata` (JSONB) | `tags` (JSONB) |

#### 3. `kpi_samples` vs `kpi_metrics` — Wrong Table

| Aspect | Current Code | Loaded Data |
|---|---|---|
| `SleepingCellDetector` | Queries `kpi_samples` via `async_session_maker` (graph DB :5432) | Data is in `kpi_metrics` on metrics DB :5433 |
| `AutonomousActionExecutor` | Queries `kpi_samples` via graph DB session | Same issue |

#### 4. `network_entities` — Column Names

| Aspect | Live DB (Old) | Current ORM (`NetworkEntityORM`) |
|---|---|---|
| Latitude | `latitude` | `geo_lat` |
| Longitude | `longitude` | `geo_lon` |
| Status | `operational_status` | *(missing from ORM)* |
| Flexible metadata | `attributes` (JSONB) | *(missing from ORM)* |
| Updated timestamp | `updated_at` | *(missing from ORM)* |
| Revenue weight | *(inside `attributes` JSONB)* | `revenue_weight` (Float column) |
| SLA tier | *(inside `attributes` JSONB)* | `sla_tier` (String column) |
| Embedding provider | *(missing)* | `embedding_provider` |
| Embedding model | *(missing)* | `embedding_model` |
| Last seen at | *(missing)* | `last_seen_at` |

#### 5. `entity_relationships` — Orphan Table

1,649,735 rows loaded into `entity_relationships`, but no ORM exists. The codebase only uses `topology_relationships` via `EntityRelationshipORM`. Not blocking — bonus data.

#### 6. `data_retention.py` — Pre-existing Bugs

- Deletes from `kpi_metrics WHERE created_at < :cutoff` but `kpi_metrics` has `timestamp`, not `created_at`.
- `anonymise_customer` sets `msisdn_hash = NULL, email = NULL, phone = NULL` but `CustomerORM` has none of these columns.

### Files That Would Need Changes (Direction A)

| # | File | Change |
|---|---|---|
| 1 | `backend/app/models/kpi_orm.py` | Rename `value` → `metric_value`, `tags` → `metadata` |
| 2 | `backend/app/models/network_entity_orm.py` | Add `latitude`/`longitude`/`operational_status`/`attributes`/`updated_at`; remove or alias `geo_lat`/`geo_lon` |
| 3 | `backend/app/services/sleeping_cell_detector.py` | Switch `KpiSampleORM` → `KPIMetricORM` + `metrics_session_maker` |
| 4 | `backend/app/services/autonomous_action_executor.py` | Switch `KpiSampleORM` → `KPIMetricORM` + metrics session |
| 5 | `backend/app/services/capacity_engine.py` | `.value` → `.metric_value` |
| 6 | `backend/app/services/rl_evaluator.py` | `.value` → `.metric_value` |
| 7 | `backend/app/services/data_retention.py` | Fix `created_at` → `timestamp`; fix anonymise columns |
| 8 | `backend/app/api/tmf628.py` | `r.value` → `r.metric_value` (internal wiring only — TMF628 schema unchanged) |
| 9 | `backend/app/services/auth_service.py` | Add UUID tenant to `SEED_TENANTS` |
| 10 | `backend/app/scripts/load_telco2_tenant.py` | Fix `TENANT_ID`, `TENANT_DISPLAY_NAME`, step_0 query |
| 11 | `tests/integration/test_rl_evaluator.py` | `value=` → `metric_value=` |
| 12 | `tests/integration/test_full_platform.py` | Fix `KpiSampleORM` usage |
| 13 | `tests/validation/test_live_data_topology.py` | Will work once ORM has `attributes` |
| 14 | `tests/integration/test_phase5_readiness.py` | Switch KPI queries to `KPIMetricORM` |

### TMF628/642 Impact Assessment

**TMF628:** The only change is `r.value` → `r.metric_value` in the internal ORM-to-Pydantic adapter in `tmf628.py`. The outward-facing TMF628 response schema (`PerformanceMeasurement.measurementValue`, `observationTime`, `performanceIndicatorSpecification`) is **completely unchanged**. The TMF628 Pydantic models (`tmf628_models.py`) require **zero changes**. **No standards compliance impact.**

**TMF642:** Does not touch `kpi_metrics` at all. It uses `DecisionTraceORM` for alarm management. **No changes needed.**

---

## Direction B: Adapt Database to Match Current Code (New Schema)

This means regenerating the Telco2 dataset with `--tenant-id pedkai_telco2_01` and reloading it.

### What the New Schema Gains

#### 1. Tenant Model — Slug PKs vs UUID PKs (**HIGH value**)

The new `TenantORM` uses human-readable slug strings (`"pedkai_telco2_01"`) as the primary key.

**Benefits of slug PKs:**
- **JWT tokens are debuggable.** `tenant_id: "pedkai_telco2_01"` in a decoded JWT is immediately readable. `tenant_id: "be84d2c2-d369-..."` requires a database lookup.
- **Log messages are readable.** Every service logging `tenant_id=` becomes interpretable at a glance across 57M+ rows and multiple concurrent tenants.
- **No indirection.** The slug is the identifier everywhere — DB, tokens, logs, URLs. UUID requires a lookup table.
- **`is_active` column.** The new schema supports soft-disabling tenants. `auth_service` already uses `TenantORM.is_active.is_(True)` for filtering. The old schema has no equivalent.
- **`display_name` separation.** Clean separation of machine ID from human label, with a `label` property fallback.
- **`UserTenantAccessORM`.** The entire multi-tenant authorization model (user↔tenant mapping with FK to `tenants.id`) is built around string PKs. Reverting to UUID PKs would require rethreading the auth flow.

#### 2. `network_entities` — First-Class Business Columns (**MEDIUM-HIGH value**)

The new ORM promotes `revenue_weight`, `sla_tier`, `embedding_provider`, `embedding_model`, `last_seen_at` to first-class columns. The old schema stuffs `revenue_weight` and `sla_tier` inside an untyped `attributes` JSONB blob.

**Benefits of first-class columns:**
- **Queryable without JSON path expressions.** `WHERE revenue_weight > 1000` vs `WHERE attributes->>'revenue_weight' > '1000'` (string comparison, requires casting, needs GIN index).
- **Type safety.** `revenue_weight Float` is enforced by the DB. Inside JSONB it could be string, null, or anything.
- **`sla_tier`** is used by `customer_prioritisation.py` for incident triage ordering. First-class column enables direct joins.
- **`embedding_provider` / `embedding_model`** — per-entity embedding model tracking for decision memory. The `backfill_embeddings.py` script writes to these columns.
- **`last_seen_at`** — entity liveness tracking for sleeping cell detection.

**What the old schema has that the new doesn't (must be added back):**
- `operational_status` — explicit status field. (Loader hardcodes to `"active"` so it carried no real information, but architecturally correct to have.)
- `attributes` JSONB — flexible bag for domain-specific metadata (vendor, band, deployment_profile, azimuth_deg, antenna_height_m, etc.). 784K entities with rich attributes. **This is a real loss if not added back.**
- `updated_at` — simple change-tracking timestamp.

**Verdict:** The right answer is to keep the new first-class columns AND add `attributes`, `operational_status`, and `updated_at` back.

#### 3. `kpi_metrics` Column Names — `value`/`tags` vs `metric_value`/`metadata` (**LOW value**)

Purely naming preference. `value` is more concise. `metric_value` is more explicit. Neither changes behavior. TMF628 outward-facing field is `measurementValue` regardless. The natural composite PK `(tenant_id, entity_id, timestamp, metric_name)` is the same in both schemas.

#### 4. `kpi_samples` vs `kpi_metrics` Architecture (**MEDIUM value**)

`KpiSampleORM` provides:
- FK to `network_entities` with CASCADE DELETE (referential integrity)
- `source` column (tracks data provenance: `RAN_TELEMETRY`, `SYNTHETIC_TEST`)
- UUID primary key (individual row identity)

However:
- **No service code actually uses the FK join.** No query does `JOIN kpi_samples ON network_entities.id`.
- **No service code filters by `source`.** Test-only usage.
- **UUID PKs on time-series data are an anti-pattern.** TimescaleDB hypertables need natural composite keys for chunk partitioning.
- **The sleeping cell detector queries `kpi_samples` on the graph DB** — but time-series queries belong on TimescaleDB where hypertable chunking, compression, and retention policies operate.
- **57.7M rows are already in `kpi_metrics`** on TimescaleDB. `kpi_samples` is empty for Telco2.

**Verdict:** `kpi_metrics` on TimescaleDB is the correct architecture. Retire `kpi_samples` as primary KPI store; keep for backward compatibility if needed.

#### 5. Sleeping Cell Detector Architecture (**HIGH value**)

Regardless of schema direction, services must be rewired to query KPIs on the metrics DB (TimescaleDB).

TimescaleDB provides:
- Hypertable chunking by timestamp → orders of magnitude faster range scans on 57M+ rows
- Native compression (7-day policy already configured) → 5-10x storage savings
- Retention policies (30-day auto-drop already configured) → no manual cleanup
- Continuous aggregates (future) → pre-computed hourly/daily rollups

None of this works if the sleeping cell detector queries `kpi_samples` on vanilla PostgreSQL.

---

## Recommendation

**Go with Direction B: New schema. Regenerate and reload the Telco2 data.**

### Rationale

1. **The UUID tenant ID is a dead end.** The entire auth system (JWT tokens, `UserTenantAccessORM`, logging, `SEED_TENANTS`) is built around slug IDs. Reverting to UUIDs would require rethreading a dozen files across the auth layer. The slug design is the better design.

2. **The `network_entities` schema should be a hybrid.** Keep the new first-class columns (`revenue_weight`, `sla_tier`, `embedding_provider`, `embedding_model`, `last_seen_at`) AND add back `attributes` JSONB + `operational_status` + `updated_at`. The loader already stores `revenue_weight` and `sla_tier` inside `attributes` — in the new loader, extract them as first-class columns AND keep the rest in `attributes`. Best of both worlds.

3. **The `kpi_metrics` column names are trivial.** Rename the loader's `metric_value` → `value` and `metadata` → `tags` to match the new ORM. Three lines in the loader script.

4. **Retire `kpi_samples` as the primary KPI store.** Keep the model for backward compatibility with tests, but all production KPI queries should hit `kpi_metrics` on TimescaleDB.

5. **The data generation pipeline is deterministic.** The `Sleeping-Cell-KPI-Data` generator uses a `global_seed` and `--tenant-id` flag. Regenerate the entire 11 GB dataset with `--tenant-id pedkai_telco2_01` and reload in one pass — this time with the break fix, so step 12 finishes in ~5 minutes instead of 65+.

### Cost of Direction B

- Re-run data generator: ~30-60 minutes (deterministic, same seed)
- Re-run loader: ~15-20 minutes (with break fix applied)
- Total: ~1 hour of compute time

### Changes Required for Direction B

| # | File | Change |
|---|---|---|
| 1 | `backend/app/models/network_entity_orm.py` | Add `operational_status`, `attributes` (JSONB), `updated_at`; rename `geo_lat` → `latitude`, `geo_lon` → `longitude`; keep all existing new columns |
| 2 | `backend/app/scripts/load_telco2_tenant.py` | Fix step 12 break (**done**); update INSERT to use `value`/`tags`; promote `revenue_weight`/`sla_tier` as first-class columns in step 1 |
| 3 | `backend/app/services/sleeping_cell_detector.py` | Switch to `KPIMetricORM` + `metrics_session_maker` |
| 4 | `backend/app/services/autonomous_action_executor.py` | Same switch |
| 5 | `backend/app/services/data_retention.py` | Fix `created_at` → `timestamp` bug; fix `anonymise_customer` column names |
| 6 | Test files | Minor fixture updates |

**No changes needed to:** `kpi_orm.py`, `tenant_orm.py`, `auth_service.py`, `tmf628.py`, `tmf642.py`, `capacity_engine.py`, `rl_evaluator.py` — the regenerated data conforms to them.

---

## Appendix: Pre-existing Bugs Found

These exist regardless of schema direction and should be fixed:

### A. `data_retention.py` — Wrong Column Name for `kpi_metrics`

```python
# BUG: kpi_metrics has 'timestamp', not 'created_at'
result = await s.execute(
    text(f"DELETE FROM {table} WHERE created_at < :cutoff"),
    {"cutoff": cutoff},
)
```

The retention cleanup for `kpi_metrics` will always fail (caught by the except handler, but silently broken).

### B. `data_retention.py` — Wrong Column Names for Customer Anonymisation

```python
# BUG: CustomerORM has no msisdn_hash, email, or phone columns
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

The `CustomerORM` only has: `id`, `external_id`, `name`, `churn_risk_score`, `associated_site_id`, `consent_proactive_comms`, `tenant_id`, `created_at`.

### C. `test_full_platform.py` — Wrong Attribute Name

```python
# Uses 'metric_value' but KpiSampleORM has 'value'
sample = KpiSampleORM(
    ...
    metric_value=50.0 + i * 10,  # Should be 'value'
    ...
)
```

### D. `test_live_data_topology.py` — References Missing ORM Attribute

```python
# Uses 'attributes' but NetworkEntityORM has no such column (currently)
entity = NetworkEntityORM(
    ...
    attributes={"importance": "high"}
)
```

This will work once `attributes` is added back to the ORM (part of recommended Direction B changes).