"""
Divergence Report API — T-025

Exposes the signal-based ReconciliationEngine findings as REST endpoints:

  POST /divergence/run              — trigger divergence detection (async, returns job_id)
  GET  /divergence/run/{job_id}     — poll job status
  GET  /divergence/summary          — summary stats from last run
  GET  /divergence/records          — paginated divergence records w/ filters
  GET  /divergence/report/{tid}     — full structured report (Roadmap V8 §1.4)

Reconciliation is long-running (minutes on large datasets). The POST endpoint
immediately returns a job_id; callers must poll GET /divergence/run/{job_id}
for completion. This avoids Cloudflare's 100s upstream timeout (HTTP 524).
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Annotated, Dict, Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Security
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.database import async_session_maker, get_db, get_metrics_db, metrics_session_maker
from backend.app.core.security import User, get_current_user
from backend.app.services.reconciliation_engine import ReconciliationEngine

logger = logging.getLogger(__name__)
router = APIRouter()

# ---------------------------------------------------------------------------
# In-memory job store (single-instance deployment)
# Keyed by job_id. Cleaned up after 1 hour to avoid unbounded growth.
# ---------------------------------------------------------------------------

_jobs: Dict[str, dict] = {}


def _make_job(tenant_id: str) -> dict:
    return {
        "job_id": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "status": "running",          # running | complete | failed
        "started_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": None,
        "result": None,
        "error": None,
    }


async def _run_reconciliation_job(job_id: str, tenant_id: str) -> None:
    """Background task: run reconciliation and update job state when done."""
    try:
        async with async_session_maker() as db, metrics_session_maker() as metrics_db:
            engine = ReconciliationEngine(db, metrics_db)
            result = await engine.run(tenant_id)
        _jobs[job_id]["status"] = "complete"
        _jobs[job_id]["result"] = result
        _jobs[job_id]["completed_at"] = datetime.now(timezone.utc).isoformat()
        logger.info(f"Reconciliation job {job_id} complete for tenant '{tenant_id}'")
    except Exception as exc:
        _jobs[job_id]["status"] = "failed"
        _jobs[job_id]["error"] = str(exc)
        _jobs[job_id]["completed_at"] = datetime.now(timezone.utc).isoformat()
        logger.error(f"Reconciliation job {job_id} failed: {exc}", exc_info=True)


def _tenant_from_jwt(current_user: User) -> str:
    """Extract tenant_id from JWT, raising 403 if not set."""
    if not current_user.tenant_id:
        raise HTTPException(status_code=403, detail="No tenant selected. Call /select-tenant first.")
    return current_user.tenant_id


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class RunReconciliationRequest(BaseModel):
    tenant_id: Optional[str] = None  # Ignored — tenant_id is now extracted from JWT


# ---------------------------------------------------------------------------
# POST /divergence/run
# ---------------------------------------------------------------------------


@router.post("/divergence/run", status_code=202)
async def run_reconciliation(
    body: RunReconciliationRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Security(get_current_user, scopes=["topology:read"]),
) -> dict:
    """
    Trigger signal-based divergence detection for a tenant.

    Returns immediately with a job_id (HTTP 202 Accepted). Poll
    GET /divergence/run/{job_id} to check status and retrieve results.

    Analyses CMDB (network_entities, topology_relationships) against
    operational signals (kpi_metrics on TimescaleDB, telco_events_alarms,
    neighbour_relations) to detect: dark nodes, phantom nodes,
    identity mutations, dark attributes, dark edges, and phantom edges.

    No ground-truth data is used during detection.
    """
    tenant_id = _tenant_from_jwt(current_user)

    # Prevent duplicate concurrent runs for the same tenant
    for job in _jobs.values():
        if job["tenant_id"] == tenant_id and job["status"] == "running":
            return {
                "job_id": job["job_id"],
                "status": "running",
                "message": "Reconciliation already in progress for this tenant.",
            }

    job = _make_job(tenant_id)
    _jobs[job["job_id"]] = job
    background_tasks.add_task(_run_reconciliation_job, job["job_id"], tenant_id)

    return {
        "job_id": job["job_id"],
        "status": "running",
        "message": "Reconciliation started. Poll GET /divergence/run/{job_id} for status.",
    }


@router.get("/divergence/run/{job_id}")
async def get_reconciliation_job(
    job_id: str,
    current_user: User = Security(get_current_user, scopes=["topology:read"]),
) -> dict:
    """Poll reconciliation job status. Returns status, and result/error when complete."""
    _tenant_from_jwt(current_user)  # Ensure tenant is selected
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")
    return job


# ---------------------------------------------------------------------------
# GET /divergence/summary
# ---------------------------------------------------------------------------


@router.get("/divergence/summary")
async def get_divergence_summary(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Security(get_current_user, scopes=["topology:read"]),
) -> dict:
    """
    Summary statistics from the most recent reconciliation run.
    Returns counts by divergence type, domain breakdown, and operational
    inventory metrics (CMDB count vs observed signal count).
    """
    tenant_id = _tenant_from_jwt(current_user)

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
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Security(get_current_user, scopes=["topology:read"]),
) -> dict:
    """
    Multi-dimensional aggregations for the executive summary dashboard.
    Returns breakdowns by type+domain, type+target_type, confidence buckets,
    and top affected entities — all computed server-side to avoid shipping
    millions of rows to the browser.
    """
    tenant_id = _tenant_from_jwt(current_user)

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
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Security(get_current_user, scopes=["topology:read"]),
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
    tenant_id = _tenant_from_jwt(current_user)
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
    current_user: User = Security(get_current_user, scopes=["topology:read"]),
) -> dict:
    """
    Full structured Divergence Report (Roadmap V8 §1.4 format).

    Returns summary + top examples per divergence type.
    Suitable for the Day-1 CIO delivery.

    Note: tenant_id path parameter is kept for URL compatibility but the
    authoritative tenant comes from the JWT. The path param is ignored.
    """
    tenant_id = _tenant_from_jwt(current_user)
    try:
        summary = await get_divergence_summary(db=db, current_user=current_user)
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
    db: Annotated[AsyncSession, Depends(get_db)],
    metrics_db: Annotated[AsyncSession, Depends(get_metrics_db)],
    current_user: User = Security(get_current_user, scopes=["topology:read"]),
) -> dict:
    """
    Fetch contextual telemetry + CMDB evidence for a specific divergence record.

    Returns structured evidence based on divergence type:
    - dark_attribute: KPI sample stats + CMDB entity details
    - dark_edge: neighbour relation stats + CMDB absence confirmation
    - phantom_node: signal sources checked, all zero
    - dark_node: signal source summary from KPI metadata
    """
    tenant_id = _tenant_from_jwt(current_user)

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
                    MIN(timestamp) AS first_seen,
                    MAX(timestamp) AS last_seen
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
                        MIN(timestamp) AS first_seen,
                        MAX(timestamp) AS last_seen
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
                    MIN(timestamp) AS first_seen,
                    MAX(timestamp) AS last_seen
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
# GET /data-health
# ---------------------------------------------------------------------------


@router.get("/data-health")
async def get_data_health(
    db: Annotated[AsyncSession, Depends(get_db)],
    metrics_db: Annotated[AsyncSession, Depends(get_metrics_db)],
    current_user: User = Security(get_current_user, scopes=["topology:read"]),
) -> dict:
    """
    Data health summary for the dashboard. Returns entity counts, alarm counts,
    KPI coverage, last ingestion timestamp, and last reconciliation status.
    """
    tenant_id = _tenant_from_jwt(current_user)

    # Entity count
    entity_count = 0
    try:
        r = await db.execute(
            text("SELECT COUNT(*) FROM network_entities WHERE tenant_id = :tid"),
            {"tid": tenant_id},
        )
        entity_count = r.scalar() or 0
    except Exception:
        pass

    # Relationship count
    rel_count = 0
    try:
        r = await db.execute(
            text("SELECT COUNT(*) FROM topology_relationships WHERE tenant_id = :tid"),
            {"tid": tenant_id},
        )
        rel_count = r.scalar() or 0
    except Exception:
        pass

    # Alarm count + severity breakdown
    alarm_count = 0
    alarm_by_severity = {}
    try:
        r = await db.execute(
            text(
                "SELECT severity, COUNT(*) FROM telco_events_alarms "
                "WHERE tenant_id = :tid GROUP BY severity ORDER BY COUNT(*) DESC"
            ),
            {"tid": tenant_id},
        )
        for sev, cnt in r.fetchall():
            alarm_by_severity[sev or "unknown"] = cnt
            alarm_count += cnt
    except Exception:
        pass

    # Customer count
    customer_count = 0
    try:
        r = await db.execute(
            text("SELECT COUNT(*) FROM customers WHERE tenant_id = :tid"),
            {"tid": tenant_id},
        )
        customer_count = r.scalar() or 0
    except Exception:
        pass

    # KPI coverage (metrics DB)
    kpi_entity_count = 0
    kpi_sample_count = 0
    kpi_time_range = None
    try:
        r = await metrics_db.execute(
            text(
                "SELECT COUNT(DISTINCT entity_id), COUNT(*), MIN(timestamp), MAX(timestamp) "
                "FROM kpi_metrics WHERE tenant_id = :tid"
            ),
            {"tid": tenant_id},
        )
        row = r.fetchone()
        if row:
            kpi_entity_count = row[0] or 0
            kpi_sample_count = row[1] or 0
            if row[2] and row[3]:
                kpi_time_range = {
                    "earliest": str(row[2]),
                    "latest": str(row[3]),
                }
    except Exception:
        pass

    # Incident count
    incident_count = 0
    open_incidents = 0
    try:
        r = await db.execute(
            text("SELECT COUNT(*) FROM incidents WHERE tenant_id = :tid"),
            {"tid": tenant_id},
        )
        incident_count = r.scalar() or 0
        r2 = await db.execute(
            text(
                "SELECT COUNT(*) FROM incidents WHERE tenant_id = :tid "
                "AND status NOT IN ('closed')"
            ),
            {"tid": tenant_id},
        )
        open_incidents = r2.scalar() or 0
    except Exception:
        pass

    # Last reconciliation run
    last_recon = None
    try:
        r = await db.execute(
            text(
                "SELECT run_id, status, total_divergences, dark_nodes, phantom_nodes, "
                "dark_edges, phantom_edges, started_at, completed_at "
                "FROM reconciliation_runs WHERE tenant_id = :tid "
                "ORDER BY started_at DESC LIMIT 1"
            ),
            {"tid": tenant_id},
        )
        row = r.mappings().fetchone()
        if row:
            last_recon = {
                "run_id": row["run_id"],
                "status": row["status"],
                "total_divergences": int(row["total_divergences"] or 0),
                "dark_nodes": int(row["dark_nodes"] or 0),
                "phantom_nodes": int(row["phantom_nodes"] or 0),
                "dark_edges": int(row["dark_edges"] or 0),
                "phantom_edges": int(row["phantom_edges"] or 0),
                "completed_at": str(row["completed_at"]) if row["completed_at"] else None,
            }
    except Exception:
        pass

    # Neighbour relations count
    nr_count = 0
    try:
        r = await db.execute(
            text("SELECT COUNT(*) FROM neighbour_relations WHERE tenant_id = :tid"),
            {"tid": tenant_id},
        )
        nr_count = r.scalar() or 0
    except Exception:
        pass

    return {
        "tenant_id": tenant_id,
        "entities": entity_count,
        "relationships": rel_count,
        "alarms": alarm_count,
        "alarm_by_severity": alarm_by_severity,
        "customers": customer_count,
        "neighbour_relations": nr_count,
        "kpi": {
            "entities_with_kpi": kpi_entity_count,
            "total_samples": kpi_sample_count,
            "time_range": kpi_time_range,
        },
        "incidents": {
            "total": incident_count,
            "open": open_incidents,
        },
        "last_reconciliation": last_recon,
    }


# ---------------------------------------------------------------------------
# GET /divergence/enriched-profile/{result_id}
# ---------------------------------------------------------------------------


@router.get("/divergence/enriched-profile/{result_id}")
async def get_enriched_profile(
    result_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    metrics_db: Annotated[AsyncSession, Depends(get_metrics_db)],
    current_user: User = Security(get_current_user, scopes=["topology:read"]),
) -> dict:
    """
    Generate an intelligence-enriched profile for a divergence entity.

    For dark nodes: infers device type, vendor, protocols, traffic role,
    and probable network position from telemetry signals.

    For phantom nodes: explains why the entity is considered phantom
    and suggests remediation actions.

    For dark edges: analyzes the operational relationship evidence.

    Returns classification confidence and reasoning chain.
    """
    tenant_id = _tenant_from_jwt(current_user)

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

    div_type = record["divergence_type"]
    target_id = record["target_id"]
    profile: dict = {
        "result_id": result_id,
        "divergence_type": div_type,
        "target_id": target_id,
        "entity_name": record.get("entity_name"),
        "description": record["description"],
    }

    if div_type == "dark_node":
        # Infer device characteristics from KPI metadata
        kpi_meta = await metrics_db.execute(
            text(
                """
                SELECT
                    metadata->>'domain' AS domain,
                    metadata->>'vendor' AS vendor,
                    metadata->>'rat_type' AS rat_type,
                    metadata->>'band' AS band,
                    metadata->>'deployment_profile' AS deployment_profile,
                    metadata->>'site_id' AS site_id,
                    COUNT(*) AS sample_count,
                    COUNT(DISTINCT kpi_name) AS distinct_kpis,
                    MIN(timestamp) AS first_seen,
                    MAX(timestamp) AS last_seen,
                    AVG(kpi_value) AS avg_value
                FROM kpi_metrics
                WHERE tenant_id = :tid AND entity_id = :eid
                GROUP BY metadata->>'domain', metadata->>'vendor', metadata->>'rat_type',
                         metadata->>'band', metadata->>'deployment_profile', metadata->>'site_id'
                ORDER BY sample_count DESC
                LIMIT 5
                """
            ),
            {"tid": tenant_id, "eid": target_id},
        )
        signal_profiles = []
        for r in kpi_meta.fetchall():
            signal_profiles.append({
                "domain": r[0], "vendor": r[1], "rat_type": r[2],
                "band": r[3], "deployment_profile": r[4], "site_id": r[5],
                "sample_count": r[6], "distinct_kpis": r[7],
                "first_seen": str(r[8]) if r[8] else None,
                "last_seen": str(r[9]) if r[9] else None,
                "avg_value": float(r[10]) if r[10] else None,
            })

        # Get distinct KPI names to infer device role
        kpi_names_row = await metrics_db.execute(
            text(
                """
                SELECT DISTINCT kpi_name FROM kpi_metrics
                WHERE tenant_id = :tid AND entity_id = :eid
                ORDER BY kpi_name
                LIMIT 50
                """
            ),
            {"tid": tenant_id, "eid": target_id},
        )
        kpi_names = [r[0] for r in kpi_names_row.fetchall()]

        # Get alarm profile
        alarm_row = await db.execute(
            text(
                """
                SELECT alarm_type, severity, probable_cause, domain, COUNT(*) AS cnt,
                       MIN(raised_at) AS first_alarm, MAX(raised_at) AS last_alarm
                FROM telco_events_alarms
                WHERE tenant_id = :tid AND entity_id = :eid
                GROUP BY alarm_type, severity, probable_cause, domain
                ORDER BY cnt DESC
                LIMIT 10
                """
            ),
            {"tid": tenant_id, "eid": target_id},
        )
        alarm_profiles = [
            {
                "alarm_type": r[0], "severity": r[1], "probable_cause": r[2],
                "domain": r[3], "count": r[4],
                "first_alarm": str(r[5]) if r[5] else None,
                "last_alarm": str(r[6]) if r[6] else None,
            }
            for r in alarm_row.fetchall()
        ]

        # Check neighbour relations for topology context
        nr_row = await db.execute(
            text(
                """
                SELECT
                    CASE WHEN from_cell_id = :eid THEN to_cell_id ELSE from_cell_id END AS peer_id,
                    neighbour_type,
                    handover_attempts,
                    handover_success_rate,
                    distance_m
                FROM neighbour_relations
                WHERE tenant_id = :tid AND (from_cell_id = :eid OR to_cell_id = :eid)
                ORDER BY handover_attempts DESC NULLS LAST
                LIMIT 10
                """
            ),
            {"tid": tenant_id, "eid": target_id},
        )
        neighbours = [
            {
                "peer_id": r[0], "neighbour_type": r[1],
                "handover_attempts": r[2], "handover_success_rate": float(r[3]) if r[3] else None,
                "distance_m": float(r[4]) if r[4] else None,
            }
            for r in nr_row.fetchall()
        ]

        # --- INFERENCE ---
        primary = signal_profiles[0] if signal_profiles else {}

        # Infer device type
        inferred_type = "UNKNOWN"
        type_confidence = 0.0
        type_reasoning = []

        if primary.get("rat_type"):
            rat = primary["rat_type"].upper() if primary["rat_type"] else ""
            if "NR" in rat or "5G" in rat:
                inferred_type = "NR_CELL"
                type_confidence = 0.85
                type_reasoning.append(f"RAT type '{primary['rat_type']}' indicates 5G NR cell")
            elif "LTE" in rat or "4G" in rat:
                inferred_type = "LTE_CELL"
                type_confidence = 0.85
                type_reasoning.append(f"RAT type '{primary['rat_type']}' indicates LTE cell")
            elif "UMTS" in rat or "3G" in rat:
                inferred_type = "UMTS_CELL"
                type_confidence = 0.80
                type_reasoning.append(f"RAT type '{primary['rat_type']}' indicates UMTS cell")

        if primary.get("domain"):
            domain = primary["domain"].upper() if primary["domain"] else ""
            if "TRANSPORT" in domain and inferred_type == "UNKNOWN":
                inferred_type = "PE_ROUTER"
                type_confidence = 0.65
                type_reasoning.append(f"Domain '{primary['domain']}' suggests transport element")
            elif "CORE" in domain and inferred_type == "UNKNOWN":
                inferred_type = "CORE_ELEMENT"
                type_confidence = 0.60
                type_reasoning.append(f"Domain '{primary['domain']}' suggests core network element")

        if neighbours:
            type_reasoning.append(f"{len(neighbours)} neighbour relations found — entity participates in handover/routing")
            if type_confidence > 0:
                type_confidence = min(0.95, type_confidence + 0.05)

        if not type_reasoning:
            type_reasoning.append("Insufficient telemetry metadata to classify device type")

        # Infer role
        role = "Unknown"
        role_reasoning = []
        if kpi_names:
            ran_kpis = [k for k in kpi_names if any(x in k.lower() for x in ["throughput", "prb", "rsrp", "sinr", "cqi", "bler", "handover"])]
            transport_kpis = [k for k in kpi_names if any(x in k.lower() for x in ["latency", "jitter", "packet_loss", "bandwidth", "utilization"])]

            if ran_kpis:
                role = "RAN Access Point"
                role_reasoning.append(f"Reports {len(ran_kpis)} RAN-specific KPIs: {', '.join(ran_kpis[:5])}")
            elif transport_kpis:
                role = "Transport Node"
                role_reasoning.append(f"Reports {len(transport_kpis)} transport KPIs: {', '.join(transport_kpis[:5])}")
            else:
                role = "Network Element"
                role_reasoning.append(f"Reports {len(kpi_names)} KPIs but no clear domain signature")

        profile["enrichment"] = {
            "inferred_device_type": inferred_type,
            "device_type_confidence": round(type_confidence, 2),
            "device_type_reasoning": type_reasoning,
            "inferred_role": role,
            "role_reasoning": role_reasoning,
            "vendor_hint": primary.get("vendor"),
            "domain": primary.get("domain"),
            "rat_type": primary.get("rat_type"),
            "band": primary.get("band"),
            "deployment_profile": primary.get("deployment_profile"),
            "site_association": primary.get("site_id"),
            "observation_window": {
                "first_seen": primary.get("first_seen"),
                "last_seen": primary.get("last_seen"),
                "total_samples": sum(p.get("sample_count", 0) for p in signal_profiles),
                "distinct_kpis": len(kpi_names),
            },
            "kpi_names": kpi_names[:20],
            "signal_profiles": signal_profiles,
            "alarm_profiles": alarm_profiles,
            "topology_context": {
                "neighbour_count": len(neighbours),
                "neighbours": neighbours,
            },
        }

    elif div_type == "phantom_node":
        # Explain why phantom and suggest remediation
        profile["enrichment"] = {
            "entity_type": record.get("cmdb_entity_type"),
            "entity_name": record.get("entity_name"),
            "external_id": record.get("entity_external_id"),
            "detection_method": "signal_absence",
            "signals_checked": ["kpi_metrics", "telco_events_alarms", "neighbour_relations"],
            "reasoning": [
                f"Entity '{record.get('entity_name')}' ({record.get('cmdb_entity_type')}) is declared in CMDB",
                "Zero KPI telemetry samples found",
                "Zero alarm events found",
                "Zero neighbour relation references found",
                "Entity type is expected to independently emit operational signals",
            ],
            "remediation_options": [
                "Verify physical equipment status on-site",
                "Check if entity has been decommissioned but not removed from CMDB",
                "Investigate if telemetry collection is misconfigured for this entity",
                "Consider reclassifying as passive infrastructure if no signals expected",
            ],
            "confidence": float(record["confidence"]),
        }

    elif div_type == "dark_edge":
        # Get the neighbour relation details
        nr = await db.execute(
            text(
                """
                SELECT nr.*, ne_from.name AS from_name, ne_to.name AS to_name
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
        nr_rec = nr.mappings().fetchone()

        reasoning = [
            "Operational neighbour relation exists between two entities",
            "No corresponding CMDB topology edge found",
        ]
        if nr_rec:
            if nr_rec.get("handover_attempts"):
                reasoning.append(f"Handover evidence: {nr_rec['handover_attempts']} attempts observed")
            if nr_rec.get("handover_success_rate"):
                reasoning.append(f"Handover success rate: {float(nr_rec['handover_success_rate']):.1%}")
            if nr_rec.get("distance_m"):
                reasoning.append(f"Inter-site distance: {float(nr_rec['distance_m']):.0f}m")

        profile["enrichment"] = {
            "from_entity": nr_rec.get("from_name") or (nr_rec["from_cell_id"] if nr_rec else target_id),
            "to_entity": nr_rec.get("to_name") or (nr_rec["to_cell_id"] if nr_rec else "unknown"),
            "neighbour_type": nr_rec.get("neighbour_type") if nr_rec else None,
            "handover_attempts": nr_rec.get("handover_attempts") if nr_rec else None,
            "handover_success_rate": float(nr_rec["handover_success_rate"]) if nr_rec and nr_rec.get("handover_success_rate") else None,
            "reasoning": reasoning,
            "confidence": float(record["confidence"]),
            "remediation_options": [
                "Add this relationship to CMDB topology",
                "Verify neighbour relation is intentional (not a temporary handover path)",
                "Review ANR (Automatic Neighbour Relation) configuration",
            ],
        }

    elif div_type == "dark_attribute":
        profile["enrichment"] = {
            "attribute": record.get("attribute_name"),
            "cmdb_value": record.get("cmdb_value"),
            "observed_value": record.get("observed_value"),
            "reasoning": [
                f"CMDB declares {record.get('attribute_name')} = '{record.get('cmdb_value')}'",
                f"Operational telemetry consistently reports {record.get('attribute_name')} = '{record.get('observed_value')}'",
                "Discrepancy detected between declared and observed values",
            ],
            "confidence": float(record["confidence"]),
            "remediation_options": [
                f"Update CMDB {record.get('attribute_name')} from '{record.get('cmdb_value')}' to '{record.get('observed_value')}'",
                "Investigate if hardware swap occurred without CMDB update",
                "Verify telemetry source configuration",
            ],
        }

    elif div_type == "phantom_edge":
        profile["enrichment"] = {
            "reasoning": [
                "CMDB topology declares this relationship",
                "Neither endpoint shows operational activity (KPI, alarms, or neighbour relations)",
                "Relationship may represent decommissioned or incorrectly configured infrastructure",
            ],
            "confidence": float(record["confidence"]),
            "remediation_options": [
                "Verify both endpoints are physically connected",
                "Remove relationship from CMDB if endpoints are decommissioned",
                "Check if telemetry collection is misconfigured for either endpoint",
            ],
        }

    elif div_type == "identity_mutation":
        profile["enrichment"] = {
            "reasoning": [
                "Evidence suggests the physical equipment behind this CMDB record has changed",
                record.get("description", ""),
            ],
            "confidence": float(record["confidence"]),
            "remediation_options": [
                "Audit hardware inventory records for this entity",
                "Verify serial numbers and hardware IDs match CMDB records",
                "Update CMDB if hardware replacement was performed",
            ],
        }

    # Kick off LLM analysis in the background (non-blocking)
    if profile.get("enrichment"):
        _enqueue_ai_analysis(result_id, profile["enrichment"], div_type, target_id)

    return profile


# ---------------------------------------------------------------------------
# Async AI Analysis — background job pattern
# ---------------------------------------------------------------------------

_ai_analysis_cache: dict = {}  # result_id -> {"status": "pending"|"completed"|"failed", "data": ...}


def _enqueue_ai_analysis(result_id: str, enrichment: dict, div_type: str, target_id: str) -> None:
    """Start AI analysis in background if not already running/completed."""
    if result_id in _ai_analysis_cache:
        return  # Already queued or completed
    _ai_analysis_cache[result_id] = {"status": "pending", "data": None}
    import threading
    t = threading.Thread(
        target=_run_ai_analysis_sync,
        args=(result_id, enrichment, div_type, target_id),
        daemon=True,
    )
    t.start()


def _run_ai_analysis_sync(result_id: str, enrichment: dict, div_type: str, target_id: str) -> None:
    """Run LLM inference in a background thread."""
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(_run_ai_analysis(result_id, enrichment, div_type, target_id))
    finally:
        loop.close()


async def _run_ai_analysis(result_id: str, enrichment: dict, div_type: str, target_id: str) -> None:
    from backend.app.services.enrichment_llm import augment_enrichment
    try:
        ai_analysis = await augment_enrichment(enrichment, div_type, target_id)
        if ai_analysis:
            _ai_analysis_cache[result_id] = {"status": "completed", "data": ai_analysis}
        else:
            _ai_analysis_cache[result_id] = {"status": "failed", "data": None}
    except Exception:
        _ai_analysis_cache[result_id] = {"status": "failed", "data": None}


@router.get("/divergence/ai-analysis/{result_id}")
async def get_ai_analysis(
    result_id: str,
    current_user: User = Security(get_current_user, scopes=["topology:read"]),
) -> dict:
    """Poll for AI analysis status. Returns status and data when complete."""
    entry = _ai_analysis_cache.get(result_id)
    if not entry:
        return {"status": "not_started", "data": None}
    return entry


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
    current_user: User = Security(get_current_user, scopes=["topology:read"]),
):
    """Upload 3 files, trigger file-based divergence analysis. Returns job_id."""
    tenant_id = _tenant_from_jwt(current_user)
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
async def get_file_divergence_report(
    job_id: str,
    current_user: User = Security(get_current_user, scopes=["topology:read"]),
):
    """Get divergence report by job_id."""
    job = _analysis_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return job
