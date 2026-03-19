#!/usr/bin/env python3
"""Generic Tenant Data Loader

This is a generic replacement for the Telco2-specific loader.

It is designed to be used for any tenant that has a folder of Parquet
artifacts (CMDB + KPI + scenario/abeyance memory artifacts).

Key goals:
- Keep `load_telco2_tenant.py` untouched (checkpoint state).
- Allow multiple tenants via `--tenant-id` / `--tenant-name`.
- Keep the "ground truth" tables out of the operational load by default.
- Load the new Abeyance Memory Parquet artifacts when present.

Usage:
  ./venv/bin/python -m backend.app.scripts.load_tenant \
    --tenant-id six-telecom-01 \
    --tenant-name "Six Telecom" \
    --output-dir "/path/to/tenant/output" \
    --load-abeyance-memory

Alternatively, omit --output-dir and use --data-root to point at the base data directory.
When --data-root points at the folder containing parquet artifacts (e.g. /home/ubuntu/Pedkai-data/output), it will be used as-is.

For a full run, use:
  ./venv/bin/python -m backend.app.scripts.load_tenant --tenant-id <id> --output-dir <dir>

This script retains the same data ordering as the original Telco2 loader,
but adds optional gating for evaluation / ground-truth tables.
"""

from __future__ import annotations

import argparse
import gc
import json
import logging
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import psycopg2
import psycopg2.extras
import pyarrow.parquet as pq
from dotenv import load_dotenv

# Load environment from .env (cloud deployment) so we pick up DATABASE_URL / GRAPH_DB_DSN, etc.
load_dotenv()


def _sqlalchemy_url_to_psycopg2_dsn(url: str) -> str:
    """Convert a SQLAlchemy URL (postgresql+asyncpg://...) to a psycopg2 DSN string."""
    parsed = urlparse(url)
    if parsed.scheme.startswith("postgres"):
        user = parsed.username or ""
        password = parsed.password or ""
        host = parsed.hostname or ""
        port = parsed.port or 5432
        dbname = (parsed.path or "").lstrip("/")
        return f"host={host} port={port} dbname={dbname} user={user} password={password}"
    return url

# ---------------------------------------------------------------------------
# Configuration defaults (can be overridden via CLI args)
# ---------------------------------------------------------------------------

_DEFAULT_DATA_STORE_ROOT = os.environ.get(
    "PEDKAI_DATA_STORE_ROOT", "/Volumes/Projects/Pedkai Data Store"
)

# Database connection strings (sync, for psycopg2 COPY performance)
# Read from env vars if available, fall back to localhost defaults for local dev
# In cloud deployments we prefer DATABASE_URL / METRICS_DATABASE_URL and/or
# GRAPH_DB_DSN / METRICS_DB_DSN from .env.
GRAPH_DB_DSN = os.environ.get("GRAPH_DB_DSN")
if not GRAPH_DB_DSN:
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        GRAPH_DB_DSN = _sqlalchemy_url_to_psycopg2_dsn(database_url)

METRICS_DB_DSN = os.environ.get("METRICS_DB_DSN")
if not METRICS_DB_DSN:
    metrics_url = os.environ.get("METRICS_DATABASE_URL")
    if metrics_url:
        METRICS_DB_DSN = _sqlalchemy_url_to_psycopg2_dsn(metrics_url)

# Fall back to local defaults when env vars are missing
if not GRAPH_DB_DSN:
    GRAPH_DB_DSN = "host=localhost port=5432 dbname=pedkai user=postgres password=postgres"
if not METRICS_DB_DSN:
    METRICS_DB_DSN = "host=localhost port=5433 dbname=pedkai_metrics user=postgres password=postgres"

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
log = logging.getLogger("tenant_loader")


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


def load_parquet_to_table(
    conn,
    filepath: Path,
    table: str,
    tenant_id: str,
    key_column: str = "id",
    enforce_tenant: bool = True,
    conflict_on: str = "id",
) -> int:
    """Load a Parquet file into a Postgres table.

    Inserts all columns present in the Parquet file (plus tenant_id if
    required). Uses `ON CONFLICT` to avoid duplicates.
    """

    if not _ensure_file(filepath):
        return 0

    try:
        import pandas as pd
    except ImportError:
        log.error("pandas is required to load Parquet files. Install it via pip.")
        return 0

    df = pd.read_parquet(filepath)
    if df.empty:
        log.info(f"  ⊘ {filepath.name} has no rows, skipping")
        return 0

    if enforce_tenant:
        if "tenant_id" not in df.columns:
            df["tenant_id"] = tenant_id
        else:
            # Force tenant isolation
            df["tenant_id"] = tenant_id

    # Ensure there is an id column for conflict handling
    if key_column not in df.columns:
        df[key_column] = [str(uuid.uuid4()) for _ in range(len(df))]

    cols = [c for c in df.columns if df[c].dtype != "object" or not df[c].isna().all()]

    values = df.to_dict(orient="records")
    if not values:
        return 0

    col_list = ", ".join([f'"{c}"' for c in cols])
    placeholder = ", ".join(["%s"] * len(cols))
    insert_sql = (
        f"INSERT INTO {table} ({col_list}) VALUES ({placeholder}) "
        f"ON CONFLICT ({conflict_on}) DO NOTHING"
    )

    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            insert_sql,
            [[row.get(c) for c in cols] for row in values],
            template=None,
            page_size=1000,
        )
        conn.commit()

    return len(values)


# ---------------------------------------------------------------------------
# Tenant loader steps
# ---------------------------------------------------------------------------


def step_0_create_tenant(
    conn, tenant_id: str, tenant_display_name: str, dry_run: bool = False
) -> str:
    """Insert the tenant record if it doesn't exist."""
    log.info("━━━ Step 0: Create tenant ━━━")

    with conn.cursor() as cur:
        cur.execute("SELECT id, display_name FROM tenants WHERE id = %s", (tenant_id,))
        row = cur.fetchone()
        if row:
            log.info(f"  ✓ Tenant already exists: id={row[0]}, display_name={row[1]}")
            return row[0]

        if dry_run:
            log.info(
                f"  [DRY RUN] Would create tenant: id={tenant_id}, display_name={tenant_display_name}"
            )
            return tenant_id

        cur.execute(
            "INSERT INTO tenants (id, display_name, is_active, created_at) VALUES (%s, %s, %s, %s)",
            (tenant_id, tenant_display_name, True, datetime.now(timezone.utc)),
        )
        conn.commit()
        log.info(f"  ✓ Created tenant: id={tenant_id}")
        return tenant_id


def step_1_load_network_entities(conn, output_dir: Path, tenant_id: str, dry_run: bool = False):
    """Load cmdb_declared_entities.parquet → network_entities."""
    log.info("━━━ Step 1: Load network entities (CMDB declared) ━━━")
    filepath = output_dir / "cmdb_declared_entities.parquet"
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

    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM network_entities WHERE tenant_id = %s", (tenant_id,)
        )
        existing = cur.fetchone()[0]
        if existing > 0:
            log.info(
                f"  ⚠ {existing:,} entities already exist for tenant {tenant_id}. Skipping. (Delete first to reload.)"
            )
            return

    t0 = _timer()
    pf = pq.ParquetFile(filepath)
    loaded = 0
    batch_num = 0

    FIRST_CLASS = {
        "entity_id",
        "tenant_id",
        "entity_type",
        "name",
        "external_id",
        "geo_lat",
        "geo_lon",
    }

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
                attrs = {}
                for col in ATTR_COLS:
                    if col in table:
                        val = table[col][i]
                        if val is not None:
                            attrs[col] = val

                row = (
                    entity_id,  # id (UUID)
                    tenant_id,  # tenant_id (force to ensure FK validation works)
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

    # Debugging aid: show the tenant IDs present in network_entities (to catch tenant mismatch)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT tenant_id, COUNT(*) FROM network_entities GROUP BY tenant_id ORDER BY COUNT(*) DESC LIMIT 5"
            )
            rows = cur.fetchall()
            if rows:
                ids = ", ".join([f"{r[0]}({r[1]})" for r in rows])
                log.info(f"  ✓ network_entities tenant_id sample: {ids}")
    except Exception:
        conn.rollback()


def step_2_load_entity_relationships(conn, output_dir: Path, tenant_id: str, dry_run: bool = False):
    """Load cmdb_declared_relationships.parquet → entity_relationships."""
    log.info("━━━ Step 2: Load entity relationships (CMDB declared) ━━━")
    filepath = output_dir / "cmdb_declared_relationships.parquet"
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
            (tenant_id,),
        )
        existing = cur.fetchone()[0]
        if existing > 0:
            log.info(
                f"  ⚠ {existing:,} relationships already exist for tenant {tenant_id}. Skipping."
            )
            return

    t0 = _timer()
    pf = pq.ParquetFile(filepath)
    loaded = 0
    skipped = 0
    batch_num = 0

    log.info("    Pre-loading entity ID set for FK validation...")
    valid_entity_ids = set()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id::text FROM network_entities WHERE tenant_id = %s", (tenant_id,)
        )
        for row in cur:
            valid_entity_ids.add(row[0])

    if not valid_entity_ids:
        log.warning(
            "    ⚠ No entity IDs found for tenant '%s' — relationships will all skip unless tenant mismatch exists",
            tenant_id,
        )
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT tenant_id, COUNT(*) FROM network_entities GROUP BY tenant_id ORDER BY COUNT(*) DESC LIMIT 5"
                )
                rows = cur.fetchall()
                if rows:
                    ids = ", ".join([f"{r[0]}({r[1]})" for r in rows])
                    log.warning(f"    ✓ network_entities tenant_id sample: {ids}")
        except Exception:
            conn.rollback()

    log.info(f"    {len(valid_entity_ids):,} valid entity IDs loaded")

    insert_sql = """
        INSERT INTO entity_relationships
            (id, tenant_id, source_entity_id, source_entity_type,
             target_entity_id, target_entity_type, relationship_type,
             weight, attributes, created_at)
        VALUES %s
        ON CONFLICT (id) DO NOTHING
    """

    with conn.cursor() as cur:
        for batch in pf.iter_batches(batch_size=BATCH_RELATIONSHIPS):
            batch_num += 1
            table = batch.to_pydict()
            n = len(table["relationship_id"])
            rows = []

            for i in range(n):
                from_id = table["from_entity_id"][i]
                to_id = table["to_entity_id"][i]

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
                    table["relationship_id"][i],
                    tenant_id,
                    from_id,
                    table["from_entity_type"][i],
                    to_id,
                    table["to_entity_type"][i],
                    table["relationship_type"][i],
                    None,
                    json.dumps(attrs),
                    datetime.now(timezone.utc),
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


def step_3_load_topology_relationships(
    conn, output_dir: Path, tenant_id: str, dry_run: bool = False
):
    """Load CMDB relationship file into topology_relationships (graph API)."""
    log.info("━━━ Step 3: Load topology relationships (graph API) ━━━")
    filepath = output_dir / "cmdb_declared_relationships.parquet"
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
            (tenant_id,),
        )
        existing = cur.fetchone()[0]
        if existing > 0:
            log.info(
                f"  ⚠ {existing:,} topology relationships already exist for tenant {tenant_id}. Skipping."
            )
            return

    t0 = _timer()
    pf = pq.ParquetFile(filepath)
    loaded = 0
    batch_num = 0

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


def step_4_load_customers_bss(
    conn, output_dir: Path, tenant_id: str, dry_run: bool = False
):
    """Load customers_bss.parquet → customers + bss_service_plans + bss_billing_accounts."""
    log.info("━━━ Step 4: Load customers & BSS ━━━")
    filepath = output_dir / "customers_bss.parquet"
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
        cur.execute("SELECT COUNT(*) FROM customers WHERE tenant_id = %s", (tenant_id,))
        existing = cur.fetchone()[0]
        if existing > 0:
            log.info(
                f"  ⚠ {existing:,} customers already exist for tenant {tenant_id}. Skipping."
            )
            return

    t0 = _timer()

    log.info("  Phase A: Loading unique service plans...")
    pf = pq.ParquetFile(filepath)
    plan_map: dict[str, str] = {}

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

    with conn.cursor() as cur:
        for pname, puuid in plan_map.items():
            pass

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

    with conn.cursor() as cur:
        cur.execute("SELECT name, id FROM bss_service_plans")
        plan_map = {row[0]: str(row[1]) for row in cur.fetchall()}

    log.info("  Phase B: Loading customers + billing accounts...")
    pf = pq.ParquetFile(filepath)
    loaded_customers = 0
    loaded_billing = 0
    skipped_dupes = 0
    batch_num = 0
    seen_external_ids: set[str] = set()

    customer_insert_sql = """
        INSERT INTO customers (id, external_id, name, churn_risk_score,
                               associated_site_id, consent_proactive_comms,
                               tenant_id, created_at)
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

    inserted_customer_ids: set[str] = set()

    with conn.cursor() as cur:
        for batch in pf.iter_batches(batch_size=BATCH_CUSTOMERS):
            batch_num += 1
            t = batch.to_pydict()
            n = len(t["customer_id"])

            customer_rows = []
            pending_billing: list[tuple] = []

            for i in range(n):
                cust_id = t["customer_id"][i]
                ext_id = t.get("external_id", [None] * n)[i]
                if not ext_id:
                    ext_id = f"CUST-{cust_id[:8]}"

                if ext_id in seen_external_ids:
                    skipped_dupes += 1
                    continue
                seen_external_ids.add(ext_id)

                name = t.get("name", [None] * n)[i]
                churn = t.get("churn_risk_score", [None] * n)[i]
                site_id = t.get("associated_site_id", [None] * n)[i]
                consent = t.get("consent_proactive_comms", [None] * n)[i]
                if consent is None:
                    consent = False

                customer_rows.append(
                    (
                        cust_id,
                        ext_id,
                        name,
                        churn,
                        site_id,
                        consent,
                        tenant_id,
                        datetime.now(timezone.utc),
                    )
                )
                inserted_customer_ids.add(cust_id)

                plan_name = t.get("service_plan_name", [None] * n)[i]
                plan_id = plan_map.get(plan_name) if plan_name else None
                if plan_id:
                    acct_status = t.get("account_status", [None] * n)[i] or "ACTIVE"
                    avg_rev = t.get("avg_monthly_revenue", [None] * n)[i]
                    contract_end = t.get("contract_end_date", [None] * n)[i]

                    pending_billing.append(
                        (
                            str(uuid.uuid4()),
                            cust_id,
                            plan_id,
                            acct_status,
                            avg_rev,
                            contract_end,
                            None,
                        )
                    )

            if customer_rows:
                try:
                    psycopg2.extras.execute_values(
                        cur,
                        customer_insert_sql,
                        customer_rows,
                        template="(%s::uuid, %s, %s, %s, %s, %s, %s, %s)",
                        page_size=BATCH_CUSTOMERS,
                    )
                    loaded_customers += len(customer_rows)
                except psycopg2.errors.NotNullViolation as e:
                    # Provide a helpful message about what column is failing
                    col = getattr(e, 'diag', None) and getattr(e.diag, 'column_name', None)
                    if col:
                        log.error(
                            f"  ✗ Not-null constraint failed on column '{col}' in customers table. "
                            "Check if the source Parquet file includes this field or add a default."
                        )
                    else:
                        log.error(
                            "  ✗ Not-null constraint failed when inserting customers. "
                            "Check the customers table schema and source Parquet fields."
                        )
                    raise

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


def step_8_load_events_alarms(
    conn, output_dir: Path, tenant_id: str, dry_run: bool = False
):
    """Load events_alarms.parquet → telco_events_alarms."""
    log.info("━━━ Step 8: Load events & alarms ━━━")
    filepath = output_dir / "events_alarms.parquet"
    if not _ensure_file(filepath):
        return

    total_rows = _pq_row_count(filepath)
    log.info(f"  Source: {filepath.name} ({total_rows:,} rows)")

    if dry_run:
        log.info(f"  [DRY RUN] Would load {total_rows:,} events/alarms")
        return

    with conn.cursor() as cur:
        # If the events/alarms table doesn't exist in this deployment, skip gracefully.
        cur.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_name = %s LIMIT 1",
            ("telco_events_alarms",),
        )
        if cur.fetchone() is None:
            log.warning(
                "  ⚠ Table telco_events_alarms does not exist in this DB; skipping events load"
            )
            return

        cur.execute(
            "SELECT COUNT(*) FROM telco_events_alarms WHERE tenant_id = %s",
            (tenant_id,),
        )
        if cur.fetchone()[0] > 0:
            log.info(f"  ⚠ Events already loaded for {tenant_id}. Skipping.")
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


def step_9_load_neighbour_relations(
    conn, output_dir: Path, tenant_id: str, dry_run: bool = False
):
    """Load neighbour_relations.parquet → neighbour_relations."""
    log.info("━━━ Step 9: Load neighbour relations ━━━")
    filepath = output_dir / "neighbour_relations.parquet"
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
            (tenant_id,),
        )
        if cur.fetchone()[0] > 0:
            log.info(
                f"  ⚠ Neighbour relations already loaded for {tenant_id}. Skipping."
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


def step_10_load_vendor_naming(
    conn, output_dir: Path, tenant_id: str, dry_run: bool = False
):
    """Load vendor_naming_map.parquet → vendor_naming_map."""
    log.info("━━━ Step 10: Load vendor naming map ━━━")
    filepath = output_dir / "vendor_naming_map.parquet"
    if not _ensure_file(filepath):
        return

    total_rows = _pq_row_count(filepath)
    log.info(f"  Source: {filepath.name} ({total_rows:,} rows)")

    if dry_run:
        log.info(f"  [DRY RUN] Would load {total_rows:,} vendor naming entries")
        return

    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM vendor_naming_map WHERE tenant_id = %s", (tenant_id,)
        )
        if cur.fetchone()[0] > 0:
            log.info(f"  ⚠ Vendor naming already loaded for {tenant_id}. Skipping.")
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


def step_11_register_kpi_datasets(
    conn, output_dir: Path, tenant_id: str, dry_run: bool = False
):
    """Register KPI Parquet files as external datasets in kpi_dataset_registry."""
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
        filepath = output_dir / filename
        if not filepath.exists():
            log.info(f"  ⊘ {filename} — not found, skipping")
            continue

        pf = pq.ParquetFile(filepath)
        total_rows = pf.metadata.num_rows
        total_cols = pf.metadata.num_columns
        file_size = filepath.stat().st_size
        schema = pf.schema_arrow
        schema_info = {
            schema.names[j]: str(schema.field(j).type) for j in range(len(schema.names))
        }

        log.info(
            f"  {filename}: {total_rows:,} rows, {total_cols} cols, "
            f"{file_size / (1024 * 1024):.1f} MB → registered as '{dataset_name}'"
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
                    tenant_id,
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


def step_12_load_kpi_sample(
    metrics_conn,
    output_dir: Path,
    tenant_id: str,
    dry_run: bool = False,
    sample_hours: int = 24,
):
    """Load a small KPI sample into TimescaleDB for anomaly / sleeping-cell detection."""
    log.info(f"━━━ Step 12: Load KPI sample into TimescaleDB ({sample_hours}h) ━━━")
    filepath = output_dir / "kpi_metrics_wide.parquet"
    if not _ensure_file(filepath):
        return

    if dry_run:
        pf = pq.ParquetFile(filepath)
        total_rows = pf.metadata.num_rows
        estimated_sample = min(total_rows, 66_000 * sample_hours)
        kpi_cols = 35
        log.info(
            f"  [DRY RUN] Would load ~{estimated_sample:,} wide rows "
            f"× {kpi_cols} KPIs = ~{estimated_sample * kpi_cols:,} long-format rows "
            f"into TimescaleDB kpi_metrics"
        )
        return

    with metrics_conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM kpi_metrics WHERE tenant_id = %s", (tenant_id,)
        )
        existing = cur.fetchone()[0]
        if existing > 0:
            log.info(
                f"  ⚠ {existing:,} KPI rows already exist for {tenant_id} in TimescaleDB. Skipping."
            )
            return

    t0 = _timer()

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

    from datetime import timedelta

    epoch = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    cutoff = epoch + timedelta(hours=sample_hours)

    loaded = 0
    wide_rows_processed = 0
    batch_num = 0
    _prev_wide = 0

    insert_sql = """
        INSERT INTO kpi_metrics (timestamp, tenant_id, entity_id, kpi_name, metric_value, metadata)
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
                if hasattr(ts, "timestamp"):
                    if ts > cutoff:
                        continue
                else:
                    continue

                cell_id = t["cell_id"][i]
                tenant = t["tenant_id"][i]
                wide_rows_processed += 1

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

            if wide_rows_processed > 0 and n > 0 and loaded > 0:
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


def print_summary(conn, metrics_conn, tenant_id: str):
    """Print a summary of loaded data."""
    log.info("\n" + "=" * 70)
    log.info("  LOAD SUMMARY — Tenant: %s", tenant_id)
    log.info("=" * 70)

    tables = [
        ("network_entities", "Graph DB"),
        ("entity_relationships", "Graph DB"),
        ("topology_relationships", "Graph DB"),
        ("customers", "Graph DB"),
        ("bss_service_plans", "Graph DB"),
        ("bss_billing_accounts", "Graph DB"),
        ("telco_events_alarms", "Graph DB"),
        ("neighbour_relations", "Graph DB"),
        ("vendor_naming_map", "Graph DB"),
        ("kpi_dataset_registry", "Graph DB"),
        ("abeyance_fragment", "Graph DB"),
        ("snap_decision_record", "Graph DB"),
        ("surprise_event", "Graph DB"),
        ("disconfirmation_events", "Graph DB"),
        ("bridge_discovery", "Graph DB"),
        ("causal_evidence_pair", "Graph DB"),
        ("entity_sequence_log", "Graph DB"),
    ]

    for table_name, db_label in tables:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM information_schema.columns "
                    "WHERE table_name = %s AND column_name = 'tenant_id'",
                    (table_name,),
                )
                has_tenant = cur.fetchone()[0] > 0

                if has_tenant:
                    cur.execute(
                        f'SELECT COUNT(*) FROM "{table_name}" WHERE tenant_id = %s',
                        (tenant_id,),
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

    try:
        with metrics_conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM kpi_metrics WHERE tenant_id = %s", (tenant_id,)
            )
            count = cur.fetchone()[0]
            log.info(f"  {'kpi_metrics':40s} [{'Metrics DB':10s}]: {count:>12,} rows")
    except Exception as e:
        log.info(f"  {'kpi_metrics':40s} [{'Metrics DB':10s}]: (error: {e})")


def main():
    parser = argparse.ArgumentParser(
        description="Generic tenant loader for Pedkai (supports abeyance memory artifacts)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument("--tenant-id", required=True, help="Tenant ID (slug)")
    parser.add_argument(
        "--tenant-name",
        default=None,
        help="Tenant display name (default: same as tenant-id)",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Path to the folder containing the Parquet artifacts (output/*.parquet).",
    )
    parser.add_argument(
        "--data-root",
        default=_DEFAULT_DATA_STORE_ROOT,
        help=(
            "Base data root (used to build default output-dir when --output-dir is not provided). "
            "If this path already contains the parquet artifacts (e.g. /path/to/output), it will be used directly."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate files without altering the database.",
    )
    parser.add_argument(
        "--step",
        type=int,
        default=None,
        help="Run only a specific step (0-13).",
    )
    parser.add_argument(
        "--load-ground-truth",
        action="store_true",
        help="Load gt_*.parquet ground-truth tables (evaluation only).",
    )
    parser.add_argument(
        "--load-divergence-manifest",
        action="store_true",
        help="Load divergence_manifest.parquet for offline scoring (evaluation only).",
    )
    parser.add_argument(
        "--load-scenarios",
        action="store_true",
        help="Load scenario_manifest / scenario_kpi_overrides (optional).",
    )
    parser.add_argument(
        "--load-abeyance-memory",
        action="store_true",
        help="Load abeyance memory parquet artifacts (new for Six Telecom).",
    )
    parser.add_argument(
        "--abeyance-dir",
        default="abeyance_memory",
        help="Subdirectory under --output-dir where abeyance memory parquet files are stored.",
    )
    parser.add_argument(
        "--kpi-sample-hours",
        type=int,
        default=0,
        help="Hours of KPI data to load into TimescaleDB (0 = skip).",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Delete all existing data for this tenant before loading (DANGER).",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging.",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    tenant_id = args.tenant_id
    tenant_name = args.tenant_name or tenant_id

    if args.output_dir:
        output_dir = Path(args.output_dir).expanduser().resolve()
    else:
        data_root = Path(args.data_root).expanduser().resolve()
        # In some deployments the data store root already points at the output folder
        # (e.g., "/home/ubuntu/Pedkai-data/output"). In that case, use it as-is.
        expected_files = [
            "cmdb_declared_entities.parquet",
            "customers_bss.parquet",
            "kpi_metrics_wide.parquet",
        ]
        if data_root.exists() and any((data_root / f).exists() for f in expected_files):
            output_dir = data_root
        else:
            output_dir = data_root / tenant_id / "output"

    log.info("╔════════════════════════════════════════════════════════════════╗")
    log.info("║   Pedkai — Generic Tenant Data Loader (Six Telecom / future)     ║")
    log.info("╚════════════════════════════════════════════════════════════════╝")
    log.info(f"  Tenant ID:    {tenant_id}")
    log.info(f"  Tenant name:  {tenant_name}")
    log.info(f"  Output dir:   {output_dir}")
    log.info(f"  Dry run:      {args.dry_run}")
    if args.step is not None:
        log.info(f"  Single step:  {args.step}")
    log.info("")

    if not output_dir.exists():
        log.error(f"Output directory not found: {output_dir}")
        sys.exit(1)

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
        log.warning("    KPI sample step will be skipped")

    log.info("")

    # Clean mode
    if args.clean and not args.dry_run:
        log.warning("⚠ CLEAN MODE — Deleting all data for this tenant...")
        confirm = input(f"  Type '{tenant_id}' to confirm deletion: ")
        if confirm.strip() != tenant_id:
            log.info("  Aborted.")
            sys.exit(0)

        with graph_conn.cursor() as cur:
            tables_to_clean = [
                "scenario_kpi_overrides",
                "scenario_manifest",
                "telco_events_alarms",
                "neighbour_relations",
                "vendor_naming_map",
                "divergence_manifest",
                "gt_entity_relationships",
                "gt_network_entities",
                "bss_billing_accounts",
                "entity_relationships",
                "topology_relationships",
                "customers",
                "network_entities",
                "kpi_dataset_registry",
                "abeyance_fragment",
                "snap_decision_record",
                "surprise_event",
                "disconfirmation_events",
                "bridge_discovery",
                "causal_evidence_pair",
                "entity_sequence_log",
            ]
            for tbl in tables_to_clean:
                try:
                    cur.execute(f'DELETE FROM "{tbl}" WHERE tenant_id = %s', (tenant_id,))
                    deleted = cur.rowcount
                    if deleted > 0:
                        log.info(f"    Deleted {deleted:,} rows from {tbl}")
                except Exception:
                    graph_conn.rollback()
            cur.execute("DELETE FROM tenants WHERE id = %s", (tenant_id,))
            graph_conn.commit()

        if metrics_conn:
            with metrics_conn.cursor() as cur:
                try:
                    cur.execute(
                        "DELETE FROM kpi_metrics WHERE tenant_id = %s", (tenant_id,)
                    )
                    deleted = cur.rowcount
                    if deleted > 0:
                        log.info(
                            f"    Deleted {deleted:,} rows from kpi_metrics (TimescaleDB)"
                        )
                    metrics_conn.commit()
                except Exception:
                    metrics_conn.rollback()

        log.info("  ✓ Clean complete\n")

    # ---------- Execute steps ----------
    overall_t0 = _timer()

    try:
        if args.step is not None:
            # Single step mode
            if args.step == 0:
                step_0_create_tenant(
                    graph_conn,
                    tenant_id=tenant_id,
                    tenant_display_name=tenant_name,
                    dry_run=args.dry_run,
                )
            elif args.step == 1:
                step_1_load_network_entities(graph_conn, output_dir, tenant_id, args.dry_run)
            elif args.step == 2:
                step_2_load_entity_relationships(
                    graph_conn, output_dir, tenant_id, args.dry_run
                )
            else:
                log.error(f"Unknown step: {args.step}")
                sys.exit(1)
        else:
            step_0_create_tenant(
                graph_conn,
                tenant_id=tenant_id,
                tenant_display_name=tenant_name,
                dry_run=args.dry_run,
            )
            step_1_load_network_entities(graph_conn, output_dir, tenant_id, args.dry_run)
            step_2_load_entity_relationships(
                graph_conn, output_dir, tenant_id, args.dry_run
            )
            step_3_load_topology_relationships(
                graph_conn, output_dir, tenant_id, args.dry_run
            )
            step_4_load_customers_bss(
                graph_conn, output_dir, tenant_id, args.dry_run
            )
            step_8_load_events_alarms(
                graph_conn, output_dir, tenant_id, args.dry_run
            )
            step_9_load_neighbour_relations(
                graph_conn, output_dir, tenant_id, args.dry_run
            )
            step_10_load_vendor_naming(
                graph_conn, output_dir, tenant_id, args.dry_run
            )
            step_11_register_kpi_datasets(
                graph_conn, output_dir, tenant_id, args.dry_run
            )

            if args.load_abeyance_memory:
                log.info("\nLoading Abeyance Memory parquet artifacts...")
                _load_abeyance_memory(
                    graph_conn,
                    output_dir,
                    tenant_id,
                    abeyance_dir=args.abeyance_dir,
                    dry_run=args.dry_run,
                )

            if args.kpi_sample_hours > 0 and metrics_conn:
                log.info("\nLoading KPI sample into TimescaleDB...")
                step_12_load_kpi_sample(
                    metrics_conn,
                    output_dir,
                    tenant_id,
                    dry_run=args.dry_run,
                    sample_hours=args.kpi_sample_hours,
                )

            if not args.dry_run:
                print_summary(graph_conn, metrics_conn or graph_conn, tenant_id)

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

    log.info(f"\n  Total elapsed: {_elapsed(overall_t0)}")
    log.info("  Done.")

    graph_conn.close()
    if metrics_conn:
        metrics_conn.close()


def _load_abeyance_fragments(conn, filepath: Path, tenant_id: str) -> int:
    """Load abeyance_fragments.parquet → abeyance_fragment.

    Parquet PK: fragment_id → DB PK: id
    New columns: entity_count, snap_partner_id
    Uses (tenant_id, dedup_key) unique constraint for conflict resolution.
    """
    import pandas as pd
    df = pd.read_parquet(filepath)
    if df.empty:
        return 0

    df["tenant_id"] = tenant_id

    # Rename Parquet PK to DB PK
    if "fragment_id" in df.columns:
        df = df.rename(columns={"fragment_id": "id"})

    # Ensure new columns exist (migration 015 adds them; parquet has them)
    for col, default in [("entity_count", 0), ("snap_partner_id", None)]:
        if col not in df.columns:
            df[col] = default

    # Map the columns that exist in both parquet and DB
    keep_cols = [
        "id", "tenant_id", "source_type", "entity_id", "entity_domain",
        "snap_status", "failure_mode_profile", "mask_semantic", "mask_topological",
        "mask_operational", "current_decay_score", "event_timestamp", "dedup_key",
        "entity_count", "extracted_entities", "polarity", "max_lifetime_days",
        "snap_partner_id",
    ]
    df = df[[c for c in keep_cols if c in df.columns]]

    insert_cols = list(df.columns)
    col_list = ", ".join([f'"{c}"' for c in insert_cols])
    placeholder = ", ".join(["%s"] * len(insert_cols))
    sql = (
        f"INSERT INTO abeyance_fragment ({col_list}) VALUES %s "
        f"ON CONFLICT (tenant_id, dedup_key) DO NOTHING"
    )

    rows = [[row.get(c) for c in insert_cols] for row in df.to_dict(orient="records")]
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(cur, sql, rows, page_size=2000)
    conn.commit()
    return len(rows)


def _load_snap_decision_records(conn, filepath: Path, tenant_id: str) -> int:
    """Load snap_decision_records.parquet → snap_decision_record.

    Parquet PK: record_id → DB PK: id
    """
    import pandas as pd
    df = pd.read_parquet(filepath)
    if df.empty:
        return 0

    df["tenant_id"] = tenant_id

    if "record_id" in df.columns:
        df = df.rename(columns={"record_id": "id"})

    keep_cols = [
        "id", "tenant_id", "new_fragment_id", "candidate_fragment_id",
        "failure_mode_profile", "score_semantic", "score_topological",
        "score_temporal", "score_operational", "score_entity_overlap",
        "masks_active", "weights_used", "weights_base",
        "raw_composite", "temporal_modifier", "final_score",
        "threshold_applied", "decision", "multiple_comparisons_k", "evaluated_at",
    ]
    df = df[[c for c in keep_cols if c in df.columns]]

    insert_cols = list(df.columns)
    col_list = ", ".join([f'"{c}"' for c in insert_cols])
    placeholder = ", ".join(["%s"] * len(insert_cols))
    sql = (
        f"INSERT INTO snap_decision_record ({col_list}) VALUES %s "
        f"ON CONFLICT (id) DO NOTHING"
    )

    rows = [[row.get(c) for c in insert_cols] for row in df.to_dict(orient="records")]
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(cur, sql, rows, page_size=2000)
    conn.commit()
    return len(rows)


def _load_disconfirmation_events(conn, filepath: Path, tenant_id: str) -> int:
    """Load disconfirmation_events.parquet → disconfirmation_events + disconfirmation_fragments.

    The parquet is denormalised: one row per (event, fragment) pair with
    pre/post decay scores. We split this into:
      - One parent row in disconfirmation_events (deduplicated by event_id)
      - One child row in disconfirmation_fragments per parquet row

    Parquet PK: event_id → DB PK: id (in disconfirmation_events)
    """
    import pandas as pd
    df = pd.read_parquet(filepath)
    if df.empty:
        return 0

    df["tenant_id"] = tenant_id

    if "event_id" in df.columns:
        df = df.rename(columns={"event_id": "id"})

    # ── Parent rows (disconfirmation_events) ──────────────────────────
    parent_cols = ["id", "tenant_id", "pathway", "reason", "acceleration_factor", "created_at"]
    parent_df = df[[c for c in parent_cols if c in df.columns]].drop_duplicates(subset=["id"])

    # DB requires initiated_by NOT NULL — use synthetic default (migration 015 adds server default,
    # but we also set it explicitly here for clarity)
    parent_df = parent_df.copy()
    parent_df["initiated_by"] = "SYNTHETIC_SEED"
    parent_df["fragment_count"] = 0  # will be back-filled after fragment insert

    p_cols = list(parent_df.columns)
    p_col_list = ", ".join([f'"{c}"' for c in p_cols])
    p_placeholder = ", ".join(["%s"] * len(p_cols))
    parent_sql = (
        f"INSERT INTO disconfirmation_events ({p_col_list}) VALUES %s "
        f"ON CONFLICT (id) DO NOTHING"
    )

    parent_rows = [[row.get(c) for c in p_cols] for row in parent_df.to_dict(orient="records")]
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(cur, parent_sql, parent_rows, page_size=1000)
    conn.commit()

    # ── Child rows (disconfirmation_fragments) ────────────────────────
    frag_cols_needed = ["id", "fragment_id", "pre_decay_score", "post_decay_score"]
    if not all(c in df.columns for c in ["fragment_id", "pre_decay_score", "post_decay_score"]):
        log.warning("  ⚠ disconfirmation_events.parquet missing fragment score columns; skipping fragments")
        return len(parent_rows)

    frag_df = df[["id", "fragment_id", "pre_decay_score", "post_decay_score"]].copy()
    frag_df = frag_df.rename(columns={"id": "disconfirmation_event_id"})
    frag_df["id"] = [str(uuid.uuid4()) for _ in range(len(frag_df))]

    f_cols = list(frag_df.columns)
    f_col_list = ", ".join([f'"{c}"' for c in f_cols])
    f_placeholder = ", ".join(["%s"] * len(f_cols))
    frag_sql = (
        f"INSERT INTO disconfirmation_fragments ({f_col_list}) VALUES %s "
        f"ON CONFLICT (id) DO NOTHING"
    )

    frag_rows = [[row.get(c) for c in f_cols] for row in frag_df.to_dict(orient="records")]
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(cur, frag_sql, frag_rows, page_size=2000)

    # Update fragment_count on parent rows
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE disconfirmation_events de
            SET fragment_count = sub.cnt
            FROM (
                SELECT disconfirmation_event_id, COUNT(*) AS cnt
                FROM disconfirmation_fragments
                GROUP BY disconfirmation_event_id
            ) sub
            WHERE de.id = sub.disconfirmation_event_id
              AND de.tenant_id = %s
        """, (tenant_id,))
    conn.commit()
    return len(parent_rows) + len(frag_rows)


def _load_bridge_candidates(conn, filepath: Path, tenant_id: str) -> int:
    """Load bridge_candidates.parquet → bridge_discovery.

    Parquet PK: node_id — maps to fragment_id (not DB PK id)
    New DB columns: entity_domains_spanned JSONB, sub_component_size INTEGER
    Unique constraint: (tenant_id, component_fingerprint)
    """
    import pandas as pd
    df = pd.read_parquet(filepath)
    if df.empty:
        return 0

    df["tenant_id"] = tenant_id
    df["id"] = [str(uuid.uuid4()) for _ in range(len(df))]

    # node_id in parquet = fragment_id in DB
    if "node_id" in df.columns:
        df = df.rename(columns={"node_id": "fragment_id"})

    # entity_domains_spanned: parquet stores as a comma-separated string,
    # convert to JSON array
    if "entity_domains_spanned" in df.columns:
        df["entity_domains_spanned"] = df["entity_domains_spanned"].apply(
            lambda v: json.dumps(v.split(",") if isinstance(v, str) else []) if v is not None else None
        )

    keep_cols = [
        "id", "tenant_id", "fragment_id", "betweenness_centrality",
        "domain_span", "severity", "component_fingerprint",
        "entity_domains_spanned", "sub_component_size", "created_at",
    ]
    df = df[[c for c in keep_cols if c in df.columns]]

    insert_cols = list(df.columns)
    col_list = ", ".join([f'"{c}"' for c in insert_cols])
    placeholder = ", ".join(["%s"] * len(insert_cols))
    sql = (
        f"INSERT INTO bridge_discovery ({col_list}) VALUES %s "
        f"ON CONFLICT (tenant_id, component_fingerprint) DO NOTHING"
    )

    rows = [[row.get(c) for c in insert_cols] for row in df.to_dict(orient="records")]
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(cur, sql, rows, page_size=2000)
    conn.commit()
    return len(rows)


def _load_causal_pairs(conn, filepath: Path, tenant_id: str) -> int:
    """Load causal_pairs.parquet → causal_evidence_pair.

    Parquet PK: pair_id → DB PK: id
    a_precedes_b (bool) → direction VARCHAR ('A_TO_B' / 'B_TO_A')
    new: direction_category VARCHAR
    Note: causal_candidate_id FK — inserts a placeholder causal_candidate
    row when needed to satisfy the FK (if FK enforcement is active).
    """
    import pandas as pd
    df = pd.read_parquet(filepath)
    if df.empty:
        return 0

    df["tenant_id"] = tenant_id

    if "pair_id" in df.columns:
        df = df.rename(columns={"pair_id": "id"})

    # Translate boolean a_precedes_b → direction string
    if "a_precedes_b" in df.columns and "direction" not in df.columns:
        df["direction"] = df["a_precedes_b"].apply(
            lambda v: "A_TO_B" if v else "B_TO_A"
        )

    keep_cols = [
        "id", "causal_candidate_id", "fragment_a_id", "fragment_b_id",
        "time_delta_seconds", "direction", "direction_category",
    ]
    df = df[[c for c in keep_cols if c in df.columns]]

    # Ensure causal_candidate_id exists (parquet should have it)
    if "causal_candidate_id" not in df.columns:
        log.warning("  ⚠ causal_pairs.parquet missing causal_candidate_id; generating placeholder")
        placeholder_cand_id = str(uuid.uuid4())
        df["causal_candidate_id"] = placeholder_cand_id
        # Insert a placeholder causal_candidate to satisfy FK
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO causal_candidate
                    (id, tenant_id, entity_a_id, entity_b_id, direction,
                     directional_fraction, confidence, sample_count)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
            """, (
                placeholder_cand_id, tenant_id,
                "00000000-0000-0000-0000-000000000000",
                "00000000-0000-0000-0000-000000000000",
                "UNKNOWN", 0.0, 0.0, 0,
            ))
        conn.commit()

    insert_cols = list(df.columns)
    col_list = ", ".join([f'"{c}"' for c in insert_cols])
    placeholder = ", ".join(["%s"] * len(insert_cols))
    sql = (
        f"INSERT INTO causal_evidence_pair ({col_list}) VALUES %s "
        f"ON CONFLICT (id) DO NOTHING"
    )

    rows = [[row.get(c) for c in insert_cols] for row in df.to_dict(orient="records")]
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(cur, sql, rows, page_size=2000)
    conn.commit()
    return len(rows)


def _load_scenario_surprise_events(conn, filepath: Path, tenant_id: str) -> int:
    """Load scenario_surprise_events.parquet → surprise_event.

    Parquet PK: event_id → DB PK: id
    """
    import pandas as pd
    df = pd.read_parquet(filepath)
    if df.empty:
        return 0

    df["tenant_id"] = tenant_id

    if "event_id" in df.columns:
        df = df.rename(columns={"event_id": "id"})

    keep_cols = [
        "id", "tenant_id", "snap_decision_record_id", "failure_mode_profile",
        "surprise_value", "threshold_at_time", "escalation_type",
        "dimensions_contributing", "bin_index", "bin_probability", "created_at",
    ]
    df = df[[c for c in keep_cols if c in df.columns]]

    # dimensions_contributing may be a string in parquet (JSON-encoded) — keep as-is
    insert_cols = list(df.columns)
    col_list = ", ".join([f'"{c}"' for c in insert_cols])
    placeholder = ", ".join(["%s"] * len(insert_cols))
    sql = (
        f"INSERT INTO surprise_event ({col_list}) VALUES %s "
        f"ON CONFLICT (id) DO NOTHING"
    )

    rows = [[row.get(c) for c in insert_cols] for row in df.to_dict(orient="records")]
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(cur, sql, rows, page_size=2000)
    conn.commit()
    return len(rows)


def _load_temporal_sequences(conn, filepath: Path, tenant_id: str) -> int:
    """Load temporal_sequences.parquet → entity_sequence_log.

    Parquet PK: seq_id (UUID) — DISCARDED because entity_sequence_log uses
    BIGSERIAL as its PK. We let the DB auto-generate the serial ID.
    New DB columns: is_rare, transition_count_hint (added by migration 015).
    """
    import pandas as pd
    df = pd.read_parquet(filepath)
    if df.empty:
        return 0

    df["tenant_id"] = tenant_id

    # Drop the parquet UUID PK — entity_sequence_log uses BIGSERIAL
    if "seq_id" in df.columns:
        df = df.drop(columns=["seq_id"])

    keep_cols = [
        "tenant_id", "entity_id", "entity_domain", "from_state", "to_state",
        "fragment_id", "event_timestamp", "is_rare", "transition_count_hint",
    ]
    df = df[[c for c in keep_cols if c in df.columns]]

    insert_cols = list(df.columns)
    col_list = ", ".join([f'"{c}"' for c in insert_cols])
    placeholder = ", ".join(["%s"] * len(insert_cols))
    # entity_sequence_log has no natural unique constraint other than serial PK;
    sql = f"INSERT INTO entity_sequence_log ({col_list}) VALUES %s"

    rows = [[row.get(c) for c in insert_cols] for row in df.to_dict(orient="records")]
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(cur, sql, rows, page_size=5000)
    conn.commit()
    return len(rows)


def _load_abeyance_memory(
    conn,
    output_dir: Path,
    tenant_id: str,
    abeyance_dir: str = "abeyance_memory",
    dry_run: bool = False,
):
    """Load Abeyance Memory parquet artifacts using dedicated column-mapped loaders.

    Each of the 7 parquet files has a dedicated loader that handles:
      - PK column renaming (e.g. fragment_id → id)
      - Data type transformations (e.g. bool a_precedes_b → direction string)
      - Denormalisation splitting (disconfirmation_events → 2 DB tables)
      - Correct ON CONFLICT clauses aligned to each table's unique constraints
      - New DB columns added by migration 015 (entity_count, snap_partner_id, etc.)

    Files are expected in a subdirectory under output_dir (default: abeyance_memory/).
    """
    abeyance_path = Path(abeyance_dir)
    base_dir = abeyance_path if abeyance_path.is_absolute() else output_dir / abeyance_path

    if not base_dir.exists():
        log.info(f"  ⊘ Abeyance memory directory not found: {base_dir}")
        return

    dispatch = {
        "abeyance_fragments.parquet":       ("abeyance_fragment",       _load_abeyance_fragments),
        "snap_decision_records.parquet":    ("snap_decision_record",    _load_snap_decision_records),
        "disconfirmation_events.parquet":   ("disconfirmation_events",  _load_disconfirmation_events),
        "bridge_candidates.parquet":        ("bridge_discovery",        _load_bridge_candidates),
        "causal_pairs.parquet":             ("causal_evidence_pair",    _load_causal_pairs),
        "scenario_surprise_events.parquet": ("surprise_event",          _load_scenario_surprise_events),
        "temporal_sequences.parquet":       ("entity_sequence_log",     _load_temporal_sequences),
    }

    for fname, (table, loader_fn) in dispatch.items():
        filepath = base_dir / fname
        if not filepath.exists():
            log.info(f"  ⊘ {fname} not found in {base_dir}, skipping")
            continue

        total_rows = _pq_row_count(filepath)
        log.info(f"  [{fname}] → {table} ({total_rows:,} rows)")

        if dry_run:
            log.info(f"  [DRY RUN] Would load {total_rows:,} rows via {loader_fn.__name__}")
            continue

        t0 = _timer()
        try:
            loaded = loader_fn(conn, filepath, tenant_id)
            log.info(f"  ✓ {table}: {loaded:,} rows loaded in {_elapsed(t0)}")
        except Exception as e:
            log.error(f"  ✗ Failed to load {fname} into {table}: {e}", exc_info=True)
            conn.rollback()


if __name__ == "__main__":
    main()
