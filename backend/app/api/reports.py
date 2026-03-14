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

from backend.app.core.database import get_db
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
) -> dict:
    """
    Trigger signal-based divergence detection for a tenant.

    Analyses CMDB (network_entities, topology_relationships) against
    operational signals (kpi_metrics, telco_events_alarms, neighbour_relations)
    to detect: dark nodes, phantom nodes, dark attributes,
    dark edges, and phantom edges.

    No ground-truth data is used during detection.
    """
    try:
        engine = ReconciliationEngine(db)
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
# GET /divergence/records
# ---------------------------------------------------------------------------


@router.get("/divergence/records")
async def get_divergence_records(
    tenant_id: Annotated[str, Query()],
    db: Annotated[AsyncSession, Depends(get_db)],
    divergence_type: Annotated[Optional[str], Query()] = None,
    domain: Annotated[Optional[str], Query()] = None,
    target_type: Annotated[Optional[str], Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict:
    """
    Paginated list of individual divergences from the latest reconciliation run.
    Filter by divergence_type, domain, and/or target_type.
    """
    offset = (page - 1) * page_size
    filters = ["tenant_id = :tid"]
    params: dict = {"tid": tenant_id, "limit": page_size, "offset": offset}

    if divergence_type:
        filters.append("divergence_type = :div_type")
        params["div_type"] = divergence_type
    if domain:
        filters.append("domain = :domain")
        params["domain"] = domain
    if target_type:
        filters.append("target_type = :target_type")
        params["target_type"] = target_type

    where = " AND ".join(filters)

    count_row = await db.execute(
        text(f"SELECT COUNT(*) FROM reconciliation_results WHERE {where}"),  # nosec
        params,
    )
    total = count_row.scalar() or 0

    rows_result = await db.execute(
        text(
            f"""
            SELECT result_id, divergence_type, entity_or_relationship,
                   target_id, target_type, domain, description,
                   attribute_name, cmdb_value, observed_value,
                   confidence, created_at
            FROM reconciliation_results
            WHERE {where}
            ORDER BY divergence_type, domain, target_type
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
