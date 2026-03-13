#!/usr/bin/env python3
"""
Telco2 Tenant Data Loader — Phase 11 Implementation
=====================================================

Loads all Parquet files from the Telco2 synthetic dataset into Pedkai's
PostgreSQL (graph DB) and TimescaleDB (metrics DB) databases.

Load order (respects FK constraints):
  1. Tenant record
  2. Network entities (CMDB declared) → network_entities
  3. Entity relationships (CMDB declared) → entity_relationships
  4. Topology relationships → topology_relationships (for graph traversal API)
  5. Customers → customers
  6. BSS service plans + billing accounts → bss_service_plans, bss_billing_accounts
  7. Ground truth tables (created if needed)
  8. Divergence manifest (created if needed)
  9. Scenario manifest + overrides (created if needed)
  10. Neighbour relations (created if needed)
  11. Vendor naming map (created if needed)
  12. Events/alarms → topology or via Kafka events
  13. KPI files → registered as external Parquet datasets (NOT exploded)

Usage:
  cd /Users/himanshu/Projects/Pedkai
  ./venv/bin/python -m backend.app.scripts.load_telco2_tenant [--dry-run] [--skip-kpi-sample] [--step STEP]

Environment:
  Reads from .env (DATABASE_URL, METRICS_DATABASE_URL)
  Defaults: postgresql://postgres:postgres@localhost:5432/pedkai
            postgresql://postgres:postgres@localhost:5433/pedkai_metrics
"""

from __future__ import annotations

import argparse
import gc
import json
import logging
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import psycopg2
import psycopg2.extras
import pyarrow.parquet as pq

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

import os

_data_store_root = os.environ.get(
    "PEDKAI_DATA_STORE_ROOT", "/Volumes/Projects/Pedkai Data Store"
)
TELCO2_DATA_DIR = Path(_data_store_root) / "Telco2"
OUTPUT_DIR = TELCO2_DATA_DIR / "output"
INTERMEDIATE_DIR = TELCO2_DATA_DIR / "intermediate"

TENANT_ID = "pedkai_telco2_01"
TENANT_DISPLAY_NAME = "Pedkai Telco2 01"

# Database connection strings (sync, for psycopg2 COPY performance)
# Read from env vars if available, fall back to localhost defaults for local dev
GRAPH_DB_DSN = os.environ.get(
    "GRAPH_DB_DSN",
    "host=localhost port=5432 dbname=pedkai user=postgres password=postgres",
)
METRICS_DB_DSN = os.environ.get(
    "METRICS_DB_DSN",
    "host=localhost port=5433 dbname=pedkai_metrics user=postgres password=postgres",
)

# Batch sizes
BATCH_ENTITIES = 10_000
BATCH_RELATIONSHIPS = 10_000
BATCH_CUSTOMERS = 10_000
BATCH_KPI_LONG = 50_000

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("telco2_loader")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _timer():
    """Simple context-manager-like timer."""
    return time.time()


def _elapsed(t0: float) -> str:
    dt = time.time() - t0
    if dt < 60:
        return f"{dt:.1f}s"
    return f"{dt / 60:.1f}m"


def _file_size_mb(p: Path) -> str:
    if p.exists():
        return f"{p.stat().st_size / (1024 * 1024):.1f} MB"
    return "N/A"


def _pq_row_count(p: Path) -> int:
    if not p.exists():
        return 0
    pf = pq.ParquetFile(p)
    return pf.metadata.num_rows


def _ensure_file(p: Path) -> bool:
    if not p.exists():
        log.warning(f"  ⊘ File not found: {p}")
        return False
    return True


def _get_conn(dsn: str):
    """Get a psycopg2 connection."""
    conn = psycopg2.connect(dsn)
    conn.autocommit = False
    return conn


# ---------------------------------------------------------------------------
# Step 0: Create / verify tenant
# ---------------------------------------------------------------------------


def step_0_create_tenant(conn, dry_run: bool = False):
    """Insert the tenant record if it doesn't exist.

    The ``tenants`` table uses a human-readable slug string as its primary
    key (``id``).  The ``display_name`` column holds the prettier UI label.
    There is no UUID indirection — ``TENANT_ID`` *is* the PK.
    """
    log.info("━━━ Step 0: Create tenant ━━━")

    with conn.cursor() as cur:
        cur.execute("SELECT id, display_name FROM tenants WHERE id = %s", (TENANT_ID,))
        row = cur.fetchone()
        if row:
            log.info(f"  ✓ Tenant already exists: id={row[0]}, display_name={row[1]}")
            return row[0]

        if dry_run:
            log.info(
                f"  [DRY RUN] Would create tenant: id={TENANT_ID}, display_name={TENANT_DISPLAY_NAME}"
            )
            return TENANT_ID

        cur.execute(
            "INSERT INTO tenants (id, display_name, is_active, created_at) VALUES (%s, %s, %s, %s)",
            (TENANT_ID, TENANT_DISPLAY_NAME, True, datetime.now(timezone.utc)),
        )
        conn.commit()
        log.info(f"  ✓ Created tenant: id={TENANT_ID}")
        return TENANT_ID


# ---------------------------------------------------------------------------
# Step 1: Network Entities (CMDB declared → network_entities)
# ---------------------------------------------------------------------------


def step_1_load_network_entities(conn, dry_run: bool = False):
    """Load cmdb_declared_entities.parquet → network_entities table."""
    log.info("━━━ Step 1: Load network entities (CMDB declared) ━━━")
    filepath = OUTPUT_DIR / "cmdb_declared_entities.parquet"
    if not _ensure_file(filepath):
        return

    total_rows = _pq_row_count(filepath)
    log.info(
        f"  Source: {filepath.name} ({total_rows:,} rows, {_file_size_mb(filepath)})"
    )

    if dry_run:
        log.info(
            f"  [DRY RUN] Would load {total_rows:,} entities into network_entities"
        )
        return

    # Check if data already loaded for this tenant
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM network_entities WHERE tenant_id = %s", (TENANT_ID,)
        )
        existing = cur.fetchone()[0]
        if existing > 0:
            log.info(
                f"  ⚠ {existing:,} entities already exist for tenant {TENANT_ID}. Skipping. (Delete first to reload.)"
            )
            return

    t0 = _timer()
    pf = pq.ParquetFile(filepath)
    loaded = 0
    batch_num = 0

    # Columns we need to map from Parquet → DB:
    # entity_id (UUID PK) → id
    # tenant_id → tenant_id
    # entity_type → entity_type
    # name → name
    # external_id → external_id
    # geo_lat → latitude
    # geo_lon → longitude
    # + remaining columns packed into attributes JSONB

    # Columns to extract as first-class DB columns
    FIRST_CLASS = {
        "entity_id",
        "tenant_id",
        "entity_type",
        "name",
        "external_id",
        "geo_lat",
        "geo_lon",
    }

    # Columns to pack into attributes JSONB
    ATTR_COLS = [
        "domain",
        "site_id",
        "site_type",
        "deployment_profile",
        "province",
        "timezone",
        "vendor",
        "rat_type",
        "band",
        "bandwidth_mhz",
        "max_tx_power_dbm",
        "max_prbs",
        "frequency_mhz",
        "sector_id",
        "azimuth_deg",
        "electrical_tilt_deg",
        "antenna_height_m",
        "inter_site_distance_m",
        "revenue_weight",
        "sla_tier",
        "is_nsa_anchor",
        "nsa_anchor_cell_id",
        "parent_entity_id",
        "properties_json",
    ]

    insert_sql = """
        INSERT INTO network_entities (id, tenant_id, entity_type, name, external_id,
                                      latitude, longitude, operational_status,
                                      attributes, created_at)
        VALUES %s
        ON CONFLICT (id) DO NOTHING
    """

    with conn.cursor() as cur:
        for batch in pf.iter_batches(batch_size=BATCH_ENTITIES):
            batch_num += 1
            table = batch.to_pydict()
            n = len(table["entity_id"])
            rows = []

            for i in range(n):
                entity_id = table["entity_id"][i]
                # Build attributes dict from remaining columns
                attrs = {}
                for col in ATTR_COLS:
                    if col in table:
                        val = table[col][i]
                        if val is not None:
                            attrs[col] = val

                row = (
                    entity_id,  # id (UUID)
                    table["tenant_id"][i],  # tenant_id
                    table["entity_type"][i],  # entity_type
                    table["name"][i],  # name
                    table.get("external_id", [None] * n)[i],  # external_id
                    table.get("geo_lat", [None] * n)[i],  # latitude
                    table.get("geo_lon", [None] * n)[i],  # longitude
                    "active",  # operational_status
                    json.dumps(attrs),  # attributes JSONB
                    datetime.now(timezone.utc),  # created_at
                )
                rows.append(row)

            psycopg2.extras.execute_values(
                cur,
                insert_sql,
                rows,
                template="(%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)",
                page_size=BATCH_ENTITIES,
            )
            loaded += n

            if batch_num % 10 == 0:
                conn.commit()
                log.info(f"    batch {batch_num}: {loaded:,} / {total_rows:,} rows")

            del table, rows
            gc.collect()

        conn.commit()

    log.info(f"  ✓ Loaded {loaded:,} entities in {_elapsed(t0)}")


# ---------------------------------------------------------------------------
# Step 2: Entity Relationships (CMDB declared → entity_relationships)
# ---------------------------------------------------------------------------


def step_2_load_entity_relationships(conn, dry_run: bool = False):
    """Load cmdb_declared_relationships.parquet → entity_relationships table."""
    log.info("━━━ Step 2: Load entity relationships (CMDB declared) ━━━")
    filepath = OUTPUT_DIR / "cmdb_declared_relationships.parquet"
    if not _ensure_file(filepath):
        return

    total_rows = _pq_row_count(filepath)
    log.info(
        f"  Source: {filepath.name} ({total_rows:,} rows, {_file_size_mb(filepath)})"
    )

    if dry_run:
        log.info(
            f"  [DRY RUN] Would load {total_rows:,} relationships into entity_relationships"
        )
        return

    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM entity_relationships WHERE tenant_id = %s",
            (TENANT_ID,),
        )
        existing = cur.fetchone()[0]
        if existing > 0:
            log.info(
                f"  ⚠ {existing:,} relationships already exist for tenant {TENANT_ID}. Skipping."
            )
            return

    t0 = _timer()
    pf = pq.ParquetFile(filepath)
    loaded = 0
    skipped = 0
    batch_num = 0

    # Parquet columns: relationship_id, tenant_id, from_entity_id, from_entity_type,
    #                  relationship_type, to_entity_id, to_entity_type, domain, properties_json
    # DB columns: id, tenant_id, source_entity_id (UUID FK), source_entity_type,
    #             target_entity_id (UUID FK), target_entity_type, relationship_type,
    #             weight, attributes (JSONB), created_at

    insert_sql = """
        INSERT INTO entity_relationships
            (id, tenant_id, source_entity_id, source_entity_type,
             target_entity_id, target_entity_type, relationship_type,
             weight, attributes, created_at)
        VALUES %s
        ON CONFLICT (id) DO NOTHING
    """

    # Pre-load the set of valid entity UUIDs so we can skip broken FKs
    log.info("    Pre-loading entity ID set for FK validation...")
    valid_entity_ids = set()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id::text FROM network_entities WHERE tenant_id = %s", (TENANT_ID,)
        )
        for row in cur:
            valid_entity_ids.add(row[0])
    log.info(f"    {len(valid_entity_ids):,} valid entity IDs loaded")

    with conn.cursor() as cur:
        for batch in pf.iter_batches(batch_size=BATCH_RELATIONSHIPS):
            batch_num += 1
            table = batch.to_pydict()
            n = len(table["relationship_id"])
            rows = []

            for i in range(n):
                from_id = table["from_entity_id"][i]
                to_id = table["to_entity_id"][i]

                # FK check — skip relationships referencing unknown entities
                if from_id not in valid_entity_ids or to_id not in valid_entity_ids:
                    skipped += 1
                    continue

                attrs = {}
                if table.get("domain") and table["domain"][i]:
                    attrs["domain"] = table["domain"][i]
                if table.get("properties_json") and table["properties_json"][i]:
                    try:
                        props = json.loads(table["properties_json"][i])
                        attrs.update(props)
                    except (json.JSONDecodeError, TypeError):
                        attrs["properties_raw"] = table["properties_json"][i]

                row = (
                    table["relationship_id"][i],  # id (UUID)
                    table["tenant_id"][i],  # tenant_id
                    from_id,  # source_entity_id (UUID FK)
                    table["from_entity_type"][i],  # source_entity_type
                    to_id,  # target_entity_id (UUID FK)
                    table["to_entity_type"][i],  # target_entity_type
                    table["relationship_type"][i],  # relationship_type
                    None,  # weight
                    json.dumps(attrs),  # attributes JSONB
                    datetime.now(timezone.utc),  # created_at
                )
                rows.append(row)

            if rows:
                psycopg2.extras.execute_values(
                    cur,
                    insert_sql,
                    rows,
                    template="(%s, %s, %s::uuid, %s, %s::uuid, %s, %s, %s, %s::jsonb, %s)",
                    page_size=BATCH_RELATIONSHIPS,
                )

            loaded += len(rows)

            if batch_num % 20 == 0:
                conn.commit()
                log.info(
                    f"    batch {batch_num}: {loaded:,} loaded, {skipped:,} skipped (FK miss)"
                )

            del table, rows
            gc.collect()

        conn.commit()

    log.info(
        f"  ✓ Loaded {loaded:,} relationships ({skipped:,} skipped for FK) in {_elapsed(t0)}"
    )


# ---------------------------------------------------------------------------
# Step 3: Topology Relationships (for graph traversal API)
# ---------------------------------------------------------------------------


def step_3_load_topology_relationships(conn, dry_run: bool = False):
    """
    Load CMDB declared relationships into topology_relationships table.
    This powers the /topology/{tenant_id} API used by the frontend graph view.
    Uses the same source file but maps to the simpler topology_relationships schema.
    """
    log.info("━━━ Step 3: Load topology relationships (graph API) ━━━")
    filepath = OUTPUT_DIR / "cmdb_declared_relationships.parquet"
    if not _ensure_file(filepath):
        return

    total_rows = _pq_row_count(filepath)
    log.info(f"  Source: {filepath.name} ({total_rows:,} rows)")

    if dry_run:
        log.info(
            f"  [DRY RUN] Would load {total_rows:,} rows into topology_relationships"
        )
        return

    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM topology_relationships WHERE tenant_id = %s",
            (TENANT_ID,),
        )
        existing = cur.fetchone()[0]
        if existing > 0:
            log.info(
                f"  ⚠ {existing:,} topology relationships already exist for tenant {TENANT_ID}. Skipping."
            )
            return

    t0 = _timer()
    pf = pq.ParquetFile(filepath)
    loaded = 0
    batch_num = 0

    # topology_relationships schema:
    #   id (UUID), from_entity_id, from_entity_type, relationship_type,
    #   to_entity_id, to_entity_type, tenant_id, properties, last_synced_at, created_at

    insert_sql = """
        INSERT INTO topology_relationships
            (id, from_entity_id, from_entity_type, relationship_type,
             to_entity_id, to_entity_type, tenant_id, properties,
             last_synced_at, created_at)
        VALUES %s
        ON CONFLICT (id) DO NOTHING
    """

    now = datetime.now(timezone.utc)

    with conn.cursor() as cur:
        for batch in pf.iter_batches(batch_size=BATCH_RELATIONSHIPS):
            batch_num += 1
            table = batch.to_pydict()
            n = len(table["relationship_id"])
            rows = []

            for i in range(n):
                props = table.get("properties_json", [None] * n)[i]
                domain = table.get("domain", [None] * n)[i]
                # Combine domain + properties into a single properties string
                props_str = None
                if domain or props:
                    props_dict = {}
                    if domain:
                        props_dict["domain"] = domain
                    if props:
                        try:
                            p = json.loads(props)
                            props_dict.update(p)
                        except (json.JSONDecodeError, TypeError):
                            props_dict["raw"] = props
                    props_str = json.dumps(props_dict)

                row = (
                    table["relationship_id"][i],
                    table["from_entity_id"][i],
                    table["from_entity_type"][i],
                    table["relationship_type"][i],
                    table["to_entity_id"][i],
                    table["to_entity_type"][i],
                    table["tenant_id"][i],
                    props_str,
                    now,
                    now,
                )
                rows.append(row)

            if rows:
                psycopg2.extras.execute_values(
                    cur,
                    insert_sql,
                    rows,
                    template="(%s::uuid, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    page_size=BATCH_RELATIONSHIPS,
                )

            loaded += len(rows)

            if batch_num % 20 == 0:
                conn.commit()
                log.info(f"    batch {batch_num}: {loaded:,} / {total_rows:,}")

            del table, rows
            gc.collect()

        conn.commit()

    log.info(f"  ✓ Loaded {loaded:,} topology relationships in {_elapsed(t0)}")


# ---------------------------------------------------------------------------
# Step 4: Customers + BSS
# ---------------------------------------------------------------------------


def step_4_load_customers_bss(conn, dry_run: bool = False):
    """Load customers_bss.parquet → customers + bss_service_plans + bss_billing_accounts."""
    log.info("━━━ Step 4: Load customers & BSS ━━━")
    filepath = OUTPUT_DIR / "customers_bss.parquet"
    if not _ensure_file(filepath):
        return

    total_rows = _pq_row_count(filepath)
    log.info(
        f"  Source: {filepath.name} ({total_rows:,} rows, {_file_size_mb(filepath)})"
    )

    if dry_run:
        log.info(f"  [DRY RUN] Would load {total_rows:,} customers")
        return

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM customers WHERE tenant_id = %s", (TENANT_ID,))
        existing = cur.fetchone()[0]
        if existing > 0:
            log.info(
                f"  ⚠ {existing:,} customers already exist for tenant {TENANT_ID}. Skipping."
            )
            return

    t0 = _timer()

    # --- Phase A: Discover and load unique service plans ---
    log.info("  Phase A: Loading unique service plans...")
    pf = pq.ParquetFile(filepath)
    plan_map: dict[str, str] = {}  # plan_name → plan_uuid

    for batch in pf.iter_batches(
        batch_size=50_000,
        columns=[
            "service_plan_name",
            "service_plan_tier",
            "monthly_fee",
            "sla_guarantee",
        ],
    ):
        t = batch.to_pydict()
        for i in range(len(t["service_plan_name"])):
            pname = t["service_plan_name"][i]
            if pname and pname not in plan_map:
                plan_map[pname] = str(uuid.uuid4())

    # Insert service plans
    with conn.cursor() as cur:
        for pname, puuid in plan_map.items():
            # We need tier and fee — read from data
            pass

    # Re-scan to get plan details
    plan_details: dict[str, dict] = {}
    pf = pq.ParquetFile(filepath)
    for batch in pf.iter_batches(
        batch_size=50_000,
        columns=[
            "service_plan_name",
            "service_plan_tier",
            "monthly_fee",
            "sla_guarantee",
        ],
    ):
        t = batch.to_pydict()
        for i in range(len(t["service_plan_name"])):
            pname = t["service_plan_name"][i]
            if pname and pname not in plan_details:
                plan_details[pname] = {
                    "tier": t["service_plan_tier"][i] or "BRONZE",
                    "monthly_fee": t["monthly_fee"][i] or 0.0,
                    "sla_guarantee": t.get("sla_guarantee", [None])[i]
                    if "sla_guarantee" in t
                    else None,
                }

    with conn.cursor() as cur:
        for pname, puuid in plan_map.items():
            details = plan_details.get(
                pname, {"tier": "BRONZE", "monthly_fee": 0.0, "sla_guarantee": None}
            )
            cur.execute(
                """INSERT INTO bss_service_plans (id, name, tier, monthly_fee, sla_guarantee, created_at)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   ON CONFLICT (name) DO UPDATE SET tier = EXCLUDED.tier""",
                (
                    puuid,
                    pname,
                    details["tier"],
                    details["monthly_fee"],
                    details["sla_guarantee"],
                    datetime.now(timezone.utc),
                ),
            )
        conn.commit()
    log.info(f"  ✓ Loaded {len(plan_map)} service plans")

    # Reload plan name→id map (in case of ON CONFLICT returning existing IDs)
    with conn.cursor() as cur:
        cur.execute("SELECT name, id FROM bss_service_plans")
        plan_map = {row[0]: str(row[1]) for row in cur.fetchall()}

    # --- Phase B: Load customers + billing accounts ---
    # The source data has duplicate external_ids (~367k dupes across 1M rows).
    # The DB has a UNIQUE constraint on external_id, so we deduplicate in-memory
    # keeping only the first occurrence per external_id.
    log.info("  Phase B: Loading customers + billing accounts...")
    log.info("    Deduplicating external_ids (source has duplicates)...")
    pf = pq.ParquetFile(filepath)
    loaded_customers = 0
    loaded_billing = 0
    skipped_dupes = 0
    batch_num = 0
    seen_external_ids: set[str] = set()

    customer_insert_sql = """
        INSERT INTO customers (id, external_id, name, churn_risk_score,
                               associated_site_id, tenant_id, created_at)
        VALUES %s
        ON CONFLICT (external_id) DO NOTHING
    """

    billing_insert_sql = """
        INSERT INTO bss_billing_accounts (id, customer_id, plan_id,
                                          account_status, avg_monthly_revenue,
                                          contract_end_date, last_billing_dispute)
        VALUES %s
        ON CONFLICT (id) DO NOTHING
    """

    # Track which customer UUIDs were actually inserted (for billing FK safety)
    inserted_customer_ids: set[str] = set()

    with conn.cursor() as cur:
        for batch in pf.iter_batches(batch_size=BATCH_CUSTOMERS):
            batch_num += 1
            t = batch.to_pydict()
            n = len(t["customer_id"])

            customer_rows = []
            # Temporarily hold billing data keyed by customer_id
            pending_billing: list[tuple] = []

            for i in range(n):
                cust_id = t["customer_id"][i]
                ext_id = t.get("external_id", [None] * n)[i]
                if not ext_id:
                    ext_id = f"CUST-{cust_id[:8]}"

                # Deduplicate by external_id in-memory
                if ext_id in seen_external_ids:
                    skipped_dupes += 1
                    continue
                seen_external_ids.add(ext_id)

                name = t.get("name", [None] * n)[i]
                churn = t.get("churn_risk_score", [None] * n)[i]
                site_id = t.get("associated_site_id", [None] * n)[i]

                customer_rows.append(
                    (
                        cust_id,
                        ext_id,
                        name,
                        churn,
                        site_id,
                        TENANT_ID,
                        datetime.now(timezone.utc),
                    )
                )
                inserted_customer_ids.add(cust_id)

                # Billing account
                plan_name = t.get("service_plan_name", [None] * n)[i]
                plan_id = plan_map.get(plan_name) if plan_name else None
                if plan_id:
                    acct_status = t.get("account_status", [None] * n)[i] or "ACTIVE"
                    avg_rev = t.get("avg_monthly_revenue", [None] * n)[i]
                    contract_end = t.get("contract_end_date", [None] * n)[i]

                    pending_billing.append(
                        (
                            str(uuid.uuid4()),  # billing account id
                            cust_id,  # customer_id FK
                            plan_id,  # plan_id FK
                            acct_status,
                            avg_rev,
                            contract_end,
                            None,  # last_billing_dispute
                        )
                    )

            if customer_rows:
                psycopg2.extras.execute_values(
                    cur,
                    customer_insert_sql,
                    customer_rows,
                    template="(%s::uuid, %s, %s, %s, %s, %s, %s)",
                    page_size=BATCH_CUSTOMERS,
                )
                loaded_customers += len(customer_rows)

            # Only insert billing rows whose customer_id was successfully deduped
            billing_rows = [r for r in pending_billing if r[1] in inserted_customer_ids]
            if billing_rows:
                psycopg2.extras.execute_values(
                    cur,
                    billing_insert_sql,
                    billing_rows,
                    template="(%s::uuid, %s::uuid, %s::uuid, %s, %s, %s, %s)",
                    page_size=BATCH_CUSTOMERS,
                )
                loaded_billing += len(billing_rows)

            if batch_num % 10 == 0:
                conn.commit()
                log.info(
                    f"    batch {batch_num}: {loaded_customers:,} customers, "
                    f"{loaded_billing:,} billing, {skipped_dupes:,} dupes skipped"
                )

            del t, customer_rows, billing_rows, pending_billing
            gc.collect()

        conn.commit()

    del seen_external_ids, inserted_customer_ids
    log.info(
        f"  ✓ Loaded {loaded_customers:,} customers, {loaded_billing:,} billing accounts "
        f"({skipped_dupes:,} duplicate external_ids skipped) in {_elapsed(t0)}"
    )


# ---------------------------------------------------------------------------
# Step 5: Supplementary tables (ground truth, divergence, scenarios, etc.)
# ---------------------------------------------------------------------------


def _create_supplementary_tables(conn):
    """
    Create supplementary tables that don't exist in the base Pedkai schema
    but are needed for Dark Graph / ML scoring.
    """
    log.info("  Creating supplementary tables if needed...")

    ddl_statements = [
        # Ground truth entities (separate from CMDB declared)
        """
        CREATE TABLE IF NOT EXISTS gt_network_entities (
            entity_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            name TEXT,
            external_id TEXT,
            domain TEXT,
            geo_lat DOUBLE PRECISION,
            geo_lon DOUBLE PRECISION,
            attributes JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ DEFAULT now()
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_gt_entities_tenant ON gt_network_entities(tenant_id)",
        "CREATE INDEX IF NOT EXISTS ix_gt_entities_type ON gt_network_entities(entity_type)",
        # Ground truth relationships
        """
        CREATE TABLE IF NOT EXISTS gt_entity_relationships (
            relationship_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            from_entity_id TEXT NOT NULL,
            from_entity_type TEXT NOT NULL,
            relationship_type TEXT NOT NULL,
            to_entity_id TEXT NOT NULL,
            to_entity_type TEXT NOT NULL,
            domain TEXT,
            attributes JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ DEFAULT now()
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_gt_rels_tenant ON gt_entity_relationships(tenant_id)",
        "CREATE INDEX IF NOT EXISTS ix_gt_rels_from ON gt_entity_relationships(from_entity_id)",
        "CREATE INDEX IF NOT EXISTS ix_gt_rels_to ON gt_entity_relationships(to_entity_id)",
        # Divergence manifest (ML scoring key)
        """
        CREATE TABLE IF NOT EXISTS divergence_manifest (
            divergence_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            divergence_type TEXT NOT NULL,
            entity_or_relationship TEXT,
            target_id TEXT,
            target_type TEXT,
            domain TEXT,
            description TEXT,
            attribute_name TEXT,
            ground_truth_value TEXT,
            cmdb_declared_value TEXT,
            original_external_id TEXT,
            mutated_external_id TEXT,
            created_at TIMESTAMPTZ DEFAULT now()
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_divergence_tenant ON divergence_manifest(tenant_id)",
        "CREATE INDEX IF NOT EXISTS ix_divergence_type ON divergence_manifest(divergence_type)",
        # Scenario manifest
        """
        CREATE TABLE IF NOT EXISTS scenario_manifest (
            scenario_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            scenario_type TEXT NOT NULL,
            severity TEXT,
            primary_entity_id TEXT,
            primary_entity_type TEXT,
            primary_domain TEXT,
            affected_entity_ids TEXT,
            affected_entity_count INT,
            start_hour INT,
            end_hour INT,
            duration_hours INT,
            cascade_chain TEXT,
            ramp_up_hours INT,
            ramp_down_hours INT,
            parameters_json TEXT,
            created_at TIMESTAMPTZ DEFAULT now()
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_scenario_tenant ON scenario_manifest(tenant_id)",
        "CREATE INDEX IF NOT EXISTS ix_scenario_type ON scenario_manifest(scenario_type)",
        # Scenario KPI overrides (sparse overlay)
        """
        CREATE TABLE IF NOT EXISTS scenario_kpi_overrides (
            id BIGSERIAL PRIMARY KEY,
            entity_id TEXT NOT NULL,
            tenant_id TEXT NOT NULL,
            timestamp TIMESTAMPTZ NOT NULL,
            kpi_column TEXT NOT NULL,
            override_value FLOAT,
            scenario_id TEXT REFERENCES scenario_manifest(scenario_id),
            scenario_type TEXT,
            source_file TEXT
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_sko_entity_ts ON scenario_kpi_overrides(entity_id, timestamp)",
        "CREATE INDEX IF NOT EXISTS ix_sko_scenario ON scenario_kpi_overrides(scenario_id)",
        "CREATE INDEX IF NOT EXISTS ix_sko_tenant ON scenario_kpi_overrides(tenant_id)",
        # Neighbour relations
        """
        CREATE TABLE IF NOT EXISTS neighbour_relations (
            relation_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            from_cell_id TEXT NOT NULL,
            from_cell_rat TEXT,
            from_cell_band TEXT,
            to_cell_id TEXT NOT NULL,
            to_cell_rat TEXT,
            to_cell_band TEXT,
            neighbour_type TEXT,
            is_intra_site BOOLEAN,
            distance_m DOUBLE PRECISION,
            handover_attempts DOUBLE PRECISION,
            handover_success_rate DOUBLE PRECISION,
            cio_offset_db DOUBLE PRECISION,
            no_remove_flag BOOLEAN,
            created_at TIMESTAMPTZ DEFAULT now()
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_nbr_tenant ON neighbour_relations(tenant_id)",
        "CREATE INDEX IF NOT EXISTS ix_nbr_from ON neighbour_relations(from_cell_id)",
        "CREATE INDEX IF NOT EXISTS ix_nbr_to ON neighbour_relations(to_cell_id)",
        # Vendor naming map
        """
        CREATE TABLE IF NOT EXISTS vendor_naming_map (
            mapping_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            internal_name TEXT,
            domain TEXT,
            vendor TEXT,
            vendor_counter_name TEXT,
            vendor_system TEXT,
            unit TEXT,
            description TEXT,
            counter_family TEXT,
            three_gpp_ref TEXT,
            created_at TIMESTAMPTZ DEFAULT now()
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_vnm_tenant ON vendor_naming_map(tenant_id)",
        # Events / alarms (dedicated table for scenario-generated alarms)
        """
        CREATE TABLE IF NOT EXISTS telco_events_alarms (
            alarm_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            entity_type TEXT,
            alarm_type TEXT NOT NULL,
            severity TEXT,
            raised_at TIMESTAMPTZ,
            cleared_at TIMESTAMPTZ,
            source_system TEXT,
            probable_cause TEXT,
            domain TEXT,
            scenario_id TEXT,
            is_synthetic_scenario BOOLEAN DEFAULT false,
            additional_text TEXT,
            correlation_group_id TEXT,
            created_at TIMESTAMPTZ DEFAULT now()
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_tea_tenant ON telco_events_alarms(tenant_id)",
        "CREATE INDEX IF NOT EXISTS ix_tea_entity ON telco_events_alarms(entity_id)",
        "CREATE INDEX IF NOT EXISTS ix_tea_type ON telco_events_alarms(alarm_type)",
        "CREATE INDEX IF NOT EXISTS ix_tea_raised ON telco_events_alarms(raised_at)",
        "CREATE INDEX IF NOT EXISTS ix_tea_scenario ON telco_events_alarms(scenario_id)",
        "CREATE INDEX IF NOT EXISTS ix_tea_corr ON telco_events_alarms(correlation_group_id)",
        # KPI dataset registry (for external Parquet file references)
        """
        CREATE TABLE IF NOT EXISTS kpi_dataset_registry (
            dataset_name TEXT NOT NULL,
            tenant_id TEXT NOT NULL,
            file_path TEXT NOT NULL,
            total_rows BIGINT,
            total_columns INT,
            file_size_bytes BIGINT,
            schema_json JSONB,
            registered_at TIMESTAMPTZ DEFAULT now(),
            PRIMARY KEY (dataset_name, tenant_id)
        )
        """,
    ]

    with conn.cursor() as cur:
        for ddl in ddl_statements:
            cur.execute(ddl)
    conn.commit()
    log.info("  ✓ Supplementary tables ready")


def step_5_load_ground_truth(conn, dry_run: bool = False):
    """Load ground truth entities and relationships."""
    log.info("━━━ Step 5: Load ground truth entities & relationships ━━━")
    _create_supplementary_tables(conn)

    # --- Ground truth entities ---
    filepath = OUTPUT_DIR / "ground_truth_entities.parquet"
    if _ensure_file(filepath):
        total_rows = _pq_row_count(filepath)
        log.info(f"  GT Entities: {filepath.name} ({total_rows:,} rows)")

        if dry_run:
            log.info(f"  [DRY RUN] Would load {total_rows:,} GT entities")
        else:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM gt_network_entities WHERE tenant_id = %s",
                    (TENANT_ID,),
                )
                if cur.fetchone()[0] > 0:
                    log.info(
                        f"  ⚠ GT entities already loaded for {TENANT_ID}. Skipping."
                    )
                else:
                    t0 = _timer()
                    pf = pq.ParquetFile(filepath)
                    loaded = 0

                    # GT entities have the same schema as cmdb_declared_entities
                    ATTR_COLS = [
                        "domain",
                        "site_id",
                        "site_type",
                        "deployment_profile",
                        "province",
                        "timezone",
                        "vendor",
                        "rat_type",
                        "band",
                        "bandwidth_mhz",
                        "max_tx_power_dbm",
                        "max_prbs",
                        "frequency_mhz",
                        "sector_id",
                        "azimuth_deg",
                        "electrical_tilt_deg",
                        "antenna_height_m",
                        "inter_site_distance_m",
                        "revenue_weight",
                        "sla_tier",
                        "is_nsa_anchor",
                        "nsa_anchor_cell_id",
                        "parent_entity_id",
                        "properties_json",
                    ]

                    insert_sql = """
                        INSERT INTO gt_network_entities
                            (entity_id, tenant_id, entity_type, name, external_id,
                             domain, geo_lat, geo_lon, attributes)
                        VALUES %s
                        ON CONFLICT (entity_id) DO NOTHING
                    """

                    batch_num = 0
                    for batch in pf.iter_batches(batch_size=BATCH_ENTITIES):
                        batch_num += 1
                        t = batch.to_pydict()
                        n = len(t["entity_id"])
                        rows = []
                        for i in range(n):
                            attrs = {}
                            for col in ATTR_COLS:
                                if col in t and t[col][i] is not None:
                                    attrs[col] = t[col][i]
                            rows.append(
                                (
                                    t["entity_id"][i],
                                    t["tenant_id"][i],
                                    t["entity_type"][i],
                                    t["name"][i],
                                    t.get("external_id", [None] * n)[i],
                                    t.get("domain", [None] * n)[i],
                                    t.get("geo_lat", [None] * n)[i],
                                    t.get("geo_lon", [None] * n)[i],
                                    json.dumps(attrs),
                                )
                            )
                        psycopg2.extras.execute_values(
                            cur,
                            insert_sql,
                            rows,
                            template="(%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)",
                            page_size=BATCH_ENTITIES,
                        )
                        loaded += n
                        if batch_num % 10 == 0:
                            conn.commit()
                            log.info(f"    GT entities batch {batch_num}: {loaded:,}")
                        del t, rows
                        gc.collect()
                    conn.commit()
                    log.info(f"  ✓ Loaded {loaded:,} GT entities in {_elapsed(t0)}")

    # --- Ground truth relationships ---
    filepath = OUTPUT_DIR / "ground_truth_relationships.parquet"
    if _ensure_file(filepath):
        total_rows = _pq_row_count(filepath)
        log.info(f"  GT Relationships: {filepath.name} ({total_rows:,} rows)")

        if dry_run:
            log.info(f"  [DRY RUN] Would load {total_rows:,} GT relationships")
        else:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM gt_entity_relationships WHERE tenant_id = %s",
                    (TENANT_ID,),
                )
                if cur.fetchone()[0] > 0:
                    log.info(
                        f"  ⚠ GT relationships already loaded for {TENANT_ID}. Skipping."
                    )
                else:
                    t0 = _timer()
                    pf = pq.ParquetFile(filepath)
                    loaded = 0

                    insert_sql = """
                        INSERT INTO gt_entity_relationships
                            (relationship_id, tenant_id, from_entity_id, from_entity_type,
                             relationship_type, to_entity_id, to_entity_type, domain, attributes)
                        VALUES %s
                        ON CONFLICT (relationship_id) DO NOTHING
                    """

                    batch_num = 0
                    for batch in pf.iter_batches(batch_size=BATCH_RELATIONSHIPS):
                        batch_num += 1
                        t = batch.to_pydict()
                        n = len(t["relationship_id"])
                        rows = []
                        for i in range(n):
                            attrs = {}
                            if t.get("properties_json") and t["properties_json"][i]:
                                try:
                                    attrs = json.loads(t["properties_json"][i])
                                except (json.JSONDecodeError, TypeError):
                                    pass
                            rows.append(
                                (
                                    t["relationship_id"][i],
                                    t["tenant_id"][i],
                                    t["from_entity_id"][i],
                                    t["from_entity_type"][i],
                                    t["relationship_type"][i],
                                    t["to_entity_id"][i],
                                    t["to_entity_type"][i],
                                    t.get("domain", [None] * n)[i],
                                    json.dumps(attrs),
                                )
                            )
                        psycopg2.extras.execute_values(
                            cur,
                            insert_sql,
                            rows,
                            template="(%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)",
                            page_size=BATCH_RELATIONSHIPS,
                        )
                        loaded += n
                        if batch_num % 20 == 0:
                            conn.commit()
                            log.info(f"    GT rels batch {batch_num}: {loaded:,}")
                        del t, rows
                        gc.collect()
                    conn.commit()
                    log.info(
                        f"  ✓ Loaded {loaded:,} GT relationships in {_elapsed(t0)}"
                    )


def step_6_load_divergence_manifest(conn, dry_run: bool = False):
    """Load divergence_manifest.parquet → divergence_manifest table."""
    log.info("━━━ Step 6: Load divergence manifest ━━━")
    filepath = OUTPUT_DIR / "divergence_manifest.parquet"
    if not _ensure_file(filepath):
        return

    total_rows = _pq_row_count(filepath)
    log.info(f"  Source: {filepath.name} ({total_rows:,} rows)")

    if dry_run:
        log.info(f"  [DRY RUN] Would load {total_rows:,} divergence records")
        return

    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM divergence_manifest WHERE tenant_id = %s",
            (TENANT_ID,),
        )
        if cur.fetchone()[0] > 0:
            log.info(
                f"  ⚠ Divergence manifest already loaded for {TENANT_ID}. Skipping."
            )
            return

    t0 = _timer()
    pf = pq.ParquetFile(filepath)
    loaded = 0
    batch_num = 0

    insert_sql = """
        INSERT INTO divergence_manifest
            (divergence_id, tenant_id, divergence_type, entity_or_relationship,
             target_id, target_type, domain, description, attribute_name,
             ground_truth_value, cmdb_declared_value,
             original_external_id, mutated_external_id)
        VALUES %s
        ON CONFLICT (divergence_id) DO NOTHING
    """

    with conn.cursor() as cur:
        for batch in pf.iter_batches(batch_size=BATCH_ENTITIES):
            batch_num += 1
            t = batch.to_pydict()
            n = len(t["divergence_id"])
            rows = []
            for i in range(n):
                rows.append(
                    (
                        t["divergence_id"][i],
                        t["tenant_id"][i],
                        t["divergence_type"][i],
                        t.get("entity_or_relationship", [None] * n)[i],
                        t.get("target_id", [None] * n)[i],
                        t.get("target_type", [None] * n)[i],
                        t.get("domain", [None] * n)[i],
                        t.get("description", [None] * n)[i],
                        t.get("attribute_name", [None] * n)[i],
                        t.get("ground_truth_value", [None] * n)[i],
                        t.get("cmdb_declared_value", [None] * n)[i],
                        t.get("original_external_id", [None] * n)[i],
                        t.get("mutated_external_id", [None] * n)[i],
                    )
                )
            psycopg2.extras.execute_values(
                cur, insert_sql, rows, page_size=BATCH_ENTITIES
            )
            loaded += n
            if batch_num % 5 == 0:
                conn.commit()
                log.info(f"    batch {batch_num}: {loaded:,}")
            del t, rows
            gc.collect()
        conn.commit()

    log.info(f"  ✓ Loaded {loaded:,} divergence records in {_elapsed(t0)}")


def step_7_load_scenarios(conn, dry_run: bool = False):
    """Load scenario_manifest + scenario_kpi_overrides."""
    log.info("━━━ Step 7: Load scenarios ━━━")

    # --- Scenario manifest ---
    filepath = OUTPUT_DIR / "scenario_manifest.parquet"
    if _ensure_file(filepath):
        total_rows = _pq_row_count(filepath)
        log.info(f"  Scenario manifest: {filepath.name} ({total_rows:,} rows)")

        if dry_run:
            log.info(f"  [DRY RUN] Would load {total_rows:,} scenarios")
        else:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM scenario_manifest WHERE tenant_id = %s",
                    (TENANT_ID,),
                )
                if cur.fetchone()[0] > 0:
                    log.info(
                        f"  ⚠ Scenario manifest already loaded for {TENANT_ID}. Skipping."
                    )
                else:
                    t0 = _timer()
                    pf = pq.ParquetFile(filepath)
                    loaded = 0

                    insert_sql = """
                        INSERT INTO scenario_manifest
                            (scenario_id, tenant_id, scenario_type, severity,
                             primary_entity_id, primary_entity_type, primary_domain,
                             affected_entity_ids, affected_entity_count,
                             start_hour, end_hour, duration_hours,
                             cascade_chain, ramp_up_hours, ramp_down_hours, parameters_json)
                        VALUES %s
                        ON CONFLICT (scenario_id) DO NOTHING
                    """

                    for batch in pf.iter_batches(batch_size=BATCH_ENTITIES):
                        t = batch.to_pydict()
                        n = len(t["scenario_id"])
                        rows = []
                        for i in range(n):
                            rows.append(
                                tuple(
                                    t.get(col, [None] * n)[i]
                                    for col in [
                                        "scenario_id",
                                        "tenant_id",
                                        "scenario_type",
                                        "severity",
                                        "primary_entity_id",
                                        "primary_entity_type",
                                        "primary_domain",
                                        "affected_entity_ids",
                                        "affected_entity_count",
                                        "start_hour",
                                        "end_hour",
                                        "duration_hours",
                                        "cascade_chain",
                                        "ramp_up_hours",
                                        "ramp_down_hours",
                                        "parameters_json",
                                    ]
                                )
                            )
                        psycopg2.extras.execute_values(
                            cur, insert_sql, rows, page_size=BATCH_ENTITIES
                        )
                        loaded += n
                        del t, rows
                    conn.commit()
                    log.info(f"  ✓ Loaded {loaded:,} scenarios in {_elapsed(t0)}")

    # --- Scenario KPI overrides ---
    filepath = OUTPUT_DIR / "scenario_kpi_overrides.parquet"
    if _ensure_file(filepath):
        total_rows = _pq_row_count(filepath)
        log.info(f"  Scenario overrides: {filepath.name} ({total_rows:,} rows)")

        if dry_run:
            log.info(f"  [DRY RUN] Would load {total_rows:,} KPI overrides")
        else:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM scenario_kpi_overrides WHERE tenant_id = %s",
                    (TENANT_ID,),
                )
                if cur.fetchone()[0] > 0:
                    log.info(
                        f"  ⚠ Scenario overrides already loaded for {TENANT_ID}. Skipping."
                    )
                else:
                    t0 = _timer()
                    pf = pq.ParquetFile(filepath)
                    loaded = 0
                    batch_num = 0

                    insert_sql = """
                        INSERT INTO scenario_kpi_overrides
                            (entity_id, tenant_id, timestamp, kpi_column,
                             override_value, scenario_id, scenario_type, source_file)
                        VALUES %s
                    """

                    for batch in pf.iter_batches(batch_size=BATCH_KPI_LONG):
                        batch_num += 1
                        t = batch.to_pydict()
                        n = len(t["entity_id"])
                        rows = []
                        for i in range(n):
                            rows.append(
                                (
                                    t["entity_id"][i],
                                    t["tenant_id"][i],
                                    t["timestamp"][i],
                                    t["kpi_column"][i],
                                    t["override_value"][i],
                                    t.get("scenario_id", [None] * n)[i],
                                    t.get("scenario_type", [None] * n)[i],
                                    t.get("source_file", [None] * n)[i],
                                )
                            )
                        psycopg2.extras.execute_values(
                            cur, insert_sql, rows, page_size=BATCH_KPI_LONG
                        )
                        loaded += n
                        if batch_num % 10 == 0:
                            conn.commit()
                            log.info(
                                f"    overrides batch {batch_num}: {loaded:,} / {total_rows:,}"
                            )
                        del t, rows
                        gc.collect()
                    conn.commit()
                    log.info(
                        f"  ✓ Loaded {loaded:,} scenario KPI overrides in {_elapsed(t0)}"
                    )


def step_8_load_events_alarms(conn, dry_run: bool = False):
    """Load events_alarms.parquet → telco_events_alarms table."""
    log.info("━━━ Step 8: Load events & alarms ━━━")
    filepath = OUTPUT_DIR / "events_alarms.parquet"
    if not _ensure_file(filepath):
        return

    total_rows = _pq_row_count(filepath)
    log.info(f"  Source: {filepath.name} ({total_rows:,} rows)")

    if dry_run:
        log.info(f"  [DRY RUN] Would load {total_rows:,} events/alarms")
        return

    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM telco_events_alarms WHERE tenant_id = %s",
            (TENANT_ID,),
        )
        if cur.fetchone()[0] > 0:
            log.info(f"  ⚠ Events already loaded for {TENANT_ID}. Skipping.")
            return

    t0 = _timer()
    pf = pq.ParquetFile(filepath)
    loaded = 0

    insert_sql = """
        INSERT INTO telco_events_alarms
            (alarm_id, tenant_id, entity_id, entity_type, alarm_type,
             severity, raised_at, cleared_at, source_system, probable_cause,
             domain, scenario_id, is_synthetic_scenario, additional_text,
             correlation_group_id)
        VALUES %s
        ON CONFLICT (alarm_id) DO NOTHING
    """

    with conn.cursor() as cur:
        for batch in pf.iter_batches(batch_size=5000):
            t = batch.to_pydict()
            n = len(t["alarm_id"])
            rows = []
            for i in range(n):
                rows.append(
                    tuple(
                        t.get(col, [None] * n)[i]
                        for col in [
                            "alarm_id",
                            "tenant_id",
                            "entity_id",
                            "entity_type",
                            "alarm_type",
                            "severity",
                            "raised_at",
                            "cleared_at",
                            "source_system",
                            "probable_cause",
                            "domain",
                            "scenario_id",
                            "is_synthetic_scenario",
                            "additional_text",
                            "correlation_group_id",
                        ]
                    )
                )
            psycopg2.extras.execute_values(cur, insert_sql, rows, page_size=5000)
            loaded += n
            del t, rows
        conn.commit()

    log.info(f"  ✓ Loaded {loaded:,} events/alarms in {_elapsed(t0)}")


def step_9_load_neighbour_relations(conn, dry_run: bool = False):
    """Load neighbour_relations.parquet → neighbour_relations table."""
    log.info("━━━ Step 9: Load neighbour relations ━━━")
    filepath = OUTPUT_DIR / "neighbour_relations.parquet"
    if not _ensure_file(filepath):
        return

    total_rows = _pq_row_count(filepath)
    log.info(f"  Source: {filepath.name} ({total_rows:,} rows)")

    if dry_run:
        log.info(f"  [DRY RUN] Would load {total_rows:,} neighbour relations")
        return

    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM neighbour_relations WHERE tenant_id = %s",
            (TENANT_ID,),
        )
        if cur.fetchone()[0] > 0:
            log.info(
                f"  ⚠ Neighbour relations already loaded for {TENANT_ID}. Skipping."
            )
            return

    t0 = _timer()
    pf = pq.ParquetFile(filepath)
    loaded = 0
    batch_num = 0

    insert_sql = """
        INSERT INTO neighbour_relations
            (relation_id, tenant_id, from_cell_id, from_cell_rat, from_cell_band,
             to_cell_id, to_cell_rat, to_cell_band, neighbour_type,
             is_intra_site, distance_m, handover_attempts, handover_success_rate,
             cio_offset_db, no_remove_flag)
        VALUES %s
        ON CONFLICT (relation_id) DO NOTHING
    """

    with conn.cursor() as cur:
        for batch in pf.iter_batches(batch_size=BATCH_ENTITIES):
            batch_num += 1
            t = batch.to_pydict()
            n = len(t["relation_id"])
            rows = []
            for i in range(n):
                rows.append(
                    tuple(
                        t.get(col, [None] * n)[i]
                        for col in [
                            "relation_id",
                            "tenant_id",
                            "from_cell_id",
                            "from_cell_rat",
                            "from_cell_band",
                            "to_cell_id",
                            "to_cell_rat",
                            "to_cell_band",
                            "neighbour_type",
                            "is_intra_site",
                            "distance_m",
                            "handover_attempts",
                            "handover_success_rate",
                            "cio_offset_db",
                            "no_remove_flag",
                        ]
                    )
                )
            psycopg2.extras.execute_values(
                cur, insert_sql, rows, page_size=BATCH_ENTITIES
            )
            loaded += n
            if batch_num % 10 == 0:
                conn.commit()
                log.info(f"    batch {batch_num}: {loaded:,} / {total_rows:,}")
            del t, rows
            gc.collect()
        conn.commit()

    log.info(f"  ✓ Loaded {loaded:,} neighbour relations in {_elapsed(t0)}")


def step_10_load_vendor_naming(conn, dry_run: bool = False):
    """Load vendor_naming_map.parquet → vendor_naming_map table."""
    log.info("━━━ Step 10: Load vendor naming map ━━━")
    filepath = OUTPUT_DIR / "vendor_naming_map.parquet"
    if not _ensure_file(filepath):
        return

    total_rows = _pq_row_count(filepath)
    log.info(f"  Source: {filepath.name} ({total_rows:,} rows)")

    if dry_run:
        log.info(f"  [DRY RUN] Would load {total_rows:,} vendor naming entries")
        return

    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM vendor_naming_map WHERE tenant_id = %s", (TENANT_ID,)
        )
        if cur.fetchone()[0] > 0:
            log.info(f"  ⚠ Vendor naming already loaded for {TENANT_ID}. Skipping.")
            return

    t0 = _timer()
    pf = pq.ParquetFile(filepath)
    table = pf.read().to_pydict()
    n = len(table["mapping_id"])

    insert_sql = """
        INSERT INTO vendor_naming_map
            (mapping_id, tenant_id, internal_name, domain, vendor,
             vendor_counter_name, vendor_system, unit, description,
             counter_family, three_gpp_ref)
        VALUES %s
        ON CONFLICT (mapping_id) DO NOTHING
    """

    rows = []
    for i in range(n):
        rows.append(
            tuple(
                table.get(col, [None] * n)[i]
                for col in [
                    "mapping_id",
                    "tenant_id",
                    "internal_name",
                    "domain",
                    "vendor",
                    "vendor_counter_name",
                    "vendor_system",
                    "unit",
                    "description",
                    "counter_family",
                    "three_gpp_ref",
                ]
            )
        )

    with conn.cursor() as cur:
        psycopg2.extras.execute_values(cur, insert_sql, rows, page_size=1000)
    conn.commit()

    log.info(f"  ✓ Loaded {n:,} vendor naming entries in {_elapsed(t0)}")


# ---------------------------------------------------------------------------
# Step 11: Register KPI files as external Parquet datasets
# ---------------------------------------------------------------------------


def step_11_register_kpi_datasets(conn, dry_run: bool = False):
    """
    Register KPI Parquet files as external datasets — NOT exploded to long format.

    Long-format explosion warning from Phase 11 instructions:
      Radio KPIs alone: 47.6M rows × 35 KPI columns = ~1.67 billion long-format rows.
      KPI files are registered as external Parquet datasets; Pedkai queries them via
      DuckDB/Arrow Flight at query time.
    """
    log.info("━━━ Step 11: Register KPI datasets (external Parquet) ━━━")

    kpi_files = [
        ("kpi_radio_wide", "kpi_metrics_wide.parquet"),
        ("kpi_transport_wide", "transport_kpis_wide.parquet"),
        ("kpi_fixed_bb_wide", "fixed_broadband_kpis_wide.parquet"),
        ("kpi_enterprise_wide", "enterprise_circuit_kpis_wide.parquet"),
        ("kpi_core_wide", "core_element_kpis_wide.parquet"),
        ("kpi_power_env", "power_environment_kpis.parquet"),
    ]

    for dataset_name, filename in kpi_files:
        filepath = OUTPUT_DIR / filename
        if not filepath.exists():
            log.info(f"  ⊘ {filename} — not found, skipping")
            continue

        pf = pq.ParquetFile(filepath)
        total_rows = pf.metadata.num_rows
        total_cols = pf.metadata.num_columns
        file_size = filepath.stat().st_size
        file_size_mb = file_size / (1024 * 1024)

        # Extract schema info
        schema = pf.schema_arrow
        schema_info = {
            schema.names[j]: str(schema.field(j).type) for j in range(len(schema.names))
        }

        log.info(
            f"  {filename}: {total_rows:,} rows, {total_cols} cols, "
            f"{file_size_mb:.1f} MB → registered as '{dataset_name}'"
        )

        if dry_run:
            continue

        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO kpi_dataset_registry
                       (dataset_name, tenant_id, file_path, total_rows,
                        total_columns, file_size_bytes, schema_json)
                   VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
                   ON CONFLICT (dataset_name, tenant_id) DO UPDATE SET
                       file_path = EXCLUDED.file_path,
                       total_rows = EXCLUDED.total_rows,
                       total_columns = EXCLUDED.total_columns,
                       file_size_bytes = EXCLUDED.file_size_bytes,
                       schema_json = EXCLUDED.schema_json,
                       registered_at = now()
                """,
                (
                    dataset_name,
                    TENANT_ID,
                    str(filepath),
                    total_rows,
                    total_cols,
                    file_size,
                    json.dumps(schema_info),
                ),
            )
        conn.commit()

    if not dry_run:
        log.info(
            "  ✓ All KPI datasets registered (external Parquet — no row explosion)"
        )
    else:
        log.info("  [DRY RUN] Would register all KPI datasets above")


# ---------------------------------------------------------------------------
# Step 12: (Optional) Load a small KPI sample into TimescaleDB
# ---------------------------------------------------------------------------


def step_12_load_kpi_sample(
    metrics_conn, graph_conn, dry_run: bool = False, sample_hours: int = 24
):
    """
    Optionally load a small sample of KPI data into TimescaleDB kpi_metrics
    table for the anomaly detection / sleeping cell detector to work with.

    By default loads the first 24 hours of radio KPIs for a subset of cells.
    This is a long-format pivot: wide → (entity_id, metric_name, metric_value, timestamp).
    """
    log.info(f"━━━ Step 12: Load KPI sample into TimescaleDB ({sample_hours}h) ━━━")
    filepath = OUTPUT_DIR / "kpi_metrics_wide.parquet"
    if not _ensure_file(filepath):
        return

    if dry_run:
        # Estimate
        pf = pq.ParquetFile(filepath)
        total_rows = pf.metadata.num_rows
        estimated_sample = min(total_rows, 66_000 * sample_hours)  # ~66k cells × hours
        kpi_cols = 35
        log.info(
            f"  [DRY RUN] Would load ~{estimated_sample:,} wide rows "
            f"× {kpi_cols} KPIs = ~{estimated_sample * kpi_cols:,} long-format rows "
            f"into TimescaleDB kpi_metrics"
        )
        return

    with metrics_conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM kpi_metrics WHERE tenant_id = %s", (TENANT_ID,)
        )
        existing = cur.fetchone()[0]
        if existing > 0:
            log.info(
                f"  ⚠ {existing:,} KPI rows already exist for {TENANT_ID} in TimescaleDB. Skipping."
            )
            return

    t0 = _timer()

    # KPI columns to pivot (exclude metadata columns)
    METADATA_COLS = {
        "cell_id",
        "tenant_id",
        "timestamp",
        "rat_type",
        "band",
        "site_id",
        "vendor",
        "deployment_profile",
        "is_nsa_scg_leg",
    }

    pf = pq.ParquetFile(filepath)
    all_cols = [pf.schema_arrow.names[j] for j in range(len(pf.schema_arrow.names))]
    kpi_cols = [c for c in all_cols if c not in METADATA_COLS]

    log.info(f"  {len(kpi_cols)} KPI columns to pivot to long format")
    log.info(f"  Reading first {sample_hours} hours (row group scan)...")

    # Read in batches, filter by timestamp <= epoch + sample_hours
    from datetime import timedelta

    epoch = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    cutoff = epoch + timedelta(hours=sample_hours)

    loaded = 0
    wide_rows_processed = 0
    batch_num = 0
    _prev_wide = 0

    insert_sql = """
        INSERT INTO kpi_metrics (timestamp, tenant_id, entity_id, metric_name, metric_value, metadata)
        VALUES %s
        ON CONFLICT DO NOTHING
    """

    with metrics_conn.cursor() as cur:
        for batch in pf.iter_batches(batch_size=5000):
            batch_num += 1
            t = batch.to_pydict()
            n = len(t["cell_id"])

            rows = []
            for i in range(n):
                ts = t["timestamp"][i]
                # Handle timestamp comparison
                if hasattr(ts, "timestamp"):
                    # It's a datetime-like object
                    if ts > cutoff:
                        continue
                else:
                    continue

                cell_id = t["cell_id"][i]
                tenant = t["tenant_id"][i]
                wide_rows_processed += 1

                # Build metadata JSONB once per wide row
                meta = {}
                for mcol in [
                    "rat_type",
                    "band",
                    "site_id",
                    "vendor",
                    "deployment_profile",
                ]:
                    if mcol in t and t[mcol][i] is not None:
                        meta[mcol] = t[mcol][i]
                meta_json = json.dumps(meta)

                for kpi_col in kpi_cols:
                    val = t.get(kpi_col, [None] * n)[i]
                    if val is not None:
                        rows.append(
                            (
                                ts,
                                tenant,
                                cell_id,
                                kpi_col,
                                float(val),
                                meta_json,
                            )
                        )

            if rows:
                psycopg2.extras.execute_values(
                    cur,
                    insert_sql,
                    rows,
                    template="(%s, %s, %s, %s, %s, %s::jsonb)",
                    page_size=BATCH_KPI_LONG,
                )
                loaded += len(rows)

            if batch_num % 50 == 0:
                metrics_conn.commit()
                log.info(
                    f"    batch {batch_num}: {wide_rows_processed:,} wide rows → "
                    f"{loaded:,} long-format KPI rows"
                )

            del t, rows
            gc.collect()

            # Stop once we've gone past the cutoff window.
            # The data is time-ordered, so once a full batch yields zero
            # qualifying rows we know every subsequent batch will also be
            # beyond the cutoff — no point scanning the remaining file.
            if wide_rows_processed > 0 and n > 0 and loaded > 0:
                # We had data before; check if this batch added nothing
                if batch_num > 1 and wide_rows_processed == _prev_wide:
                    log.info(
                        f"    All rows in batch {batch_num} past {sample_hours}h cutoff — stopping scan."
                    )
                    break
            _prev_wide = wide_rows_processed

        metrics_conn.commit()

    log.info(
        f"  ✓ Loaded {loaded:,} long-format KPI rows "
        f"(from {wide_rows_processed:,} wide rows, {sample_hours}h sample) "
        f"in {_elapsed(t0)}"
    )


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def print_summary(conn, metrics_conn):
    """Print a summary of loaded data."""
    log.info("\n" + "=" * 70)
    log.info("  LOAD SUMMARY — Tenant: %s (%s)", TENANT_ID, TENANT_DISPLAY_NAME)
    log.info("=" * 70)

    tables = [
        ("network_entities", "Graph DB"),
        ("entity_relationships", "Graph DB"),
        ("topology_relationships", "Graph DB"),
        ("customers", "Graph DB"),
        ("bss_service_plans", "Graph DB"),
        ("bss_billing_accounts", "Graph DB"),
        ("gt_network_entities", "Graph DB"),
        ("gt_entity_relationships", "Graph DB"),
        ("divergence_manifest", "Graph DB"),
        ("scenario_manifest", "Graph DB"),
        ("scenario_kpi_overrides", "Graph DB"),
        ("telco_events_alarms", "Graph DB"),
        ("neighbour_relations", "Graph DB"),
        ("vendor_naming_map", "Graph DB"),
        ("kpi_dataset_registry", "Graph DB"),
    ]

    for table_name, db_label in tables:
        try:
            with conn.cursor() as cur:
                # Check if table has tenant_id column
                cur.execute(
                    "SELECT COUNT(*) FROM information_schema.columns "
                    "WHERE table_name = %s AND column_name = 'tenant_id'",
                    (table_name,),
                )
                has_tenant = cur.fetchone()[0] > 0

                if has_tenant:
                    cur.execute(
                        f'SELECT COUNT(*) FROM "{table_name}" WHERE tenant_id = %s',
                        (TENANT_ID,),
                    )
                else:
                    cur.execute(f'SELECT COUNT(*) FROM "{table_name}"')

                count = cur.fetchone()[0]
                log.info(f"  {table_name:40s} [{db_label:10s}]: {count:>12,} rows")
        except Exception as e:
            log.info(
                f"  {table_name:40s} [{db_label:10s}]: (table not found or error: {e})"
            )
            conn.rollback()

    # TimescaleDB
    try:
        with metrics_conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM kpi_metrics WHERE tenant_id = %s", (TENANT_ID,)
            )
            count = cur.fetchone()[0]
            log.info(f"  {'kpi_metrics':40s} [{'Metrics DB':10s}]: {count:>12,} rows")
    except Exception as e:
        log.info(f"  {'kpi_metrics':40s} [{'Metrics DB':10s}]: (error: {e})")

    log.info("=" * 70)


# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------


STEPS = {
    0: ("Create tenant", step_0_create_tenant),
    1: ("Load network entities", step_1_load_network_entities),
    2: ("Load entity relationships", step_2_load_entity_relationships),
    3: ("Load topology relationships", step_3_load_topology_relationships),
    4: ("Load customers & BSS", step_4_load_customers_bss),
    5: ("Load ground truth", step_5_load_ground_truth),
    6: ("Load divergence manifest", step_6_load_divergence_manifest),
    7: ("Load scenarios", step_7_load_scenarios),
    8: ("Load events & alarms", step_8_load_events_alarms),
    9: ("Load neighbour relations", step_9_load_neighbour_relations),
    10: ("Load vendor naming map", step_10_load_vendor_naming),
    11: ("Register KPI datasets", step_11_register_kpi_datasets),
    12: ("Load KPI sample to TimescaleDB", None),  # special handling
}


def main():
    parser = argparse.ArgumentParser(
        description="Telco2 Tenant Data Loader — Phase 11 for Pedkai",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Steps:
   0  Create tenant
   1  Load network entities (CMDB declared → network_entities)
   2  Load entity relationships (CMDB declared → entity_relationships)
   3  Load topology relationships (for graph API)
   4  Load customers & BSS
   5  Load ground truth entities & relationships
   6  Load divergence manifest
   7  Load scenarios (manifest + KPI overrides)
   8  Load events & alarms
   9  Load neighbour relations
  10  Load vendor naming map
  11  Register KPI files as external Parquet datasets
  12  [Optional] Load KPI sample into TimescaleDB

Examples:
  # Dry run (validate everything, load nothing)
  python -m backend.app.scripts.load_telco2_tenant --dry-run

  # Load everything except KPI sample
  python -m backend.app.scripts.load_telco2_tenant

  # Load only step 1 (entities)
  python -m backend.app.scripts.load_telco2_tenant --step 1

  # Load with 48-hour KPI sample to TimescaleDB
  python -m backend.app.scripts.load_telco2_tenant --kpi-sample-hours 48

  # Clean and reload (DANGER)
  python -m backend.app.scripts.load_telco2_tenant --clean
        """,
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Validate files without loading"
    )
    parser.add_argument(
        "--step", type=int, default=None, help="Run only a specific step (0-12)"
    )
    parser.add_argument(
        "--skip-kpi-sample",
        action="store_true",
        help="Skip step 12 (KPI sample to TimescaleDB)",
    )
    parser.add_argument(
        "--kpi-sample-hours",
        type=int,
        default=0,
        help="Hours of KPI data to load into TimescaleDB (0=skip, default=0)",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Delete all existing Telco2 data before loading (DANGER)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable verbose logging"
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    log.info("╔══════════════════════════════════════════════════════════════╗")
    log.info("║   Pedkai — Telco2 Tenant Data Loader (Phase 11)            ║")
    log.info("╚══════════════════════════════════════════════════════════════╝")
    log.info(f"  Tenant ID:   {TENANT_ID}")
    log.info(f"  Data source: {OUTPUT_DIR}")
    log.info(f"  Graph DB:    localhost:5432/pedkai")
    log.info(f"  Metrics DB:  localhost:5433/pedkai_metrics")
    log.info(f"  Dry run:     {args.dry_run}")
    if args.step is not None:
        log.info(f"  Single step: {args.step}")
    log.info("")

    # Verify data directory
    if not OUTPUT_DIR.exists():
        log.error(f"Data directory not found: {OUTPUT_DIR}")
        log.error(
            "Ensure the Telco2 data is at /Volumes/Projects/Pedkai Data Store/Telco2/output/"
        )
        sys.exit(1)

    # File inventory
    log.info("File inventory:")
    total_size = 0
    for p in sorted(OUTPUT_DIR.glob("*.parquet")):
        size = p.stat().st_size
        total_size += size
        rows = _pq_row_count(p)
        log.info(f"  {p.name:45s} {rows:>14,} rows  {size / (1024 * 1024):>10.1f} MB")
    log.info(
        f"  {'TOTAL':45s} {'':>14s}  {total_size / (1024 * 1024 * 1024):>10.2f} GB"
    )
    log.info("")

    # Connect to databases
    try:
        graph_conn = _get_conn(GRAPH_DB_DSN)
        log.info("  ✓ Connected to Graph DB (PostgreSQL :5432)")
    except Exception as e:
        log.error(f"  ✗ Cannot connect to Graph DB: {e}")
        sys.exit(1)

    metrics_conn = None
    try:
        metrics_conn = _get_conn(METRICS_DB_DSN)
        log.info("  ✓ Connected to Metrics DB (TimescaleDB :5433)")
    except Exception as e:
        log.warning(f"  ⚠ Cannot connect to Metrics DB: {e}")
        log.warning("    Step 12 (KPI sample) will be skipped")

    log.info("")

    # Clean mode
    if args.clean and not args.dry_run:
        log.warning("⚠ CLEAN MODE — Deleting all Telco2 data...")
        confirm = input(f"  Type '{TENANT_ID}' to confirm deletion: ")
        if confirm.strip() != TENANT_ID:
            log.info("  Aborted.")
            sys.exit(0)

        with graph_conn.cursor() as cur:
            # Delete in reverse FK order
            tables_to_clean = [
                "scenario_kpi_overrides",
                "scenario_manifest",
                "telco_events_alarms",
                "neighbour_relations",
                "vendor_naming_map",
                "divergence_manifest",
                "gt_entity_relationships",
                "gt_network_entities",
                "bss_billing_accounts",  # FK → customers
                "kpi_samples",  # FK → network_entities
                "entity_relationships",  # FK → network_entities
                "topology_relationships",
                "customers",
                "network_entities",
                "kpi_dataset_registry",
            ]
            for tbl in tables_to_clean:
                try:
                    cur.execute(
                        f'DELETE FROM "{tbl}" WHERE tenant_id = %s', (TENANT_ID,)
                    )
                    deleted = cur.rowcount
                    if deleted > 0:
                        log.info(f"    Deleted {deleted:,} rows from {tbl}")
                except Exception as e:
                    log.debug(f"    {tbl}: {e}")
                    graph_conn.rollback()

            # Tenant record
            cur.execute("DELETE FROM tenants WHERE id = %s", (TENANT_ID,))
            graph_conn.commit()

        # Clean metrics DB
        if metrics_conn:
            with metrics_conn.cursor() as cur:
                try:
                    cur.execute(
                        "DELETE FROM kpi_metrics WHERE tenant_id = %s", (TENANT_ID,)
                    )
                    deleted = cur.rowcount
                    if deleted > 0:
                        log.info(
                            f"    Deleted {deleted:,} rows from kpi_metrics (TimescaleDB)"
                        )
                    metrics_conn.commit()
                except Exception as e:
                    log.debug(f"    kpi_metrics: {e}")
                    metrics_conn.rollback()

        # Also delete service plans (no tenant_id column, but they were created by us)
        # We'll leave them as they don't conflict

        log.info("  ✓ Clean complete\n")

    # Execute steps
    overall_t0 = _timer()

    try:
        if args.step is not None:
            # Single step mode
            if args.step == 12:
                if metrics_conn:
                    step_12_load_kpi_sample(
                        metrics_conn,
                        graph_conn,
                        dry_run=args.dry_run,
                        sample_hours=args.kpi_sample_hours or 24,
                    )
                else:
                    log.warning("  ⚠ Metrics DB not available, cannot run step 12")
            elif args.step == 0:
                step_0_create_tenant(graph_conn, dry_run=args.dry_run)
            elif args.step in STEPS:
                _, fn = STEPS[args.step]
                if fn:
                    fn(graph_conn, dry_run=args.dry_run)
            else:
                log.error(f"Unknown step: {args.step}")
                sys.exit(1)
        else:
            # Full pipeline
            step_0_create_tenant(graph_conn, dry_run=args.dry_run)
            step_1_load_network_entities(graph_conn, dry_run=args.dry_run)
            step_2_load_entity_relationships(graph_conn, dry_run=args.dry_run)
            step_3_load_topology_relationships(graph_conn, dry_run=args.dry_run)
            step_4_load_customers_bss(graph_conn, dry_run=args.dry_run)
            step_5_load_ground_truth(graph_conn, dry_run=args.dry_run)
            step_6_load_divergence_manifest(graph_conn, dry_run=args.dry_run)
            step_7_load_scenarios(graph_conn, dry_run=args.dry_run)
            step_8_load_events_alarms(graph_conn, dry_run=args.dry_run)
            step_9_load_neighbour_relations(graph_conn, dry_run=args.dry_run)
            step_10_load_vendor_naming(graph_conn, dry_run=args.dry_run)
            step_11_register_kpi_datasets(graph_conn, dry_run=args.dry_run)

            # Step 12: Optional KPI sample
            if args.kpi_sample_hours > 0 and metrics_conn:
                step_12_load_kpi_sample(
                    metrics_conn,
                    graph_conn,
                    dry_run=args.dry_run,
                    sample_hours=args.kpi_sample_hours,
                )
            elif not args.skip_kpi_sample and args.kpi_sample_hours == 0:
                log.info(
                    "\n  ℹ Step 12 skipped (KPI sample). Use --kpi-sample-hours N to load "
                    "N hours of radio KPIs into TimescaleDB for anomaly detection."
                )

    except KeyboardInterrupt:
        log.warning("\n  ⚠ Interrupted by user")
        graph_conn.rollback()
        if metrics_conn:
            metrics_conn.rollback()
    except Exception as e:
        log.error(f"\n  ✗ Fatal error: {e}", exc_info=True)
        graph_conn.rollback()
        if metrics_conn:
            metrics_conn.rollback()
        sys.exit(1)

    # Summary
    if not args.dry_run and args.step is None:
        print_summary(graph_conn, metrics_conn or graph_conn)

    log.info(f"\n  Total elapsed: {_elapsed(overall_t0)}")
    log.info("  Done.")

    # Cleanup
    graph_conn.close()
    if metrics_conn:
        metrics_conn.close()


if __name__ == "__main__":
    main()
