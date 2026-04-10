#!/usr/bin/env python3
"""KPI-only tenant loader for pedkai_metrics.kpi_metrics.

Purpose:
- Load baseline KPI telemetry from kpi_metrics_wide.parquet into long-format
  kpi_metrics rows (missing only, idempotent).
- Apply scenario overlays from scenario_kpi_overrides.parquet directly into
  kpi_metrics using multiplicative factors.
- Keep scope strictly to Metrics DB (pedkai_metrics).

This script intentionally does NOT write to graph DB tables.

Usage example:
  ./venv/bin/python -m backend.app.scripts.load_tenant_kpi_only \
    --tenant-id six_telecom \
    --output-dir /home/ubuntu/Pedkai-data/output
"""

from __future__ import annotations

import argparse
import gc
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import psycopg2
import psycopg2.extras
import pyarrow.parquet as pq
from dotenv import load_dotenv

load_dotenv()


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_DEFAULT_DATA_STORE_ROOT = os.environ.get(
    "PEDKAI_DATA_STORE_ROOT", "/Volumes/Projects/Pedkai Data Store"
)

BATCH_WIDE = 5_000
BATCH_KPI_LONG = 50_000
BATCH_OVERRIDES = 50_000

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("kpi_only_loader")


def _timer() -> float:
    return time.time()


def _elapsed(t0: float) -> str:
    dt = time.time() - t0
    if dt < 60:
        return f"{dt:.1f}s"
    return f"{dt / 60:.1f}m"


def _sqlalchemy_url_to_psycopg2_dsn(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme.startswith("postgres"):
        user = parsed.username or ""
        password = parsed.password or ""
        host = parsed.hostname or ""
        port = parsed.port or 5432
        dbname = (parsed.path or "").lstrip("/")
        return f"host={host} port={port} dbname={dbname} user={user} password={password}"
    return url


def _resolve_metrics_dsn() -> str:
    dsn = os.environ.get("METRICS_DB_DSN")
    if dsn:
        return dsn

    metrics_url = os.environ.get("METRICS_DATABASE_URL")
    if metrics_url:
        return _sqlalchemy_url_to_psycopg2_dsn(metrics_url)

    return "host=localhost port=5433 dbname=pedkai_metrics user=postgres password=postgres"


def _get_conn(dsn: str):
    conn = psycopg2.connect(dsn)
    conn.autocommit = False
    return conn


def _ensure_file(path: Path) -> bool:
    if not path.exists():
        log.error("Missing required file: %s", path)
        return False
    return True


def _verify_parquet_tenant_id(filepath: Path, expected_tenant_id: str) -> None:
    """Abort if Parquet file contains wrong or missing tenant_id."""
    try:
        table = pq.read_table(filepath, columns=["tenant_id"])
        unique_tenants = table.column("tenant_id").unique().to_pylist()
        if len(unique_tenants) == 0:
            raise ValueError(f"TENANT MISMATCH in {filepath.name}: no tenant_id values found")
        if len(unique_tenants) != 1 or unique_tenants[0] != expected_tenant_id:
            raise ValueError(
                f"TENANT MISMATCH in {filepath.name}: expected '{expected_tenant_id}', found {unique_tenants}"
            )
    except KeyError as exc:
        raise ValueError(
            f"TENANT MISMATCH in {filepath.name}: file has no 'tenant_id' column"
        ) from exc


def _delete_tenant_kpi(metrics_conn, tenant_id: str) -> int:
    with metrics_conn.cursor() as cur:
        cur.execute("DELETE FROM kpi_metrics WHERE tenant_id = %s", (tenant_id,))
        deleted = cur.rowcount
    metrics_conn.commit()
    return deleted


def _baseline_kpi_columns(pf: pq.ParquetFile) -> list[str]:
    # Non-KPI fields from kpi_metrics_wide.parquet.
    metadata_cols = {
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
    all_cols = [pf.schema_arrow.names[j] for j in range(len(pf.schema_arrow.names))]
    return [c for c in all_cols if c not in metadata_cols]


def load_baseline_kpi(
    metrics_conn,
    filepath: Path,
    tenant_id: str,
    dry_run: bool,
    limit_hours: int,
    wide_batch_size: int,
    long_page_size: int,
) -> dict[str, int]:
    """Load baseline KPI rows from wide parquet into kpi_metrics (missing only)."""
    log.info("━━━ Baseline load: kpi_metrics_wide.parquet -> kpi_metrics ━━━")

    pf = pq.ParquetFile(filepath)
    kpi_cols = _baseline_kpi_columns(pf)

    stats = {
        "wide_rows_scanned": 0,
        "wide_rows_kept": 0,
        "long_rows_attempted": 0,
        "long_rows_inserted": 0,
    }

    cutoff = None
    if limit_hours > 0:
        epoch = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        cutoff = epoch + timedelta(hours=limit_hours)
        log.info("  Time filter enabled: first %d hours (<= %s)", limit_hours, cutoff.isoformat())

    if dry_run:
        total_rows = pf.metadata.num_rows
        estimated = total_rows * max(len(kpi_cols), 1)
        log.info(
            "  [DRY RUN] wide rows=%s, KPI columns=%d, estimated long rows~=%s",
            f"{total_rows:,}",
            len(kpi_cols),
            f"{estimated:,}",
        )
        return stats

    insert_sql = """
        INSERT INTO kpi_metrics (timestamp, tenant_id, entity_id, kpi_name, kpi_value, metadata)
        VALUES %s
        ON CONFLICT DO NOTHING
    """

    t0 = _timer()
    batch_num = 0
    committed_rows_before = None

    with metrics_conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM kpi_metrics WHERE tenant_id = %s", (tenant_id,))
        committed_rows_before = int(cur.fetchone()[0])

        for batch in pf.iter_batches(batch_size=wide_batch_size):
            batch_num += 1
            data = batch.to_pydict()
            n = len(data["cell_id"])
            stats["wide_rows_scanned"] += n

            rows: list[tuple[Any, ...]] = []

            for i in range(n):
                ts = data["timestamp"][i]
                if not hasattr(ts, "timestamp"):
                    continue
                if cutoff is not None and ts > cutoff:
                    continue
                if data["tenant_id"][i] != tenant_id:
                    continue

                stats["wide_rows_kept"] += 1
                entity_id = data["cell_id"][i]

                meta: dict[str, Any] = {}
                for mcol in ["rat_type", "band", "site_id", "vendor", "deployment_profile", "is_nsa_scg_leg"]:
                    if mcol in data and data[mcol][i] is not None:
                        meta[mcol] = data[mcol][i]
                meta_json = json.dumps(meta)

                for kpi_col in kpi_cols:
                    val = data.get(kpi_col, [None] * n)[i]
                    if val is None:
                        continue
                    rows.append((ts, tenant_id, entity_id, kpi_col, float(val), meta_json))

            if rows:
                stats["long_rows_attempted"] += len(rows)
                psycopg2.extras.execute_values(
                    cur,
                    insert_sql,
                    rows,
                    template="(%s, %s, %s, %s, %s, %s::jsonb)",
                    page_size=long_page_size,
                )

            if batch_num % 25 == 0:
                metrics_conn.commit()
                log.info(
                    "    batch %d: scanned=%s kept=%s long_attempted=%s",
                    batch_num,
                    f"{stats['wide_rows_scanned']:,}",
                    f"{stats['wide_rows_kept']:,}",
                    f"{stats['long_rows_attempted']:,}",
                )

            del data, rows
            gc.collect()

        metrics_conn.commit()

        cur.execute("SELECT COUNT(*) FROM kpi_metrics WHERE tenant_id = %s", (tenant_id,))
        committed_rows_after = int(cur.fetchone()[0])
        stats["long_rows_inserted"] = max(committed_rows_after - committed_rows_before, 0)

    log.info(
        "  Baseline complete in %s | inserted=%s (attempted=%s)",
        _elapsed(t0),
        f"{stats['long_rows_inserted']:,}",
        f"{stats['long_rows_attempted']:,}",
    )
    return stats


def apply_scenario_overrides(
    metrics_conn,
    filepath: Path,
    tenant_id: str,
    dry_run: bool,
    overrides_batch_size: int,
) -> dict[str, int]:
    """Apply scenario_kpi_overrides into existing kpi_metrics rows.

    Option A policy for unmatched rows:
    - Log-only, do not insert synthetic rows.
    """
    log.info("━━━ Overlay apply: scenario_kpi_overrides.parquet -> kpi_metrics ━━━")

    stats = {
        "override_rows_total": 0,
        "override_rows_tenant": 0,
        "override_rows_dedup": 0,
        "override_rows_duplicate_keys": 0,
        "override_rows_unmatched": 0,
        "override_rows_updated": 0,
    }

    if dry_run:
        pf = pq.ParquetFile(filepath)
        stats["override_rows_total"] = pf.metadata.num_rows
        log.info("  [DRY RUN] override rows total=%s", f"{stats['override_rows_total']:,}")
        return stats

    t0 = _timer()

    with metrics_conn.cursor() as cur:
        cur.execute(
            """
            CREATE TEMP TABLE _kpi_overrides_raw (
                tenant_id TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                ts TIMESTAMPTZ NOT NULL,
                kpi_name TEXT NOT NULL,
                override_value DOUBLE PRECISION NOT NULL,
                scenario_id TEXT,
                scenario_type TEXT,
                source_file TEXT
            ) ON COMMIT DROP
            """
        )

    pf = pq.ParquetFile(filepath)
    with metrics_conn.cursor() as cur:
        batch_num = 0
        for batch in pf.iter_batches(batch_size=overrides_batch_size):
            batch_num += 1
            data = batch.to_pydict()
            n = len(data["entity_id"])
            stats["override_rows_total"] += n

            rows: list[tuple[Any, ...]] = []
            for i in range(n):
                if data["tenant_id"][i] != tenant_id:
                    continue
                kpi_name = data.get("kpi_column", [None] * n)[i]
                ts = data.get("timestamp", [None] * n)[i]
                if not kpi_name or ts is None:
                    continue
                rows.append(
                    (
                        tenant_id,
                        data["entity_id"][i],
                        ts,
                        str(kpi_name),
                        float(data.get("override_value", [1.0] * n)[i]),
                        data.get("scenario_id", [None] * n)[i],
                        data.get("scenario_type", [None] * n)[i],
                        data.get("source_file", [None] * n)[i],
                    )
                )

            if rows:
                stats["override_rows_tenant"] += len(rows)
                psycopg2.extras.execute_values(
                    cur,
                    """
                    INSERT INTO _kpi_overrides_raw
                        (tenant_id, entity_id, ts, kpi_name, override_value, scenario_id, scenario_type, source_file)
                    VALUES %s
                    """,
                    rows,
                    page_size=10_000,
                )

            if batch_num % 20 == 0:
                metrics_conn.commit()
                log.info(
                    "    override batch %d: total=%s tenant=%s",
                    batch_num,
                    f"{stats['override_rows_total']:,}",
                    f"{stats['override_rows_tenant']:,}",
                )

            del data, rows
            gc.collect()

        metrics_conn.commit()

    with metrics_conn.cursor() as cur:
        cur.execute(
            """
            SELECT COALESCE(SUM(cnt - 1), 0)
            FROM (
                SELECT COUNT(*) AS cnt
                FROM _kpi_overrides_raw
                GROUP BY tenant_id, entity_id, ts, kpi_name
                HAVING COUNT(*) > 1
            ) d
            """
        )
        stats["override_rows_duplicate_keys"] = int(cur.fetchone()[0] or 0)

        cur.execute(
            """
            CREATE TEMP TABLE _kpi_overrides AS
            SELECT DISTINCT ON (tenant_id, entity_id, ts, kpi_name)
                tenant_id, entity_id, ts, kpi_name,
                override_value, scenario_id, scenario_type, source_file
            FROM _kpi_overrides_raw
            ORDER BY tenant_id, entity_id, ts, kpi_name, scenario_id NULLS LAST
            """
        )

        cur.execute("SELECT COUNT(*) FROM _kpi_overrides")
        stats["override_rows_dedup"] = int(cur.fetchone()[0])

        cur.execute(
            """
            SELECT COUNT(*)
            FROM _kpi_overrides o
            LEFT JOIN kpi_metrics km
              ON km.tenant_id = o.tenant_id
             AND km.entity_id = o.entity_id
             AND km.timestamp = o.ts
             AND km.kpi_name = o.kpi_name
            WHERE km.tenant_id IS NULL
            """
        )
        stats["override_rows_unmatched"] = int(cur.fetchone()[0])

        cur.execute(
            """
            UPDATE kpi_metrics km
            SET
                kpi_value = km.kpi_value * o.override_value,
                metadata = COALESCE(km.metadata, '{}'::jsonb) || jsonb_build_object(
                    'scenario_injected', true,
                    'override_factor', o.override_value,
                    'scenario_id', o.scenario_id,
                    'scenario_type', o.scenario_type,
                    'source_file', o.source_file,
                    'injection_applied_at', NOW()::text
                )
            FROM _kpi_overrides o
            WHERE km.tenant_id = o.tenant_id
              AND km.entity_id = o.entity_id
              AND km.timestamp = o.ts
              AND km.kpi_name = o.kpi_name
              AND NOT COALESCE((km.metadata->>'scenario_injected')::boolean, false)
            """
        )
        stats["override_rows_updated"] = int(cur.rowcount)

    metrics_conn.commit()

    if stats["override_rows_unmatched"] > 0:
        log.warning(
            "  Unmatched overrides (Option A log-only): %s",
            f"{stats['override_rows_unmatched']:,}",
        )

    if stats["override_rows_duplicate_keys"] > 0:
        log.warning(
            "  Duplicate override keys detected (dedup used first row): %s",
            f"{stats['override_rows_duplicate_keys']:,}",
        )

    log.info(
        "  Overlay complete in %s | updated=%s dedup=%s",
        _elapsed(t0),
        f"{stats['override_rows_updated']:,}",
        f"{stats['override_rows_dedup']:,}",
    )
    return stats


def _resolve_output_dir(output_dir: str | None, data_root: str, tenant_id: str) -> Path:
    if output_dir:
        return Path(output_dir).expanduser().resolve()

    root = Path(data_root).expanduser().resolve()
    expected = ["kpi_metrics_wide.parquet", "scenario_kpi_overrides.parquet"]
    if root.exists() and any((root / f).exists() for f in expected):
        return root
    return root / tenant_id / "output"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Load missing KPI baseline and scenario overlays into pedkai_metrics.kpi_metrics",
    )
    parser.add_argument("--tenant-id", required=True, help="Tenant ID")
    parser.add_argument("--output-dir", default=None, help="Folder containing parquet files")
    parser.add_argument("--data-root", default=_DEFAULT_DATA_STORE_ROOT, help="Base data root")
    parser.add_argument("--dry-run", action="store_true", help="Validate and estimate only")
    parser.add_argument("--force", action="store_true", help="Delete tenant KPI rows before load")
    parser.add_argument(
        "--limit-hours",
        type=int,
        default=0,
        help="Load only first N hours from kpi_metrics_wide (0 = full file)",
    )
    parser.add_argument(
        "--skip-overrides",
        action="store_true",
        help="Skip scenario_kpi_overrides apply phase",
    )
    parser.add_argument("--wide-batch-size", type=int, default=BATCH_WIDE)
    parser.add_argument("--long-page-size", type=int, default=BATCH_KPI_LONG)
    parser.add_argument("--overrides-batch-size", type=int, default=BATCH_OVERRIDES)
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    tenant_id = args.tenant_id
    output_dir = _resolve_output_dir(args.output_dir, args.data_root, tenant_id)
    baseline_file = output_dir / "kpi_metrics_wide.parquet"
    overrides_file = output_dir / "scenario_kpi_overrides.parquet"

    log.info("=" * 72)
    log.info("  Pedkai KPI-only Loader")
    log.info("=" * 72)
    log.info("  Tenant ID:       %s", tenant_id)
    log.info("  Output dir:      %s", output_dir)
    log.info("  Dry run:         %s", args.dry_run)
    log.info("  Force reset:     %s", args.force)
    log.info("  Limit hours:     %s", args.limit_hours)
    log.info("  Apply overrides: %s", not args.skip_overrides)

    if not output_dir.exists():
        log.error("Output directory not found: %s", output_dir)
        sys.exit(1)

    if not _ensure_file(baseline_file):
        sys.exit(1)

    if (not args.skip_overrides) and (not _ensure_file(overrides_file)):
        sys.exit(1)

    try:
        _verify_parquet_tenant_id(baseline_file, tenant_id)
        if not args.skip_overrides:
            _verify_parquet_tenant_id(overrides_file, tenant_id)
    except Exception as exc:
        log.error("Tenant validation failed: %s", exc)
        sys.exit(1)

    dsn = _resolve_metrics_dsn()

    try:
        metrics_conn = _get_conn(dsn)
    except Exception as exc:
        log.error("Cannot connect to Metrics DB: %s", exc)
        sys.exit(1)

    overall_t0 = _timer()

    try:
        if args.force and not args.dry_run:
            deleted = _delete_tenant_kpi(metrics_conn, tenant_id)
            log.warning("Force mode: deleted %s rows from kpi_metrics", f"{deleted:,}")

        baseline_stats = load_baseline_kpi(
            metrics_conn=metrics_conn,
            filepath=baseline_file,
            tenant_id=tenant_id,
            dry_run=args.dry_run,
            limit_hours=args.limit_hours,
            wide_batch_size=args.wide_batch_size,
            long_page_size=args.long_page_size,
        )

        override_stats: dict[str, int] = {}
        if not args.skip_overrides:
            override_stats = apply_scenario_overrides(
                metrics_conn=metrics_conn,
                filepath=overrides_file,
                tenant_id=tenant_id,
                dry_run=args.dry_run,
                overrides_batch_size=args.overrides_batch_size,
            )

        log.info("-" * 72)
        log.info("Summary")
        log.info("  Baseline wide scanned:    %s", f"{baseline_stats.get('wide_rows_scanned', 0):,}")
        log.info("  Baseline long attempted:  %s", f"{baseline_stats.get('long_rows_attempted', 0):,}")
        log.info("  Baseline long inserted:   %s", f"{baseline_stats.get('long_rows_inserted', 0):,}")

        if override_stats:
            log.info("  Overrides tenant rows:    %s", f"{override_stats.get('override_rows_tenant', 0):,}")
            log.info("  Overrides dedup rows:     %s", f"{override_stats.get('override_rows_dedup', 0):,}")
            log.info("  Overrides updated rows:   %s", f"{override_stats.get('override_rows_updated', 0):,}")
            log.info("  Overrides unmatched rows: %s", f"{override_stats.get('override_rows_unmatched', 0):,}")

        log.info("  Total elapsed:            %s", _elapsed(overall_t0))
        log.info("Done.")

    except KeyboardInterrupt:
        metrics_conn.rollback()
        log.warning("Interrupted by user")
        sys.exit(130)
    except Exception as exc:
        metrics_conn.rollback()
        log.error("Fatal error: %s", exc, exc_info=True)
        sys.exit(1)
    finally:
        metrics_conn.close()


if __name__ == "__main__":
    main()
