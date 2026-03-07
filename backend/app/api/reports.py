"""
Divergence Report API — T-025

Exposes the ReconciliationEngine findings as REST endpoints:

  POST /divergence/run              — trigger reconciliation
  GET  /divergence/summary          — summary stats from last run
  GET  /divergence/records          — paginated divergence records w/ filters
  GET  /divergence/report/{tid}     — full structured report (Roadmap V8 §1.4)
  GET  /divergence/score/{tid}      — detection accuracy vs pre-seeded manifest
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
    Trigger divergence reconciliation for a tenant.

    Compares CMDB (network_entities, topology_relationships) against ground
    truth reality (gt_network_entities, gt_entity_relationships) to detect:
    dark nodes, phantom nodes, identity mutations, dark attributes,
    dark edges, and phantom edges.

    Results are persisted and scored against the pre-seeded divergence_manifest.
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
    Returns counts by divergence type, domain breakdown, and CMDB accuracy metrics.
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

    cmdb_count = int(run["cmdb_entity_count"] or 0)
    gt_count = int(run["gt_entity_count"] or 0)
    confirmed_count = int(run["confirmed_entity_count"] or 0)
    cmdb_edges = int(run["cmdb_edge_count"] or 0)
    gt_edges = int(run["gt_edge_count"] or 0)
    confirmed_edges = int(run["confirmed_edge_count"] or 0)

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
        "cmdb_accuracy": {
            "entity_count_cmdb": cmdb_count,
            "entity_count_reality": gt_count,
            "confirmed_entities": confirmed_count,
            "dark_nodes": int(run["dark_nodes"] or 0),
            "phantom_nodes": int(run["phantom_nodes"] or 0),
            "entity_accuracy_pct": round(confirmed_count / max(gt_count, 1) * 100, 2),
            "edge_count_cmdb": cmdb_edges,
            "edge_count_reality": gt_edges,
            "confirmed_edges": confirmed_edges,
            "dark_edges": int(run["dark_edges"] or 0),
            "phantom_edges": int(run["phantom_edges"] or 0),
            "edge_accuracy_pct": round(confirmed_edges / max(gt_edges, 1) * 100, 2),
        },
        "detection_score": {
            "manifest_size": int(run["manifest_count"] or 0),
            "detected_in_manifest": int(run["detected_in_manifest"] or 0),
            "recall": run["recall_score"],
            "precision": run["precision_score"],
            "f1": run["f1_score"],
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
                   attribute_name, cmdb_value, ground_truth_value,
                   cmdb_external_id, gt_external_id, confidence, created_at
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
    Suitable for the Day-1 CIO delivery — shows what we found in their data.
    """
    # Reuse summary
    try:
        summary = await get_divergence_summary(tenant_id, db)
    except HTTPException:
        raise HTTPException(
            status_code=404,
            detail=f"No reconciliation run found for tenant '{tenant_id}'.",
        )

    # Top examples per type
    async def _top_examples(div_type: str, limit: int = 10) -> list[dict]:
        rows = await db.execute(
            text(
                """
                SELECT target_id, target_type, domain, description,
                       attribute_name, cmdb_value, ground_truth_value,
                       cmdb_external_id, gt_external_id, confidence
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
    identity_mutations = await _top_examples("identity_mutation")
    dark_attributes = await _top_examples("dark_attribute")
    dark_edges = await _top_examples("dark_edge")
    phantom_edges = await _top_examples("phantom_edge")

    acc = summary["cmdb_accuracy"]
    score = summary["detection_score"]
    by_type = summary["summary"]["by_type"]

    headline = (
        f"{by_type.get('dark_edge', 0):,} undocumented dependencies, "
        f"{by_type.get('dark_node', 0):,} unregistered entities, and "
        f"{by_type.get('identity_mutation', 0):,} identity mutations were found "
        f"by comparing your CMDB against operational reality. "
        f"Your CMDB is {acc['entity_accuracy_pct']:.1f}% accurate at the entity level "
        f"and {acc['edge_accuracy_pct']:.1f}% accurate at the relationship level."
    )

    return {
        "report_id": f"DIV-{tenant_id}-{summary['run_id'][:8]}",
        "tenant_id": tenant_id,
        "generated_at": summary["run_at"],
        "headline": headline,
        "summary": summary["summary"],
        "cmdb_accuracy": acc,
        "detection_score": score,
        "dark_nodes": dark_nodes,
        "phantom_nodes": phantom_nodes,
        "identity_mutations": identity_mutations,
        "dark_attributes": dark_attributes,
        "dark_edges": dark_edges,
        "phantom_edges": phantom_edges,
        "recommendation": (
            f"Your CMDB declares {acc['entity_count_cmdb']:,} entities and "
            f"{acc['edge_count_cmdb']:,} relationships. Operational reality shows "
            f"{acc['entity_count_reality']:,} entities and {acc['edge_count_reality']:,} "
            f"relationships. "
            f"{by_type.get('phantom_node', 0):,} phantom CIs are wasting licence fees. "
            f"{by_type.get('dark_node', 0):,} entities carry production traffic with "
            f"no change management oversight. Address identity mutations first — "
            f"{by_type.get('identity_mutation', 0):,} external ID discrepancies "
            f"are the most actionable quick wins."
        ),
    }


# ---------------------------------------------------------------------------
# GET /divergence/score/{tenant_id}
# ---------------------------------------------------------------------------


@router.get("/divergence/score/{tenant_id}")
async def get_detection_score(
    tenant_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """
    Detection accuracy of the reconciliation engine vs pre-seeded divergence_manifest.

    Breaks down precision, recall, and F1 per divergence type so Pedkai's
    detection quality can be tracked as the engine improves.
    """
    run_row = await db.execute(
        text(
            "SELECT * FROM reconciliation_runs WHERE tenant_id = :tid ORDER BY started_at DESC LIMIT 1"
        ),
        {"tid": tenant_id},
    )
    run = run_row.mappings().fetchone()
    if not run:
        raise HTTPException(status_code=404, detail="No reconciliation run found.")

    # Per-type scoring
    per_type = []
    for div_type in [
        "dark_node", "phantom_node", "identity_mutation",
        "dark_attribute", "dark_edge", "phantom_edge"
    ]:
        manifest_n = await db.execute(
            text(
                "SELECT COUNT(*) FROM divergence_manifest "
                "WHERE tenant_id = :tid AND divergence_type = :dt"
            ),
            {"tid": tenant_id, "dt": div_type},
        )
        manifest_count = manifest_n.scalar() or 0

        detected_n = await db.execute(
            text(
                "SELECT COUNT(*) FROM reconciliation_results "
                "WHERE tenant_id = :tid AND divergence_type = :dt"
            ),
            {"tid": tenant_id, "dt": div_type},
        )
        detected_count = detected_n.scalar() or 0

        hits_n = await db.execute(
            text(
                """
                SELECT COUNT(*)
                FROM divergence_manifest dm
                WHERE dm.tenant_id = :tid AND dm.divergence_type = :dt
                  AND EXISTS (
                      SELECT 1 FROM reconciliation_results rr
                      WHERE rr.tenant_id = :tid
                        AND rr.target_id = dm.target_id
                        AND rr.divergence_type = :dt
                  )
                """
            ),
            {"tid": tenant_id, "dt": div_type},
        )
        hits = hits_n.scalar() or 0

        recall = hits / max(manifest_count, 1)
        precision = hits / max(detected_count, 1)
        f1 = (
            2 * precision * recall / (precision + recall)
            if (precision + recall) > 0
            else 0.0
        )

        per_type.append(
            {
                "type": div_type,
                "manifest_count": manifest_count,
                "engine_detected": detected_count,
                "hits": hits,
                "recall": round(recall, 4),
                "precision": round(precision, 4),
                "f1": round(f1, 4),
            }
        )

    return {
        "run_id": run["run_id"],
        "tenant_id": tenant_id,
        "overall": {
            "manifest_count": int(run["manifest_count"] or 0),
            "detected_in_manifest": int(run["detected_in_manifest"] or 0),
            "recall": run["recall_score"],
            "precision": run["precision_score"],
            "f1": run["f1_score"],
        },
        "by_type": per_type,
        "note": (
            "The divergence_manifest contains pre-seeded ground truth labels from the "
            "Sleeping-Cell-KPI-Data generator. It is used to score Pedkai's detection "
            "quality, not to populate the report. Rows where engine_detected > manifest_count "
            "indicate the engine found additional divergences not covered by the seeded labels."
        ),
    }
