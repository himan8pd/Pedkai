#!/usr/bin/env python3
"""Validate that SQLAlchemy ORM models are in sync with the live database schema.

Connects to the graph database (DATABASE_URL / GRAPH_DB_DSN) and compares every
table registered in Base.metadata against information_schema.columns.

Reports:
  - ORM columns that are missing from the live DB (ORM drifted ahead of migrations)
  - DB columns that are missing from the ORM (shadow columns added outside Alembic)

Exit codes:
  0 — all in-DB tables have no column drift
  1 — at least one drift found
  2 — could not connect to the database

Usage:
  python -m backend.scripts.validate_schema_sync
  python -m backend.scripts.validate_schema_sync --database-url postgresql://...
"""

from __future__ import annotations

import argparse
import os
import sys
from urllib.parse import urlparse

import psycopg2
from dotenv import load_dotenv

# Register all ORM models with Base.metadata — keep this list in sync with
# test_tenant_isolation_enforced.py.
import backend.app.models.abeyance_orm  # noqa: F401
import backend.app.models.abeyance_v3_orm  # noqa: F401
import backend.app.models.action_execution_orm  # noqa: F401
import backend.app.models.audit_orm  # noqa: F401
import backend.app.models.bss_orm  # noqa: F401
import backend.app.models.customer_orm  # noqa: F401
import backend.app.models.decision_trace_orm  # noqa: F401
import backend.app.models.incident_orm  # noqa: F401
import backend.app.models.kpi_orm  # noqa: F401
import backend.app.models.kpi_sample_orm  # noqa: F401
import backend.app.models.network_entity_orm  # noqa: F401
import backend.app.models.policy_orm  # noqa: F401
import backend.app.models.reconciliation_result_orm  # noqa: F401
import backend.app.models.tenant_orm  # noqa: F401
import backend.app.models.topology_models  # noqa: F401
import backend.app.models.user_orm  # noqa: F401
import backend.app.models.user_tenant_access_orm  # noqa: F401

from backend.app.core.database import Base


def _sqlalchemy_url_to_psycopg2_dsn(url: str) -> str:
    """Convert a SQLAlchemy URL (postgresql+asyncpg://...) to a psycopg2 DSN."""
    parsed = urlparse(url)
    if parsed.scheme.startswith("postgres"):
        user = parsed.username or ""
        password = parsed.password or ""
        host = parsed.hostname or ""
        port = parsed.port or 5432
        dbname = (parsed.path or "").lstrip("/")
        return f"host={host} port={port} dbname={dbname} user={user} password={password}"
    return url


def _resolve_dsn() -> str:
    """Resolve the graph DB DSN using the same precedence as load_tenant.py."""
    dsn = os.environ.get("GRAPH_DB_DSN")
    if dsn:
        return dsn
    url = os.environ.get("DATABASE_URL")
    if url:
        return _sqlalchemy_url_to_psycopg2_dsn(url)
    return "host=localhost port=5432 dbname=pedkai user=postgres password=postgres"


def _get_db_columns(conn: psycopg2.extensions.connection, table_name: str, schema: str) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            """,
            (schema, table_name),
        )
        return {row[0] for row in cur.fetchall()}


def main() -> int:
    load_dotenv()

    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Override DATABASE_URL / GRAPH_DB_DSN env var",
    )
    parser.add_argument(
        "--schema",
        default="public",
        help="PostgreSQL schema to inspect (default: public)",
    )
    args = parser.parse_args()

    dsn = (
        _sqlalchemy_url_to_psycopg2_dsn(args.database_url)
        if args.database_url
        else _resolve_dsn()
    )

    try:
        conn = psycopg2.connect(dsn)
    except Exception as exc:
        print(f"ERROR: cannot connect to database: {exc}", file=sys.stderr)
        return 2

    issues: list[str] = []
    not_in_db: list[str] = []

    try:
        for table_name, table in sorted(Base.metadata.tables.items()):
            db_cols = _get_db_columns(conn, table_name, args.schema)
            if not db_cols:
                not_in_db.append(table_name)
                continue

            orm_cols = {col.name for col in table.columns}
            missing_from_db = orm_cols - db_cols
            missing_from_orm = db_cols - orm_cols

            if missing_from_db:
                issues.append(
                    f"  {table_name}: ORM columns not in DB — "
                    + ", ".join(sorted(missing_from_db))
                )
            if missing_from_orm:
                issues.append(
                    f"  {table_name}: DB columns not in ORM — "
                    + ", ".join(sorted(missing_from_orm))
                )
    finally:
        conn.close()

    if not_in_db:
        print(
            "WARN: tables in ORM but not yet in DB (pending migration?):\n"
            + "".join(f"  - {t}\n" for t in not_in_db)
        )

    if issues:
        print("SCHEMA DRIFT DETECTED:\n" + "\n".join(issues))
        return 1

    synced = len(Base.metadata.tables) - len(not_in_db)
    print(f"OK — {synced} tables verified in sync with the database.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
