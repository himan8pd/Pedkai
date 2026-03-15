"""
Divergence Report API — T-025

Exposes the signal-based ReconciliationEngine findings as REST endpoints:

  POST /divergence/run              — trigger divergence detection
  GET  /divergence/summary          — summary stats from last run
  GET  /divergence/records          — paginated divergence records w/ filters
  GET  /divergence/report/{tid}     — full structured report (Roadmap V8 §1.4)

Evaluation-only (separate from operational pipeline):
  GET  /divergence/score/{tid}      — detection accuracy vs ground-truth manifest
"""

import logging
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.database import get_db, get_metrics_db
from backend.app.services.reconciliation_engine import ReconciliationEngine

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class RunReconciliationRequest(BaseModel):
    tenant_id: str


# ---------------------------------------------------------------------------
# POST /divergence/run
# ---------------------------------------------------------------------------


@router.post("/divergence/run")
async def run_reconciliation(
    body: RunReconciliationRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    metrics_db: Annotated[AsyncSession, Depends(get_metrics_db)],
) -> dict:
    """
    Trigger signal-based divergence detection for a tenant.

    Analyses CMDB (network_entities, topology_relationships) against
    operational signals (kpi_metrics on TimescaleDB, telco_events_alarms,
    neighbour_relations) to detect: dark nodes, phantom nodes,
    identity mutations, dark attributes, dark edges, and phantom edges.

    No ground-truth data is used during detection.
    """
    try:
        engine = ReconciliationEngine(db, metrics_db)
        result = await engine.run(body.tenant_id)
        return result
    except Exception as exc:
        logger.error(f"Reconciliation failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# GET /divergence/summary
# ---------------------------------------------------------------------------


@router.get("/divergence/summary")
async def get_divergence_summary(
    tenant_id: Annotated[str, Query(description="Tenant ID to query")],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """
    Summary statistics from the most recent reconciliation run.
    Returns counts by divergence type, domain breakdown, and operational
    inventory metrics (CMDB count vs observed signal count).
    """
    # Get latest run
    run_row = await db.execute(
        text(
            """
            SELECT * FROM reconciliation_runs
            WHERE tenant_id = :tid
            ORDER BY started_at DESC
            LIMIT 1
            """
        ),
        {"tid": tenant_id},
    )
    run = run_row.mappings().fetchone()

    if not run:
        raise HTTPException(
            status_code=404,
            detail=f"No reconciliation run found for tenant '{tenant_id}'. "
                   f"Call POST /divergence/run first.",
        )

    # Counts by type
    type_counts_row = await db.execute(
        text(
            """
            SELECT divergence_type, COUNT(*) as cnt
            FROM reconciliation_results
            WHERE tenant_id = :tid
            GROUP BY divergence_type
            ORDER BY cnt DESC
            """
        ),
        {"tid": tenant_id},
    )
    by_type = {row[0]: row[1] for row in type_counts_row.fetchall()}

    # Counts by domain
    domain_counts_row = await db.execute(
        text(
            """
            SELECT domain, COUNT(*) as cnt
            FROM reconciliation_results
            WHERE tenant_id = :tid AND domain IS NOT NULL
            GROUP BY domain
            ORDER BY cnt DESC
            """
        ),
        {"tid": tenant_id},
    )
    by_domain = {row[0]: row[1] for row in domain_counts_row.fetchall()}

    cmdb_entities = int(run["cmdb_entity_count"] or 0)
    observed_entities = int(run["observed_entity_count"] or 0)
    cmdb_edges = int(run["cmdb_edge_count"] or 0)
    observed_edges = int(run["observed_edge_count"] or 0)

    return {
        "run_id": run["run_id"],
        "tenant_id": tenant_id,
        "run_at": run["completed_at"],
        "duration_seconds": (
            (run["completed_at"] - run["started_at"]).total_seconds()
            if run["completed_at"] and run["started_at"]
            else None
        ),
        "summary": {
            "total_divergences": int(run["total_divergences"] or 0),
            "by_type": by_type,
            "by_domain": by_domain,
        },
        "operational_inventory": {
            "cmdb_entity_count": cmdb_entities,
            "observed_entity_count": observed_entities,
            "cmdb_edge_count": cmdb_edges,
            "observed_edge_count": observed_edges,
        },
    }


# ---------------------------------------------------------------------------
# GET /divergence/aggregations
# ---------------------------------------------------------------------------


@router.get("/divergence/aggregations")
async def get_divergence_aggregations(
    tenant_id: Annotated[str, Query()],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """
    Multi-dimensional aggregations for the executive summary dashboard.
    Returns breakdowns by type+domain, type+target_type, confidence buckets,
    and top affected entities — all computed server-side to avoid shipping
    millions of rows to the browser.
    """
    # -- By type x domain (heatmap data) --
    type_domain_rows = await db.execute(
        text(
            """
            SELECT divergence_type, domain, COUNT(*) AS cnt
            FROM reconciliation_results
            WHERE tenant_id = :tid AND domain IS NOT NULL
            GROUP BY divergence_type, domain
            ORDER BY cnt DESC
            """
        ),
        {"tid": tenant_id},
    )
    type_domain = [
        {"type": r[0], "domain": r[1], "count": r[2]}
        for r in type_domain_rows.fetchall()
    ]

    # -- By type x target_type (top entity types per divergence) --
    type_target_rows = await db.execute(
        text(
            """
            SELECT divergence_type, target_type, COUNT(*) AS cnt
            FROM reconciliation_results
            WHERE tenant_id = :tid AND target_type IS NOT NULL
            GROUP BY divergence_type, target_type
            ORDER BY cnt DESC
            """
        ),
        {"tid": tenant_id},
    )
    type_target = [
        {"type": r[0], "target_type": r[1], "count": r[2]}
        for r in type_target_rows.fetchall()
    ]

    # -- Confidence distribution (buckets) --
    confidence_rows = await db.execute(
        text(
            """
            SELECT
              divergence_type,
              CASE
                WHEN confidence >= 0.9 THEN 'critical'
                WHEN confidence >= 0.7 THEN 'high'
                WHEN confidence >= 0.5 THEN 'medium'
                ELSE 'low'
              END AS bucket,
              COUNT(*) AS cnt
            FROM reconciliation_results
            WHERE tenant_id = :tid
            GROUP BY divergence_type, bucket
            ORDER BY divergence_type, bucket
            """
        ),
        {"tid": tenant_id},
    )
    confidence_buckets = [
        {"type": r[0], "bucket": r[1], "count": r[2]}
        for r in confidence_rows.fetchall()
    ]

    # -- Top affected entities (most divergences per entity) --
    top_entities_rows = await db.execute(
        text(
            """
            SELECT rr.target_id, rr.target_type, rr.domain,
                   COUNT(*) AS divergence_count,
                   AVG(rr.confidence) AS avg_confidence,
                   ne.name AS entity_name, ne.external_id
            FROM reconciliation_results rr
            LEFT JOIN network_entities ne
              ON CAST(ne.id AS TEXT) = rr.target_id AND ne.tenant_id = :tid
            WHERE rr.tenant_id = :tid
              AND rr.entity_or_relationship = 'entity'
            GROUP BY rr.target_id, rr.target_type, rr.domain, ne.name, ne.external_id
            ORDER BY divergence_count DESC
            LIMIT 20
            """
        ),
        {"tid": tenant_id},
    )
    top_entities = [
        {
            "target_id": r[0],
            "target_type": r[1],
            "domain": r[2],
            "divergence_count": r[3],
            "avg_confidence": round(float(r[4]), 3) if r[4] else None,
            "entity_name": r[5],
            "external_id": r[6],
        }
        for r in top_entities_rows.fetchall()
    ]

    # -- Key divergences: highest-confidence, most impactful --
    key_rows = await db.execute(
        text(
            """
            SELECT rr.result_id, rr.divergence_type, rr.target_id, rr.target_type,
                   rr.domain, rr.description, rr.confidence,
                   rr.attribute_name, rr.cmdb_value, rr.observed_value,
                   ne.name AS entity_name, ne.external_id
            FROM reconciliation_results rr
            LEFT JOIN network_entities ne
              ON CAST(ne.id AS TEXT) = rr.target_id AND ne.tenant_id = :tid
            WHERE rr.tenant_id = :tid AND rr.confidence >= 0.8
            ORDER BY rr.confidence DESC, rr.divergence_type
            LIMIT 50
            """
        ),
        {"tid": tenant_id},
    )
    key_divergences = [dict(r) for r in key_rows.mappings().fetchall()]

    return {
        "tenant_id": tenant_id,
        "type_domain": type_domain,
        "type_target": type_target,
        "confidence_buckets": confidence_buckets,
        "top_entities": top_entities,
        "key_divergences": key_divergences,
    }


# ---------------------------------------------------------------------------
# GET /divergence/records
# ---------------------------------------------------------------------------


@router.get("/divergence/records")
async def get_divergence_records(
    tenant_id: Annotated[str, Query()],
    db: Annotated[AsyncSession, Depends(get_db)],
    divergence_type: Annotated[Optional[str], Query()] = None,
    domain: Annotated[Optional[str], Query()] = None,
    target_type: Annotated[Optional[str], Query()] = None,
    confidence_min: Annotated[Optional[float], Query(ge=0, le=1)] = None,
    sort_by: Annotated[Optional[str], Query()] = None,
    sort_dir: Annotated[Optional[str], Query()] = "desc",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict:
    """
    Paginated list of individual divergences with entity name resolution.
    JOINs network_entities to resolve target_id UUIDs into human-readable
    names and external_ids for entity traceability.
    """
    offset = (page - 1) * page_size
    filters = ["rr.tenant_id = :tid"]
    params: dict = {"tid": tenant_id, "limit": page_size, "offset": offset}

    if divergence_type:
        filters.append("rr.divergence_type = :div_type")
        params["div_type"] = divergence_type
    if domain:
        filters.append("rr.domain = :domain")
        params["domain"] = domain
    if target_type:
        filters.append("rr.target_type = :target_type")
        params["target_type"] = target_type
    if confidence_min is not None:
        filters.append("rr.confidence >= :conf_min")
        params["conf_min"] = confidence_min

    where = " AND ".join(filters)

    # Sortable columns whitelist
    sort_columns = {
        "divergence_type": "rr.divergence_type",
        "domain": "rr.domain",
        "target_type": "rr.target_type",
        "confidence": "rr.confidence",
        "entity_name": "ne.name",
    }
    order_col = sort_columns.get(sort_by or "", "rr.confidence")
    order_dir = "ASC" if sort_dir == "asc" else "DESC"

    count_row = await db.execute(
        text(f"SELECT COUNT(*) FROM reconciliation_results rr WHERE {where}"),  # nosec
        params,
    )
    total = count_row.scalar() or 0

    rows_result = await db.execute(
        text(
            f"""
            SELECT rr.result_id, rr.divergence_type, rr.entity_or_relationship,
                   rr.target_id, rr.target_type, rr.domain, rr.description,
                   rr.attribute_name, rr.cmdb_value, rr.observed_value,
                   rr.confidence, rr.created_at,
                   ne.name AS entity_name, ne.external_id AS entity_external_id
            FROM reconciliation_results rr
            LEFT JOIN network_entities ne
              ON CAST(ne.id AS TEXT) = rr.target_id AND ne.tenant_id = :tid
            WHERE {where}
            ORDER BY {order_col} {order_dir}
            LIMIT :limit OFFSET :offset
            """  # nosec
        ),
        params,
    )
    rows = rows_result.mappings().fetchall()

    return {
        "tenant_id": tenant_id,
        "page": page,
        "page_size": page_size,
        "total": total,
        "pages": (total + page_size - 1) // page_size,
        "records": [dict(r) for r in rows],
    }


# ---------------------------------------------------------------------------
# GET /divergence/report/{tenant_id}
# ---------------------------------------------------------------------------


@router.get("/divergence/report/{tenant_id}")
async def get_divergence_report(
    tenant_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """
    Full structured Divergence Report (Roadmap V8 §1.4 format).

    Returns summary + top examples per divergence type.
    Suitable for the Day-1 CIO delivery.
    """
    try:
        summary = await get_divergence_summary(tenant_id, db)
    except HTTPException:
        raise HTTPException(
            status_code=404,
            detail=f"No reconciliation run found for tenant '{tenant_id}'.",
        )

    async def _top_examples(div_type: str, limit: int = 10) -> list[dict]:
        rows = await db.execute(
            text(
                """
                SELECT target_id, target_type, domain, description,
                       attribute_name, cmdb_value, observed_value,
                       confidence
                FROM reconciliation_results
                WHERE tenant_id = :tid AND divergence_type = :dt
                ORDER BY confidence DESC
                LIMIT :limit
                """
            ),
            {"tid": tenant_id, "dt": div_type, "limit": limit},
        )
        return [dict(r) for r in rows.mappings().fetchall()]

    dark_nodes = await _top_examples("dark_node")
    phantom_nodes = await _top_examples("phantom_node")
    dark_attributes = await _top_examples("dark_attribute")
    dark_edges = await _top_examples("dark_edge")
    phantom_edges = await _top_examples("phantom_edge")

    inv = summary["operational_inventory"]
    by_type = summary["summary"]["by_type"]

    headline = (
        f"{by_type.get('dark_edge', 0):,} undocumented dependencies, "
        f"{by_type.get('dark_node', 0):,} unregistered entities, and "
        f"{by_type.get('phantom_node', 0):,} phantom CIs detected "
        f"by analysing operational signals against CMDB declarations. "
        f"CMDB declares {inv['cmdb_entity_count']:,} entities; "
        f"operational signals reference {inv['observed_entity_count']:,} distinct entities."
    )

    return {
        "report_id": f"DIV-{tenant_id}-{summary['run_id'][:8]}",
        "tenant_id": tenant_id,
        "generated_at": summary["run_at"],
        "headline": headline,
        "summary": summary["summary"],
        "operational_inventory": inv,
        "dark_nodes": dark_nodes,
        "phantom_nodes": phantom_nodes,
        "dark_attributes": dark_attributes,
        "dark_edges": dark_edges,
        "phantom_edges": phantom_edges,
        "recommendation": (
            f"Your CMDB declares {inv['cmdb_entity_count']:,} entities and "
            f"{inv['cmdb_edge_count']:,} relationships. Operational signals show "
            f"{inv['observed_entity_count']:,} active entities and "
            f"{inv['observed_edge_count']:,} neighbour relations. "
            f"{by_type.get('phantom_node', 0):,} phantom CIs are wasting licence fees. "
            f"{by_type.get('dark_node', 0):,} entities carry production traffic with "
            f"no change management oversight."
        ),
    }


# ---------------------------------------------------------------------------
# GET /divergence/evidence/{result_id}
# ---------------------------------------------------------------------------


@router.get("/divergence/evidence/{result_id}")
async def get_divergence_evidence(
    result_id: str,
    tenant_id: Annotated[str, Query()],
    db: Annotated[AsyncSession, Depends(get_db)],
    metrics_db: Annotated[AsyncSession, Depends(get_metrics_db)],
) -> dict:
    """
    Fetch contextual telemetry + CMDB evidence for a specific divergence record.

    Returns structured evidence based on divergence type:
    - dark_attribute: KPI sample stats + CMDB entity details
    - dark_edge: neighbour relation stats + CMDB absence confirmation
    - phantom_node: signal sources checked, all zero
    - dark_node: signal source summary from KPI metadata
    """
    # Fetch the divergence record
    row = await db.execute(
        text(
            """
            SELECT rr.*, ne.name AS entity_name, ne.external_id AS entity_external_id,
                   ne.attributes AS entity_attributes, ne.entity_type AS cmdb_entity_type
            FROM reconciliation_results rr
            LEFT JOIN network_entities ne
              ON CAST(ne.id AS TEXT) = rr.target_id AND ne.tenant_id = :tid
            WHERE rr.result_id = :rid AND rr.tenant_id = :tid
            """
        ),
        {"rid": result_id, "tid": tenant_id},
    )
    record = row.mappings().fetchone()
    if not record:
        raise HTTPException(status_code=404, detail="Divergence record not found")

    evidence: dict = {
        "result_id": result_id,
        "divergence_type": record["divergence_type"],
        "target_id": record["target_id"],
        "description": record["description"],
    }

    div_type = record["divergence_type"]

    if div_type == "dark_attribute":
        # Fetch KPI telemetry evidence for this entity + attribute
        attr_name = record["attribute_name"]
        # Safety: only allow known crosscheck attributes in SQL interpolation
        SAFE_ATTRS = {"vendor", "band", "rat_type"}
        if attr_name not in SAFE_ATTRS:
            raise HTTPException(status_code=400, detail=f"Unsupported attribute: {attr_name}")
        target_id = record["target_id"]

        # Get sample distribution from metrics DB
        kpi_stats = await metrics_db.execute(
            text(
                f"""
                SELECT
                    metadata->>'{attr_name}' AS observed_value,
                    COUNT(*) AS sample_count,
                    MIN(time) AS first_seen,
                    MAX(time) AS last_seen
                FROM kpi_metrics
                WHERE tenant_id = :tid
                  AND entity_id = :eid
                  AND metadata->>'{attr_name}' IS NOT NULL
                GROUP BY metadata->>'{attr_name}'
                ORDER BY sample_count DESC
                LIMIT 10
                """  # nosec — attr_name from DB record, not user input
            ),
            {"tid": tenant_id, "eid": target_id},
        )
        telemetry_samples = [
            {
                "value": r[0],
                "sample_count": r[1],
                "first_seen": str(r[2]) if r[2] else None,
                "last_seen": str(r[3]) if r[3] else None,
            }
            for r in kpi_stats.fetchall()
        ]

        # Also try resolving via external_id
        if not telemetry_samples and record["entity_external_id"]:
            kpi_stats2 = await metrics_db.execute(
                text(
                    f"""
                    SELECT
                        metadata->>'{attr_name}' AS observed_value,
                        COUNT(*) AS sample_count,
                        MIN(time) AS first_seen,
                        MAX(time) AS last_seen
                    FROM kpi_metrics
                    WHERE tenant_id = :tid
                      AND entity_id = :eid
                      AND metadata->>'{attr_name}' IS NOT NULL
                    GROUP BY metadata->>'{attr_name}'
                    ORDER BY sample_count DESC
                    LIMIT 10
                    """  # nosec
                ),
                {"tid": tenant_id, "eid": record["entity_external_id"]},
            )
            telemetry_samples = [
                {
                    "value": r[0],
                    "sample_count": r[1],
                    "first_seen": str(r[2]) if r[2] else None,
                    "last_seen": str(r[3]) if r[3] else None,
                }
                for r in kpi_stats2.fetchall()
            ]

        # Build CMDB panel
        cmdb_attrs = record["entity_attributes"] or {}
        if isinstance(cmdb_attrs, str):
            import json as _json
            cmdb_attrs = _json.loads(cmdb_attrs)

        evidence["cmdb"] = {
            "entity_name": record["entity_name"],
            "external_id": record["entity_external_id"],
            "entity_type": record["cmdb_entity_type"],
            "configured_value": record["cmdb_value"],
            "attribute": attr_name,
            "vendor": cmdb_attrs.get("vendor"),
            "band": cmdb_attrs.get("band"),
            "rat_type": cmdb_attrs.get("rat_type"),
            "domain": cmdb_attrs.get("domain"),
        }
        evidence["telemetry"] = {
            "observed_value": record["observed_value"],
            "samples": telemetry_samples,
            "total_samples": sum(s["sample_count"] for s in telemetry_samples),
        }

    elif div_type == "dark_edge":
        # Fetch neighbour relation details
        target_id = record["target_id"]
        nr_row = await db.execute(
            text(
                """
                SELECT nr.*,
                       ne_from.name AS from_name, ne_from.external_id AS from_ext_id,
                       ne_to.name AS to_name, ne_to.external_id AS to_ext_id
                FROM neighbour_relations nr
                LEFT JOIN network_entities ne_from
                  ON CAST(ne_from.id AS TEXT) = nr.from_cell_id AND ne_from.tenant_id = :tid
                LEFT JOIN network_entities ne_to
                  ON CAST(ne_to.id AS TEXT) = nr.to_cell_id AND ne_to.tenant_id = :tid
                WHERE nr.relation_id = :rid AND nr.tenant_id = :tid
                """
            ),
            {"rid": target_id, "tid": tenant_id},
        )
        nr = nr_row.mappings().fetchone()
        if nr:
            evidence["neighbour_relation"] = {
                "from_cell": nr.get("from_name") or nr.get("from_ext_id") or nr["from_cell_id"],
                "from_cell_id": nr["from_cell_id"],
                "to_cell": nr.get("to_name") or nr.get("to_ext_id") or nr["to_cell_id"],
                "to_cell_id": nr["to_cell_id"],
                "neighbour_type": nr.get("neighbour_type"),
                "handover_attempts": nr.get("handover_attempts"),
                "handover_success_rate": nr.get("handover_success_rate"),
            }

        # Confirm CMDB absence
        cmdb_edge = await db.execute(
            text(
                """
                SELECT COUNT(*) FROM topology_relationships
                WHERE tenant_id = :tid
                  AND (
                    (from_entity_id = :from_id AND to_entity_id = :to_id)
                    OR
                    (from_entity_id = :to_id AND to_entity_id = :from_id)
                  )
                """
            ),
            {
                "tid": tenant_id,
                "from_id": nr["from_cell_id"] if nr else "",
                "to_id": nr["to_cell_id"] if nr else "",
            },
        )
        evidence["cmdb_edge_exists"] = (cmdb_edge.scalar() or 0) > 0

    elif div_type == "phantom_node":
        target_id = record["target_id"]
        # Check each signal source
        kpi_count = await metrics_db.execute(
            text(
                "SELECT COUNT(*) FROM kpi_metrics WHERE tenant_id = :tid AND entity_id = :eid"
            ),
            {"tid": tenant_id, "eid": target_id},
        )
        alarm_count = await db.execute(
            text(
                "SELECT COUNT(*) FROM telco_events_alarms WHERE tenant_id = :tid AND entity_id = :eid"
            ),
            {"tid": tenant_id, "eid": target_id},
        )
        nr_count = await db.execute(
            text(
                """
                SELECT COUNT(*) FROM neighbour_relations
                WHERE tenant_id = :tid
                  AND (from_cell_id = :eid OR to_cell_id = :eid)
                """
            ),
            {"tid": tenant_id, "eid": target_id},
        )

        evidence["signal_check"] = {
            "kpi_samples": kpi_count.scalar() or 0,
            "alarm_events": alarm_count.scalar() or 0,
            "neighbour_relations": nr_count.scalar() or 0,
            "detection_method": "signal_absence",
            "entity_name_used": False,
        }
        evidence["cmdb"] = {
            "entity_name": record["entity_name"],
            "external_id": record["entity_external_id"],
            "entity_type": record["cmdb_entity_type"],
        }

    elif div_type == "dark_node":
        target_id = record["target_id"]
        # Get signal summary from KPI metadata
        kpi_summary = await metrics_db.execute(
            text(
                """
                SELECT
                    metadata->>'domain' AS domain,
                    metadata->>'vendor' AS vendor,
                    metadata->>'rat_type' AS rat_type,
                    COUNT(*) AS sample_count,
                    MIN(time) AS first_seen,
                    MAX(time) AS last_seen
                FROM kpi_metrics
                WHERE tenant_id = :tid AND entity_id = :eid
                GROUP BY metadata->>'domain', metadata->>'vendor', metadata->>'rat_type'
                ORDER BY sample_count DESC
                LIMIT 5
                """
            ),
            {"tid": tenant_id, "eid": target_id},
        )
        signal_profiles = [
            {
                "domain": r[0],
                "vendor": r[1],
                "rat_type": r[2],
                "sample_count": r[3],
                "first_seen": str(r[4]) if r[4] else None,
                "last_seen": str(r[5]) if r[5] else None,
            }
            for r in kpi_summary.fetchall()
        ]

        # Also check alarms
        alarm_summary = await db.execute(
            text(
                """
                SELECT domain, severity, COUNT(*) AS cnt
                FROM telco_events_alarms
                WHERE tenant_id = :tid AND entity_id = :eid
                GROUP BY domain, severity
                ORDER BY cnt DESC
                LIMIT 5
                """
            ),
            {"tid": tenant_id, "eid": target_id},
        )
        alarm_profiles = [
            {"domain": r[0], "severity": r[1], "count": r[2]}
            for r in alarm_summary.fetchall()
        ]

        evidence["signal_summary"] = {
            "kpi_profiles": signal_profiles,
            "alarm_profiles": alarm_profiles,
            "signal_id": target_id,
        }

    return evidence


# ---------------------------------------------------------------------------
# GET /divergence/score/{tenant_id}  — EVALUATION ONLY
# ---------------------------------------------------------------------------


@router.get("/divergence/score/{tenant_id}")
async def get_detection_score(
    tenant_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """
    [EVALUATION ONLY] Detection accuracy vs pre-seeded divergence_manifest.

    This endpoint is NOT part of the operational pipeline. It compares
    engine output against ground-truth labels for development benchmarking.
    The engine itself never reads ground-truth data.
    """
    from backend.app.services.divergence_scorer import DivergenceScorer

    scorer = DivergenceScorer(db)
    return await scorer.score(tenant_id)


# -- TASK-301: File-based Divergence Analysis endpoints --

import asyncio
import tempfile
import os as _os
from fastapi import UploadFile, File, BackgroundTasks

_analysis_jobs: dict = {}


@router.post("/dark-graph/analyze")
async def analyze_divergence(
    background_tasks: BackgroundTasks,
    cmdb_file: UploadFile = File(...),
    telemetry_file: UploadFile = File(...),
    ticket_file: UploadFile = File(...),
    tenant_id: str = "default",
):
    """Upload 3 files, trigger file-based divergence analysis. Returns job_id."""
    from backend.app.services.dark_graph.divergence_reporter import DivergenceReporter

    job_id = str(__import__("uuid").uuid4())
    _analysis_jobs[job_id] = {"status": "processing", "report": None}

    # Save uploaded files to temp
    tmp_dir = tempfile.mkdtemp()
    cmdb_path = _os.path.join(tmp_dir, cmdb_file.filename or "cmdb.csv")
    tel_path = _os.path.join(tmp_dir, telemetry_file.filename or "telemetry.csv")
    tick_path = _os.path.join(tmp_dir, ticket_file.filename or "tickets.csv")

    with open(cmdb_path, "wb") as f:
        f.write(await cmdb_file.read())
    with open(tel_path, "wb") as f:
        f.write(await telemetry_file.read())
    with open(tick_path, "wb") as f:
        f.write(await ticket_file.read())

    async def _run():
        try:
            reporter = DivergenceReporter()
            report = reporter.generate_report(
                tenant_id=tenant_id,
                cmdb_path=cmdb_path,
                telemetry_path=tel_path,
                ticket_path=tick_path,
            )
            _analysis_jobs[job_id]["status"] = "complete"
            _analysis_jobs[job_id]["report"] = report.to_dict()
        except Exception as e:
            _analysis_jobs[job_id]["status"] = "failed"
            _analysis_jobs[job_id]["error"] = str(e)

    background_tasks.add_task(_run)
    return {"job_id": job_id, "status": "processing"}


@router.get("/dark-graph/report/{job_id}")
async def get_file_divergence_report(job_id: str):
    """Get divergence report by job_id."""
    job = _analysis_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return job
