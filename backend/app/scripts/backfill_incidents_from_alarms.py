#!/usr/bin/env python3
"""
Historic Backfill Script — Process Loaded Alarms into Incidents & Decision Traces
==================================================================================

Reads the 15,341 alarms in ``telco_events_alarms`` for tenant
``pedkai_telco2_01`` and processes them through Pedkai's alarm correlation
engine to produce ``incidents`` and ``decision_traces`` rows.  This is
exactly what a real customer would expect: "feed Pedkai my history and let
it show me what it finds."

What this unlocks
-----------------
- Dashboard scorecard (MTTR, incident count, alarm feed)
- Incidents page (full incident list with ITIL priority)
- TMF642 ``GET /alarm`` returns real alarm resources
- Service Impact page (alarm clusters with noise reduction)
- Scorecard page (MTTR, drift, value capture)

Usage
-----
::

    cd /Users/himanshu/Projects/Pedkai
    ./venv/bin/python -m backend.app.scripts.backfill_incidents_from_alarms [--force] [--dry-run] [--batch-size 500]

Idempotency
-----------
Before inserting the script checks whether incidents already exist for the
tenant.  If they do it prints a warning and exits unless ``--force`` is
passed, in which case it deletes existing incidents and decision traces
before re-creating them.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import psycopg2
import psycopg2.extras

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

TENANT_ID = "pedkai_telco2_01"  # default; overridden by --tenant-id CLI arg

import os

# Database connection strings (sync psycopg2 for performance)
# Read from env var if available, fall back to localhost default for local dev
GRAPH_DB_DSN = os.environ.get(
    "GRAPH_DB_DSN",
    "host=localhost port=5432 dbname=pedkai user=postgres password=postgres",
)

# Temporal window matching AlarmCorrelationService (5 min)
TEMPORAL_WINDOW_MINUTES = 5

# Default batch commit size
DEFAULT_BATCH_SIZE = 500

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("backfill_incidents")

# ---------------------------------------------------------------------------
# ITIL severity mapping (mirrors backend/app/schemas/incidents.py)
# ---------------------------------------------------------------------------

SEVERITY_TO_ITIL: Dict[str, Tuple[str, str, str]] = {
    "critical": ("high", "high", "P1"),
    "high": ("high", "medium", "P2"),
    "major": ("high", "medium", "P2"),
    "medium": ("medium", "medium", "P3"),
    "minor": ("medium", "low", "P3"),
    "warning": ("low", "medium", "P4"),
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _timer() -> float:
    return time.time()


def _elapsed(t0: float) -> str:
    dt = time.time() - t0
    if dt < 60:
        return f"{dt:.1f}s"
    return f"{dt / 60:.1f}m"


def _get_conn(dsn: str):
    conn = psycopg2.connect(dsn)
    conn.autocommit = False
    return conn


# ---------------------------------------------------------------------------
# Alarm reader
# ---------------------------------------------------------------------------


def read_alarms(conn) -> List[Dict[str, Any]]:
    """Read all alarms for the tenant ordered by raised_at ASC."""
    log.info(f"Reading alarms from telco_events_alarms for tenant={TENANT_ID} ...")
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT alarm_id, tenant_id, entity_id, entity_type,
                   alarm_type, severity, raised_at, cleared_at,
                   source_system, probable_cause, domain,
                   scenario_id, is_synthetic_scenario,
                   additional_text, correlation_group_id, created_at
            FROM telco_events_alarms
            WHERE tenant_id = %s
            ORDER BY raised_at ASC NULLS LAST
            """,
            (TENANT_ID,),
        )
        rows = cur.fetchall()
    log.info(f"  Read {len(rows):,} alarms")
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Temporal windowing (mirrors AlarmCorrelationService logic)
# ---------------------------------------------------------------------------


def group_into_windows(
    alarms: List[Dict[str, Any]],
) -> List[List[Dict[str, Any]]]:
    """Split alarms into non-overlapping temporal windows of TEMPORAL_WINDOW_MINUTES."""
    if not alarms:
        return []

    windows: List[List[Dict[str, Any]]] = []
    current_window: List[Dict[str, Any]] = []
    window_start: Optional[datetime] = None

    for alarm in alarms:
        raised = alarm.get("raised_at")
        if raised is None:
            # Alarms without a timestamp go into the current window
            if current_window:
                current_window.append(alarm)
            else:
                current_window = [alarm]
                window_start = None
            continue

        if window_start is None:
            window_start = raised
            current_window = [alarm]
            continue

        elapsed = (raised - window_start).total_seconds()
        if elapsed <= TEMPORAL_WINDOW_MINUTES * 60:
            current_window.append(alarm)
        else:
            # Finalize current window, start new one
            if current_window:
                windows.append(current_window)
            current_window = [alarm]
            window_start = raised

    if current_window:
        windows.append(current_window)

    return windows


# ---------------------------------------------------------------------------
# Lightweight in-process correlation (avoids async dependency)
# ---------------------------------------------------------------------------


def correlate_window(alarms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Correlate alarms within a single temporal window into clusters.

    Mirrors ``AlarmCorrelationService.correlate_alarms`` logic but runs
    synchronously without requiring an async session.

    Strategy:
    1. Group by entity_id
    2. Within each entity group, further sub-group by alarm_type
    3. Cross-entity merge for same alarm_type (since they're already in
       the same temporal window, temporal overlap is guaranteed)
    """
    if not alarms:
        return []

    # Group by entity_id
    entity_groups: Dict[str, List[Dict[str, Any]]] = {}
    for alarm in alarms:
        eid = alarm.get("entity_id") or "unknown"
        entity_groups.setdefault(eid, []).append(alarm)

    # Create proto-clusters: one per (entity_id, alarm_type) pair
    proto_clusters: List[List[Dict[str, Any]]] = []
    for _eid, group in entity_groups.items():
        type_sub: Dict[Optional[str], List[Dict[str, Any]]] = {}
        for a in group:
            atype = a.get("alarm_type")
            type_sub.setdefault(atype, []).append(a)
        for _atype, sub in type_sub.items():
            proto_clusters.append(sub)

    # Cross-entity merge for same alarm_type
    type_index: Dict[Optional[str], List[int]] = {}
    for idx, cluster in enumerate(proto_clusters):
        atype = cluster[0].get("alarm_type") if cluster else None
        type_index.setdefault(atype, []).append(idx)

    merged_flags = [False] * len(proto_clusters)
    final_clusters: List[List[Dict[str, Any]]] = []

    for atype, indices in type_index.items():
        if atype is None:
            # Don't merge clusters with unknown alarm type across entities
            for idx in indices:
                if not merged_flags[idx]:
                    final_clusters.append(proto_clusters[idx])
                    merged_flags[idx] = True
            continue

        # Merge all clusters of same non-None alarm_type in this window
        merged: List[Dict[str, Any]] = []
        for idx in indices:
            if not merged_flags[idx]:
                merged.extend(proto_clusters[idx])
                merged_flags[idx] = True
        if merged:
            final_clusters.append(merged)

    # Add any remaining un-merged
    for idx, cluster in enumerate(proto_clusters):
        if not merged_flags[idx]:
            final_clusters.append(cluster)

    # Build cluster dicts
    severity_order = {"critical": 4, "major": 3, "minor": 2, "warning": 1}

    result_clusters: List[Dict[str, Any]] = []
    for cluster_alarms in final_clusters:
        if not cluster_alarms:
            continue

        severities = [a.get("severity", "minor") for a in cluster_alarms]
        cluster_severity = max(severities, key=lambda s: severity_order.get(s, 0))

        entity_ids = [a.get("entity_id") for a in cluster_alarms if a.get("entity_id")]
        root_entity = max(set(entity_ids), key=entity_ids.count) if entity_ids else None

        result_clusters.append(
            {
                "alarm_count": len(cluster_alarms),
                "alarms": cluster_alarms,
                "severity": cluster_severity,
                "root_cause_entity_id": root_entity,
            }
        )

    return result_clusters


# ---------------------------------------------------------------------------
# Incident + Decision Trace builders
# ---------------------------------------------------------------------------


def build_incident(cluster: Dict[str, Any], cluster_idx: int) -> Dict[str, Any]:
    """Build an incident dict from a cluster."""
    severity_str = cluster["severity"] or "minor"
    impact, urgency, priority = SEVERITY_TO_ITIL.get(
        severity_str, SEVERITY_TO_ITIL["minor"]
    )

    root_entity = cluster.get("root_cause_entity_id")
    alarm_types = list({a.get("alarm_type", "UNKNOWN") for a in cluster["alarms"]})

    # Determine created_at from earliest alarm in cluster
    raised_times = [
        a["raised_at"] for a in cluster["alarms"] if a.get("raised_at") is not None
    ]
    created_at = min(raised_times) if raised_times else datetime.now(timezone.utc)

    # Determine if incident should be closed
    # If ALL alarms in the cluster have cleared_at, close the incident
    cleared_times = [
        a["cleared_at"] for a in cluster["alarms"] if a.get("cleared_at") is not None
    ]
    all_cleared = (
        len(cleared_times) == len(cluster["alarms"]) and len(cleared_times) > 0
    )

    if all_cleared:
        closed_at = max(cleared_times)
        status = "closed"
    else:
        closed_at = None
        status = "anomaly"

    incident_id = str(uuid.uuid4())
    title = (
        f"{', '.join(alarm_types[:3])} on {root_entity or 'multiple entities'} "
        f"({cluster['alarm_count']} alarm{'s' if cluster['alarm_count'] != 1 else ''})"
    )

    return {
        "id": incident_id,
        "tenant_id": TENANT_ID,
        "title": title[:500],
        "severity": severity_str,
        "status": status,
        "impact": impact,
        "urgency": urgency,
        "priority": priority,
        "entity_id": str(root_entity) if root_entity else None,
        "entity_external_id": None,
        "decision_trace_id": None,  # Will be updated after traces are created
        "reasoning_chain": None,
        "resolution_summary": "Historic backfill — resolved by operator"
        if all_cleared
        else None,
        "kpi_snapshot": None,
        "llm_model_version": None,
        "llm_prompt_hash": None,
        "sitrep_approved_by": None,
        "sitrep_approved_at": None,
        "action_approved_by": None,
        "action_approved_at": None,
        "closed_by": "historic_backfill" if all_cleared else None,
        "closed_at": closed_at,
        "created_at": created_at,
        "updated_at": closed_at if closed_at else created_at,
    }


def build_decision_trace(alarm: Dict[str, Any], incident_id: str) -> Dict[str, Any]:
    """Build a decision_trace dict from an individual alarm."""
    alarm_type = alarm.get("alarm_type") or "UNKNOWN"
    probable_cause = alarm.get("probable_cause") or ""
    entity_id = alarm.get("entity_id")
    entity_type = alarm.get("entity_type") or "NETWORK_ELEMENT"
    severity = alarm.get("severity") or "minor"
    raised_at = alarm.get("raised_at") or datetime.now(timezone.utc)
    cleared_at = alarm.get("cleared_at")
    alarm_id = alarm.get("alarm_id") or str(uuid.uuid4())

    status = "cleared" if cleared_at else "raised"
    description = f"Historic alarm: {alarm_type}"
    if probable_cause:
        description += f" — {probable_cause}"

    trace_id = str(uuid.uuid4())

    return {
        "id": trace_id,
        "tenant_id": TENANT_ID,
        "created_at": raised_at,
        "decision_made_at": raised_at,
        "trigger_type": "EXTERNAL_ALARM",
        "trigger_id": alarm_id,
        "trigger_description": description[:1000],
        "entity_id": str(entity_id) if entity_id else None,
        "entity_type": entity_type,
        "context": "{}",
        "constraints": "[]",
        "options_considered": "[]",
        "decision_summary": (
            f"Alarm {alarm_type} detected on entity {entity_id}. "
            f"Severity: {severity}. Correlated into incident {incident_id}."
        ),
        "tradeoff_rationale": (
            f"Historic backfill: alarm auto-correlated by temporal window "
            f"({TEMPORAL_WINDOW_MINUTES}min) and alarm-type grouping."
        ),
        "action_taken": "Correlated into incident"
        if not cleared_at
        else "Correlated into incident (auto-cleared)",
        "decision_maker": "historic_backfill_script",
        "confidence_score": 0.7,
        "outcome": None,
        "embedding": None,
        "embedding_provider": None,
        "embedding_model": None,
        "memory_hits": 0,
        "causal_evidence_count": 0,
        "tags": "[]",
        "domain": "anops",
        "title": f"{alarm_type} — {entity_id}"[:500] if entity_id else alarm_type[:500],
        "severity": severity,
        "status": status,
        "ack_state": "unacknowledged",
        "external_correlation_id": alarm.get("correlation_group_id"),
        "internal_correlation_id": incident_id,
        "probable_cause": (probable_cause or alarm_type)[:100],
        "feedback_score": 0,
        "parent_id": None,
        "derivation_type": None,
    }


# ---------------------------------------------------------------------------
# Database writers
# ---------------------------------------------------------------------------

INSERT_INCIDENT_SQL = """
    INSERT INTO incidents (
        id, tenant_id, title, severity, status,
        impact, urgency, priority,
        entity_id, entity_external_id,
        decision_trace_id, reasoning_chain, resolution_summary,
        kpi_snapshot, llm_model_version, llm_prompt_hash,
        sitrep_approved_by, sitrep_approved_at,
        action_approved_by, action_approved_at,
        closed_by, closed_at,
        created_at, updated_at
    ) VALUES %s
    ON CONFLICT (id) DO NOTHING
"""

INSERT_DECISION_TRACE_SQL = """
    INSERT INTO decision_traces (
        id, tenant_id, created_at, decision_made_at,
        trigger_type, trigger_id, trigger_description,
        entity_id, entity_type,
        context, constraints, options_considered,
        decision_summary, tradeoff_rationale, action_taken,
        decision_maker, confidence_score,
        outcome, embedding, embedding_provider, embedding_model,
        memory_hits, causal_evidence_count, tags, domain,
        title, severity, status, ack_state,
        external_correlation_id, internal_correlation_id,
        probable_cause, feedback_score,
        parent_id, derivation_type
    ) VALUES %s
    ON CONFLICT (id) DO NOTHING
"""


def _incident_tuple(inc: Dict[str, Any]) -> tuple:
    return (
        inc["id"],
        inc["tenant_id"],
        inc["title"],
        inc["severity"],
        inc["status"],
        inc["impact"],
        inc["urgency"],
        inc["priority"],
        inc["entity_id"],
        inc["entity_external_id"],
        inc["decision_trace_id"],
        None,
        inc["resolution_summary"],
        None,
        inc["llm_model_version"],
        inc["llm_prompt_hash"],
        inc["sitrep_approved_by"],
        inc["sitrep_approved_at"],
        inc["action_approved_by"],
        inc["action_approved_at"],
        inc["closed_by"],
        inc["closed_at"],
        inc["created_at"],
        inc["updated_at"],
    )


def _trace_tuple(t: Dict[str, Any]) -> tuple:
    return (
        t["id"],
        t["tenant_id"],
        t["created_at"],
        t["decision_made_at"],
        t["trigger_type"],
        t["trigger_id"],
        t["trigger_description"],
        t["entity_id"],
        t["entity_type"],
        t["context"],
        t["constraints"],
        t["options_considered"],
        t["decision_summary"],
        t["tradeoff_rationale"],
        t["action_taken"],
        t["decision_maker"],
        t["confidence_score"],
        t["outcome"],
        t["embedding"],
        t["embedding_provider"],
        t["embedding_model"],
        t["memory_hits"],
        t["causal_evidence_count"],
        t["tags"],
        t["domain"],
        t["title"],
        t["severity"],
        t["status"],
        t["ack_state"],
        t["external_correlation_id"],
        t["internal_correlation_id"],
        t["probable_cause"],
        t["feedback_score"],
        t["parent_id"],
        t["derivation_type"],
    )


def write_batch(
    conn,
    incidents: List[Dict[str, Any]],
    traces: List[Dict[str, Any]],
    dry_run: bool = False,
) -> Tuple[int, int]:
    """Write a batch of incidents and traces. Returns (incidents_written, traces_written)."""
    if dry_run:
        return len(incidents), len(traces)

    inc_written = 0
    trace_written = 0

    with conn.cursor() as cur:
        if incidents:
            psycopg2.extras.execute_values(
                cur,
                INSERT_INCIDENT_SQL,
                [_incident_tuple(i) for i in incidents],
                page_size=500,
            )
            inc_written = len(incidents)

        if traces:
            psycopg2.extras.execute_values(
                cur,
                INSERT_DECISION_TRACE_SQL,
                [_trace_tuple(t) for t in traces],
                page_size=500,
            )
            trace_written = len(traces)

    conn.commit()
    return inc_written, trace_written


# ---------------------------------------------------------------------------
# Idempotency check / cleanup
# ---------------------------------------------------------------------------


def check_existing(conn) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM incidents WHERE tenant_id = %s", (TENANT_ID,))
        return cur.fetchone()[0]


def delete_existing(conn) -> Tuple[int, int]:
    """Delete existing incidents and decision traces for the tenant."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM decision_traces WHERE tenant_id = %s", (TENANT_ID,))
        traces_deleted = cur.rowcount
        cur.execute("DELETE FROM incidents WHERE tenant_id = %s", (TENANT_ID,))
        incidents_deleted = cur.rowcount
    conn.commit()
    return incidents_deleted, traces_deleted


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------


def main():
    global TENANT_ID

    parser = argparse.ArgumentParser(
        description="Backfill incidents and decision traces from telco_events_alarms"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Delete existing incidents/traces and re-create",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Read and correlate alarms but don't write to DB",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Commit batch size (default: {DEFAULT_BATCH_SIZE})",
    )
    parser.add_argument(
        "--tenant-id",
        type=str,
        default=None,
        help=f"Tenant ID to backfill (default: {TENANT_ID})",
    )
    args = parser.parse_args()

    if args.tenant_id:
        TENANT_ID = args.tenant_id

    log.info("=" * 70)
    log.info("Historic Backfill: telco_events_alarms → incidents + decision_traces")
    log.info(f"  Tenant:     {TENANT_ID}")
    log.info(f"  Dry run:    {args.dry_run}")
    log.info(f"  Force:      {args.force}")
    log.info(f"  Batch size: {args.batch_size}")
    log.info("=" * 70)

    t0 = _timer()

    # Connect to graph DB
    log.info("Connecting to graph DB ...")
    conn = _get_conn(GRAPH_DB_DSN)

    # Idempotency check
    existing_count = check_existing(conn)
    if existing_count > 0:
        if args.force:
            log.warning(
                f"Found {existing_count:,} existing incidents for {TENANT_ID}. "
                f"--force specified — deleting ..."
            )
            inc_del, trace_del = delete_existing(conn)
            log.info(f"  Deleted {inc_del:,} incidents, {trace_del:,} decision traces")
        else:
            log.error(
                f"Found {existing_count:,} existing incidents for {TENANT_ID}. "
                f"Use --force to delete and re-create, or remove them manually."
            )
            sys.exit(1)

    # Step 1: Read alarms
    alarms = read_alarms(conn)
    if not alarms:
        log.warning("No alarms found. Nothing to do.")
        sys.exit(0)

    # Step 2: Group into temporal windows
    log.info(
        f"Grouping {len(alarms):,} alarms into {TEMPORAL_WINDOW_MINUTES}-minute windows ..."
    )
    windows = group_into_windows(alarms)
    log.info(f"  Created {len(windows):,} temporal windows")

    # Step 3: Correlate each window
    log.info("Correlating alarms within windows ...")
    all_incidents: List[Dict[str, Any]] = []
    all_traces: List[Dict[str, Any]] = []
    total_clusters = 0

    for win_idx, window_alarms in enumerate(windows):
        clusters = correlate_window(window_alarms)
        total_clusters += len(clusters)

        for cl_idx, cluster in enumerate(clusters):
            # Build incident
            incident = build_incident(cluster, total_clusters + cl_idx)
            incident_id = incident["id"]

            # Build decision traces for each alarm in the cluster
            cluster_traces: List[Dict[str, Any]] = []
            for alarm in cluster["alarms"]:
                trace = build_decision_trace(alarm, incident_id)
                cluster_traces.append(trace)

            # Link first trace to the incident
            if cluster_traces:
                incident["decision_trace_id"] = cluster_traces[0]["id"]

            all_incidents.append(incident)
            all_traces.extend(cluster_traces)

    log.info(
        f"  Correlation complete: {len(alarms):,} alarms → "
        f"{total_clusters:,} clusters → {len(all_incidents):,} incidents, "
        f"{len(all_traces):,} decision traces"
    )

    # Calculate noise reduction
    noise_reduction: float = 0.0
    if len(alarms) > 0 and total_clusters > 0:
        noise_reduction = ((len(alarms) - total_clusters) / len(alarms)) * 100
        log.info(f"  Noise reduction: {noise_reduction:.1f}%")

    # Count closed vs open
    closed_count = sum(1 for i in all_incidents if i["status"] == "closed")
    open_count = len(all_incidents) - closed_count
    log.info(f"  Open incidents: {open_count:,}  |  Closed incidents: {closed_count:,}")

    # Step 4: Write to DB in batches
    log.info(f"Writing to DB (batch_size={args.batch_size}) ...")
    total_inc_written = 0
    total_trace_written = 0

    # Write incidents in batches
    for batch_start in range(0, len(all_incidents), args.batch_size):
        batch_end = min(batch_start + args.batch_size, len(all_incidents))
        inc_batch = all_incidents[batch_start:batch_end]

        # Collect all traces that belong to incidents in this batch
        incident_ids_in_batch = {i["id"] for i in inc_batch}
        trace_batch = [
            t
            for t in all_traces
            if t["internal_correlation_id"] in incident_ids_in_batch
        ]

        inc_w, trace_w = write_batch(conn, inc_batch, trace_batch, dry_run=args.dry_run)
        total_inc_written += inc_w
        total_trace_written += trace_w

        if (batch_start // args.batch_size) % 10 == 0:
            log.info(
                f"  Progress: {batch_end:,}/{len(all_incidents):,} incidents, "
                f"{total_trace_written:,} traces"
            )

    # Handle any traces not yet written (safety net for orphaned traces)
    written_trace_ids = set()
    for batch_start in range(0, len(all_incidents), args.batch_size):
        batch_end = min(batch_start + args.batch_size, len(all_incidents))
        incident_ids_in_batch = {i["id"] for i in all_incidents[batch_start:batch_end]}
        for t in all_traces:
            if t["internal_correlation_id"] in incident_ids_in_batch:
                written_trace_ids.add(t["id"])

    remaining_traces = [t for t in all_traces if t["id"] not in written_trace_ids]
    if remaining_traces:
        log.info(f"  Writing {len(remaining_traces):,} remaining traces ...")
        _, extra_t = write_batch(conn, [], remaining_traces, dry_run=args.dry_run)
        total_trace_written += extra_t

    conn.close()

    # Summary
    elapsed = _elapsed(t0)
    log.info("")
    log.info("=" * 70)
    log.info("BACKFILL COMPLETE")
    log.info("=" * 70)
    log.info(f"  Tenant:              {TENANT_ID}")
    log.info(f"  Alarms processed:    {len(alarms):,}")
    log.info(f"  Temporal windows:    {len(windows):,}")
    log.info(f"  Clusters:            {total_clusters:,}")
    log.info(f"  Incidents created:   {total_inc_written:,}")
    log.info(f"  Decision traces:     {total_trace_written:,}")
    log.info(f"    ├─ Open:           {open_count:,}")
    log.info(f"    └─ Closed (MTTR):  {closed_count:,}")
    if len(alarms) > 0 and total_clusters > 0:
        log.info(f"  Noise reduction:     {noise_reduction:.1f}%")
    log.info(f"  Dry run:             {args.dry_run}")
    log.info(f"  Elapsed:             {elapsed}")
    log.info("=" * 70)

    if args.dry_run:
        log.info("DRY RUN — no data was written. Remove --dry-run to persist.")


if __name__ == "__main__":
    main()
