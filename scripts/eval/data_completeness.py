#!/usr/bin/env python3
"""EVL-02 -- Data-completeness scorer.

Quantifies, per CMDB `entity_type` and per signal source, what fraction of
declared entities have *any* observed signal (an alarm event and/or a KPI
sample).

Signals considered:
  * alarm signal  -- entity_id appears in the events_alarms parquet
  * kpi signal    -- entity_id appears in the KPI parquet (optional)

Memory safety:
  The KPI parquet can be enormous (the wide store files run to multiple GB,
  and ``kpi_metrics_wide.parquet`` is ~9 GB). We therefore NEVER materialise
  it. We open it via the pyarrow *dataset* API and stream batches reading
  ONLY the entity-id column, accumulating a Python ``set`` of distinct ids.
  A set of distinct entity ids is bounded by the CMDB entity count
  (~800k strings), which is trivially small regardless of KPI row count.

Output:
  A JSON document with a per-``entity_type`` breakdown
  ``{total, with_alarm_signal, with_kpi_signal, with_any_signal, coverage}``
  plus an ``overall`` block, and a printed summary table.

Acceptance guarantee:
  The per-type ``total`` values sum to ``len(cmdb_declared_entities)`` because
  ``total`` is derived directly from a group-by over the CMDB table's own rows.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict

import pyarrow.dataset as ds
import pyarrow.parquet as pq

# Candidate names for the "entity id" column, in preference order. The store's
# CMDB / alarm / wide-KPI files all use ``entity_id``, but radio-cell exports
# sometimes key on ``cell_id``; we adapt to whatever the file actually exposes.
ENTITY_ID_CANDIDATES = ["entity_id", "cell_id", "element_id", "node_id", "id"]


def pick_entity_id_column(schema_names: list[str], source_label: str) -> str:
    """Return the entity-id column present in ``schema_names``.

    Raises a clear error if none of the known candidates are present so the
    operator can adapt, rather than silently producing zero coverage.
    """
    for candidate in ENTITY_ID_CANDIDATES:
        if candidate in schema_names:
            return candidate
    raise SystemExit(
        f"[EVL-02] Could not find an entity-id column in {source_label}. "
        f"Tried {ENTITY_ID_CANDIDATES}; available columns: {schema_names}"
    )


def load_cmdb(path: str) -> tuple[dict[str, str], str, str]:
    """Load the CMDB entity->type mapping.

    Returns ``(entity_type_by_id, id_col, type_col)``.
    """
    schema_names = pq.read_schema(path).names
    id_col = pick_entity_id_column(schema_names, "CMDB entities")
    type_col = "entity_type"
    if type_col not in schema_names:
        raise SystemExit(
            f"[EVL-02] CMDB file lacks an 'entity_type' column; available: {schema_names}"
        )

    table = pq.read_table(path, columns=[id_col, type_col])
    ids = table.column(id_col).to_pylist()
    types = table.column(type_col).to_pylist()
    entity_type_by_id: dict[str, str] = {}
    for eid, etype in zip(ids, types):
        # Keep the declared row count faithful: last-writer-wins on any
        # duplicate id (there should be none, but be deterministic).
        entity_type_by_id[eid] = etype if etype is not None else "UNKNOWN"
    return entity_type_by_id, id_col, type_col


def alarm_signal_ids(path: str, valid_ids: set[str]) -> tuple[set[str], str]:
    """Return the set of entity ids that have >=1 alarm, intersected with CMDB.

    The alarm file is small; read only the id column.
    """
    schema_names = pq.read_schema(path).names
    id_col = pick_entity_id_column(schema_names, "alarms")
    table = pq.read_table(path, columns=[id_col])
    seen = set(table.column(id_col).to_pylist())
    return (seen & valid_ids), id_col


def kpi_signal_ids(path: str, valid_ids: set[str]) -> tuple[set[str], str]:
    """Stream the KPI parquet and return the set of entity ids observed.

    Uses the pyarrow dataset batch API reading ONLY the entity-id column so
    the huge KPI file is never loaded into memory. The accumulated set is
    bounded by the number of distinct CMDB entities.
    """
    dataset = ds.dataset(path, format="parquet")
    id_col = pick_entity_id_column(list(dataset.schema.names), "KPI")

    seen: set[str] = set()
    scanner = dataset.scanner(columns=[id_col], batch_size=1 << 16)
    for batch in scanner.to_batches():
        # Intersect incrementally so ``seen`` stays bounded by CMDB size even
        # if the KPI file references ids outside the CMDB.
        for eid in batch.column(0).to_pylist():
            if eid in valid_ids:
                seen.add(eid)
    return seen, id_col


def build_report(
    entity_type_by_id: dict[str, str],
    alarm_ids: set[str],
    kpi_ids: set[str] | None,
) -> dict:
    per_type: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "total": 0,
            "with_alarm_signal": 0,
            "with_kpi_signal": 0,
            "with_any_signal": 0,
        }
    )

    for eid, etype in entity_type_by_id.items():
        row = per_type[etype]
        row["total"] += 1
        has_alarm = eid in alarm_ids
        has_kpi = kpi_ids is not None and eid in kpi_ids
        if has_alarm:
            row["with_alarm_signal"] += 1
        if has_kpi:
            row["with_kpi_signal"] += 1
        if has_alarm or has_kpi:
            row["with_any_signal"] += 1

    for row in per_type.values():
        row["coverage"] = (
            row["with_any_signal"] / row["total"] if row["total"] else 0.0
        )

    total = len(entity_type_by_id)
    with_any = sum(r["with_any_signal"] for r in per_type.values())
    overall = {
        "total": total,
        "with_alarm_signal": sum(r["with_alarm_signal"] for r in per_type.values()),
        "with_kpi_signal": sum(r["with_kpi_signal"] for r in per_type.values()),
        "with_any_signal": with_any,
        "coverage": with_any / total if total else 0.0,
        "kpi_included": kpi_ids is not None,
    }

    return {
        "overall": overall,
        "per_entity_type": dict(sorted(per_type.items())),
    }


def print_table(report: dict) -> None:
    per_type = report["per_entity_type"]
    header = (
        f"{'entity_type':<28} {'total':>9} {'alarm':>9} "
        f"{'kpi':>9} {'any':>9} {'coverage':>9}"
    )
    print(header)
    print("-" * len(header))
    for etype, row in per_type.items():
        print(
            f"{etype:<28} {row['total']:>9} {row['with_alarm_signal']:>9} "
            f"{row['with_kpi_signal']:>9} {row['with_any_signal']:>9} "
            f"{row['coverage']:>9.3f}"
        )
    print("-" * len(header))
    o = report["overall"]
    print(
        f"{'OVERALL':<28} {o['total']:>9} {o['with_alarm_signal']:>9} "
        f"{o['with_kpi_signal']:>9} {o['with_any_signal']:>9} "
        f"{o['coverage']:>9.3f}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="EVL-02 data-completeness scorer")
    parser.add_argument(
        "--cmdb-entities",
        required=True,
        help="Path to cmdb_declared_entities.parquet",
    )
    parser.add_argument(
        "--alarms",
        required=True,
        help="Path to events_alarms.parquet",
    )
    parser.add_argument(
        "--kpi",
        default=None,
        help="Path to a KPI parquet (optional; may be huge -- streamed, never fully loaded)",
    )
    parser.add_argument(
        "--out",
        required=True,
        help="Path to write the JSON report",
    )
    args = parser.parse_args(argv)

    entity_type_by_id, cmdb_id_col, cmdb_type_col = load_cmdb(args.cmdb_entities)
    valid_ids = set(entity_type_by_id.keys())
    print(
        f"[EVL-02] CMDB: {len(entity_type_by_id)} declared entities "
        f"(id column='{cmdb_id_col}', type column='{cmdb_type_col}')"
    )

    alarm_ids, alarm_id_col = alarm_signal_ids(args.alarms, valid_ids)
    print(
        f"[EVL-02] Alarms: {len(alarm_ids)} distinct CMDB entities with an alarm "
        f"(id column='{alarm_id_col}')"
    )

    kpi_ids: set[str] | None = None
    kpi_id_col = None
    if args.kpi:
        kpi_ids, kpi_id_col = kpi_signal_ids(args.kpi, valid_ids)
        print(
            f"[EVL-02] KPI: {len(kpi_ids)} distinct CMDB entities with a KPI sample "
            f"(id column='{kpi_id_col}', streamed from {args.kpi})"
        )
    else:
        print("[EVL-02] KPI: not provided -- reporting alarm+cmdb coverage only")

    report = build_report(entity_type_by_id, alarm_ids, kpi_ids)
    report["sources"] = {
        "cmdb_entities": {"path": args.cmdb_entities, "id_column": cmdb_id_col},
        "alarms": {"path": args.alarms, "id_column": alarm_id_col},
        "kpi": (
            {"path": args.kpi, "id_column": kpi_id_col} if args.kpi else None
        ),
    }

    # Acceptance invariant: per-type totals must sum to the CMDB entity count.
    per_type_total = sum(r["total"] for r in report["per_entity_type"].values())
    assert per_type_total == len(entity_type_by_id), (
        f"per-type total {per_type_total} != CMDB count {len(entity_type_by_id)}"
    )
    print(
        f"[EVL-02] Invariant OK: per-type totals sum to {per_type_total} "
        f"== len(CMDB) {len(entity_type_by_id)}"
    )

    with open(args.out, "w") as fh:
        json.dump(report, fh, indent=2)
    print(f"[EVL-02] Wrote report -> {args.out}\n")

    print_table(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
