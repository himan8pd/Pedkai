"""
Abeyance Memory API Router.

Provides endpoints for fragment ingestion, retrieval, snap history,
accumulation graph queries, shadow topology, incident reconstruction,
and maintenance.

Uses the remediated service factory (create_abeyance_services) so all
services share ProvenanceLogger and RedisNotifier instances.

LLD ref: §5 (Fragment Model), §9 (Snap Engine), §10 (Accumulation Graph),
         §8 (Shadow Topology), §12 (Incident Reconstruction)
"""

from datetime import datetime, timezone
from typing import Any, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Security
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.database import get_db
from backend.app.core.logging import get_logger
from backend.app.core.security import INCIDENT_READ, User, get_current_user
from backend.app.models.abeyance_orm import (
    AbeyanceFragmentORM,
    AccumulationEdgeORM,
    FragmentEntityRefORM,
    SnapDecisionRecordORM,
)
from backend.app.schemas.abeyance import (
    AbeyanceFragmentResponse,
    AbeyanceFragmentSummary,
    AccumulationClusterResponse,
    AccumulationEdgeResponse,
    RawEvidence,
    SnapHistoryEntry,
)
from backend.app.services.abeyance import create_abeyance_services

logger = get_logger(__name__)
router = APIRouter()

# ---------------------------------------------------------------------------
# Service singleton (created once, shared across requests)
# ---------------------------------------------------------------------------
_services: dict | None = None


def _get_services() -> dict:
    """Lazy-initialise the abeyance service layer."""
    global _services
    if _services is None:
        _services = create_abeyance_services()
    return _services


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_tenant(current_user: User, query_tenant: str | None) -> str:
    tid = current_user.tenant_id or query_tenant
    if not tid:
        raise HTTPException(status_code=400, detail="tenant_id is required")
    return tid


def _primary_failure_mode(fragment: AbeyanceFragmentORM) -> Optional[str]:
    """Get the primary failure mode from a fragment's tags."""
    tags = fragment.failure_mode_tags or []
    if not tags or not isinstance(tags, list):
        return None
    best = max(tags, key=lambda t: t.get("confidence", 0) if isinstance(t, dict) else 0)
    return best.get("divergence_type") if isinstance(best, dict) else None


# ---------------------------------------------------------------------------
# POST /ingest
# ---------------------------------------------------------------------------

@router.post("/ingest", response_model=AbeyanceFragmentResponse, status_code=201)
async def ingest_evidence(
    payload: RawEvidence,
    db: AsyncSession = Depends(get_db),
    current_user: User = Security(get_current_user, scopes=[INCIDENT_READ]),
):
    """Submit raw evidence for enrichment and snap evaluation.

    The enrichment chain processes the evidence through:
    1. Entity resolution (LLM + regex fallback)
    2. Operational fingerprinting
    3. Failure mode classification
    4. Temporal-semantic embedding (with validity mask)

    Then the snap engine evaluates the enriched fragment against existing
    abeyance fragments for potential snaps.

    LLD ref: §6 (Enrichment Chain), §9 (Snap Engine)
    """
    tenant_id = _resolve_tenant(current_user, getattr(payload, "tenant_id", None))
    services = _get_services()
    enrichment = services["enrichment_v3"]
    snap_engine = services["snap_engine_v3"]
    accumulation = services["accumulation_graph"]

    # Enrich the raw evidence into a fragment
    fragment = await enrichment.enrich(
        session=db,
        tenant_id=tenant_id,
        raw_content=payload.content,
        source_type=payload.source_type.value,
        event_timestamp=payload.event_timestamp,
        source_ref=payload.source_ref,
        source_engineer_id=payload.source_engineer_id,
        explicit_entity_refs=payload.entity_refs or None,
        metadata=payload.metadata,
    )
    await db.flush()

    # Run snap evaluation
    try:
        snap_result = await snap_engine.evaluate(
            session=db,
            new_fragment=fragment,
            tenant_id=tenant_id,
        )
        logger.info(
            "Snap evaluation complete",
            extra={
                "fragment_id": str(fragment.id),
                "snaps": len(snap_result.get("snaps", [])),
                "near_misses": len(snap_result.get("near_misses", [])),
            },
        )
    except Exception as e:
        logger.warning("Snap evaluation failed (fragment stored): %s", e)

    # Check accumulation clusters (best-effort)
    try:
        await accumulation.detect_and_evaluate_clusters(
            session=db,
            tenant_id=tenant_id,
            trigger_fragment_id=fragment.id,
        )
    except Exception as e:
        logger.warning("Cluster detection failed: %s", e)

    return AbeyanceFragmentResponse.model_validate(fragment)


# ---------------------------------------------------------------------------
# GET /fragments
# ---------------------------------------------------------------------------

@router.get("/fragments", response_model=List[AbeyanceFragmentSummary])
async def list_fragments(
    tenant_id: Optional[str] = Query(None),
    snap_status: Optional[str] = Query(None),
    source_type: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Security(get_current_user, scopes=[INCIDENT_READ]),
):
    """List abeyance fragments with optional filters.

    LLD ref: §5 (Fragment Model)
    """
    tid = _resolve_tenant(current_user, tenant_id)

    query = (
        select(AbeyanceFragmentORM)
        .where(AbeyanceFragmentORM.tenant_id == tid)
    )

    if snap_status:
        query = query.where(AbeyanceFragmentORM.snap_status == snap_status)
    if source_type:
        query = query.where(AbeyanceFragmentORM.source_type == source_type)

    query = (
        query.order_by(AbeyanceFragmentORM.created_at.desc())
        .offset(offset)
        .limit(limit)
    )

    result = await db.execute(query)
    fragments = result.scalars().all()
    return [AbeyanceFragmentSummary.model_validate(f) for f in fragments]


# ---------------------------------------------------------------------------
# GET /fragments/{fragment_id}
# ---------------------------------------------------------------------------

@router.get("/fragments/{fragment_id}", response_model=AbeyanceFragmentResponse)
async def get_fragment(
    fragment_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Security(get_current_user, scopes=[INCIDENT_READ]),
):
    """Get a single fragment with full enrichment details.

    LLD ref: §5 (Fragment Model)
    """
    result = await db.execute(
        select(AbeyanceFragmentORM).where(AbeyanceFragmentORM.id == fragment_id)
    )
    fragment = result.scalars().first()
    if not fragment:
        raise HTTPException(status_code=404, detail=f"Fragment {fragment_id} not found")

    # Tenant check (INV-7)
    if current_user.tenant_id and fragment.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail=f"Fragment {fragment_id} not found")

    return AbeyanceFragmentResponse.model_validate(fragment)


# ---------------------------------------------------------------------------
# GET /snap-history
# ---------------------------------------------------------------------------

@router.get("/snap-history", response_model=List[SnapHistoryEntry])
async def get_snap_history(
    tenant_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Security(get_current_user, scopes=[INCIDENT_READ]),
):
    """Query successful snaps with full scoring provenance.

    Returns snap decision records ordered by most recent evaluation.

    LLD ref: §9 (Snap Engine), INV-10 (provenance)
    """
    tid = _resolve_tenant(current_user, tenant_id)

    # Use snap_decision_record for provenance-backed history
    result = await db.execute(
        select(SnapDecisionRecordORM)
        .where(
            SnapDecisionRecordORM.tenant_id == tid,
            SnapDecisionRecordORM.decision.in_(["SNAP", "NEAR_MISS"]),
        )
        .order_by(SnapDecisionRecordORM.evaluated_at.desc())
        .offset(offset)
        .limit(limit)
    )
    records = result.scalars().all()

    snaps = []
    for r in records:
        snaps.append(SnapHistoryEntry(
            fragment_id=r.new_fragment_id,
            snapped_to=r.candidate_fragment_id,
            snap_score=r.final_score,
            failure_mode=r.failure_mode_profile,
            snapped_at=r.evaluated_at,
            score_semantic=r.score_semantic,
            score_topological=r.score_topological,
            score_temporal=r.score_temporal,
            score_operational=r.score_operational,
            score_entity_overlap=r.score_entity_overlap,
            threshold_applied=r.threshold_applied,
            decision=r.decision,
        ))
    return snaps


# ---------------------------------------------------------------------------
# GET /accumulation-graph
# ---------------------------------------------------------------------------

@router.get("/accumulation-graph", response_model=List[AccumulationEdgeResponse])
async def get_accumulation_edges(
    tenant_id: Optional[str] = Query(None),
    fragment_id: Optional[UUID] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    current_user: User = Security(get_current_user, scopes=[INCIDENT_READ]),
):
    """Query accumulation graph edges.

    LLD ref: §10 (Accumulation Graph)
    """
    tid = _resolve_tenant(current_user, tenant_id)

    query = select(AccumulationEdgeORM).where(
        AccumulationEdgeORM.tenant_id == tid
    )

    if fragment_id:
        query = query.where(
            (AccumulationEdgeORM.fragment_a_id == fragment_id)
            | (AccumulationEdgeORM.fragment_b_id == fragment_id)
        )

    result = await db.execute(query.limit(limit))
    edges = result.scalars().all()
    return [AccumulationEdgeResponse.model_validate(e) for e in edges]


# ---------------------------------------------------------------------------
# GET /accumulation-graph/clusters
# ---------------------------------------------------------------------------

@router.get("/accumulation-graph/clusters", response_model=List[AccumulationClusterResponse])
async def get_accumulation_clusters(
    tenant_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Security(get_current_user, scopes=[INCIDENT_READ]),
):
    """List current accumulation clusters.

    Uses LME-scored union-find detection (remediated per Audit §4.1, §5.3).

    LLD ref: §10 (Accumulation Graph)
    """
    tid = _resolve_tenant(current_user, tenant_id)
    services = _get_services()

    clusters = await services["accumulation_graph"].detect_and_evaluate_clusters(
        session=db,
        tenant_id=tid,
    )
    return [
        AccumulationClusterResponse(
            cluster_id=c.get("cluster_id", ""),
            member_fragment_ids=c.get("member_ids", []),
            member_count=c.get("member_count", 0),
            cluster_score=c.get("adjusted_score", c.get("cluster_score", 0.0)),
            strongest_failure_mode=c.get("strongest_failure_mode"),
        )
        for c in clusters
    ]


# ---------------------------------------------------------------------------
# GET /reconstruction
# ---------------------------------------------------------------------------

@router.get("/reconstruction")
async def reconstruct_incident(
    tenant_id: Optional[str] = Query(None),
    hypothesis_id: Optional[UUID] = Query(None),
    entity_identifier: Optional[str] = Query(None),
    time_start: Optional[datetime] = Query(None),
    time_end: Optional[datetime] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Security(get_current_user, scopes=[INCIDENT_READ]),
):
    """Reconstruct incident timeline from provenance data.

    LLD ref: §12 (Incident Reconstruction)
    """
    tid = _resolve_tenant(current_user, tenant_id)
    services = _get_services()

    return await services["incident_reconstruction"].reconstruct(
        session=db,
        tenant_id=tid,
        hypothesis_id=hypothesis_id,
        entity_identifier=entity_identifier,
        time_start=time_start,
        time_end=time_end,
    )


# ---------------------------------------------------------------------------
# POST /maintenance
# ---------------------------------------------------------------------------

@router.post("/maintenance")
async def run_maintenance(
    tenant_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Security(get_current_user, scopes=[INCIDENT_READ]),
):
    """Trigger full maintenance pass (decay, prune, expire, orphan cleanup).

    LLD ref: §11 (Decay Engine), §5 (Maintenance)
    """
    tid = _resolve_tenant(current_user, tenant_id)
    services = _get_services()

    return await services["maintenance"].run_full_maintenance(
        session=db,
        tenant_id=tid,
    )


# ---------------------------------------------------------------------------
# v3 Discovery Loop Endpoints
# ---------------------------------------------------------------------------

@router.post("/ingest/v3", status_code=201)
async def ingest_evidence_v3(
    payload: RawEvidence,
    db: AsyncSession = Depends(get_db),
    current_user: User = Security(get_current_user, scopes=[INCIDENT_READ]),
):
    """Submit raw evidence through the v3 six-stage discovery loop.

    Processes through: Ingest → Enrich → Score → Detect → Generate → Learn → Adapt.
    Uses T-VEC/TSLAM local models, mask-aware scoring, and all 14 discovery mechanisms.

    LLD v3.0 ref: §12 (Discovery Loop)
    """
    tenant_id = _resolve_tenant(current_user, getattr(payload, "tenant_id", None))
    services = _get_services()
    discovery_loop = services.get("discovery_loop")
    if discovery_loop is None:
        raise HTTPException(status_code=503, detail="Discovery loop not available")

    result = await discovery_loop.process_event(
        session=db,
        tenant_id=tenant_id,
        raw_content=payload.content,
        source_type=payload.source_type.value,
        event_timestamp=payload.event_timestamp,
        source_ref=payload.source_ref,
        source_engineer_id=payload.source_engineer_id,
        explicit_entity_refs=payload.entity_refs or None,
    )

    await db.commit()
    return result


@router.post("/discovery/background")
async def run_discovery_background(
    tenant_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Security(get_current_user, scopes=[INCIDENT_READ]),
):
    """Trigger periodic background discovery jobs.

    Runs ignorance mapping, bridge detection, pattern conflict scan,
    causal analysis, pattern compression, counterfactual simulation,
    evolutionary patterns, and hypothesis expiration.

    LLD v3.0 ref: §12.2 (Background Jobs)
    """
    tid = _resolve_tenant(current_user, tenant_id)
    services = _get_services()
    discovery_loop = services.get("discovery_loop")
    if discovery_loop is None:
        raise HTTPException(status_code=503, detail="Discovery loop not available")

    result = await discovery_loop.run_background_jobs(session=db, tenant_id=tid)
    await db.commit()
    return {"tenant_id": tid, "results": result}


@router.get("/discovery/status")
async def discovery_status(
    tenant_id: Optional[str] = Query(None),
    current_user: User = Security(get_current_user, scopes=[INCIDENT_READ]),
):
    """Get health status of v3 discovery mechanisms.

    Returns model loading status for T-VEC and TSLAM, plus availability
    of each discovery mechanism.
    """
    tid = _resolve_tenant(current_user, tenant_id)
    services = _get_services()

    tvec_status = {}
    tslam_status = {}
    tvec = services.get("tvec")
    tslam = services.get("tslam")
    if tvec:
        tvec_status = await tvec.health()
    if tslam:
        tslam_status = await tslam.health()

    mechanism_names = [
        "surprise_engine", "ignorance_mapper", "negative_evidence",
        "bridge_detector", "outcome_calibration", "pattern_conflict",
        "temporal_sequence", "hypothesis_generator", "expectation_violation",
        "causal_direction", "pattern_compressor", "counterfactual_sim",
        "meta_memory", "evolutionary_patterns",
    ]
    mechanisms = {}
    for name in mechanism_names:
        svc = services.get(name)
        mechanisms[name] = "available" if svc is not None else "unavailable"

    return {
        "tenant_id": tid,
        "tvec_status": tvec_status,
        "tslam_status": tslam_status,
        "mechanisms": mechanisms,
        "discovery_loop": "available" if services.get("discovery_loop") else "unavailable",
    }


# ---------------------------------------------------------------------------
# POST /explain — TSLAM-backed multi-perspective explanation of a snap chain
# ---------------------------------------------------------------------------

@router.post("/explain")
async def explain_snap_chain(
    entity_identifier: str = Query(..., description="Shared entity to anchor the chain"),
    time_start: Optional[datetime] = Query(None),
    time_end: Optional[datetime] = Query(None),
    tenant_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Security(get_current_user, scopes=[INCIDENT_READ]),
):
    """Generate 3 perspective explanations of a snap chain using TSLAM.

    Returns telecom, technical, and executive summaries derived from
    fragments connected to the given entity within the time window.

    LLD v3.0 ref: §12 (Incident Reconstruction), §2.3 (TSLAM)
    """
    tid = _resolve_tenant(current_user, tenant_id)
    services = _get_services()
    tslam = services.get("tslam")
    if tslam is None:
        raise HTTPException(status_code=503, detail="TSLAM service not available")

    # Gather fragments touching this entity
    entity_stmt = (
        select(FragmentEntityRefORM.fragment_id)
        .where(
            FragmentEntityRefORM.tenant_id == tid,
            FragmentEntityRefORM.entity_identifier == entity_identifier,
        )
        .distinct()
    )
    entity_result = await db.execute(entity_stmt)
    fragment_ids = {row[0] for row in entity_result.fetchall()}

    if not fragment_ids:
        raise HTTPException(status_code=404, detail=f"No fragments reference entity {entity_identifier}")

    stmt = select(AbeyanceFragmentORM).where(
        AbeyanceFragmentORM.id.in_(fragment_ids),
        AbeyanceFragmentORM.tenant_id == tid,
    )
    if time_start:
        stmt = stmt.where(AbeyanceFragmentORM.event_timestamp >= time_start)
    if time_end:
        stmt = stmt.where(AbeyanceFragmentORM.event_timestamp <= time_end)
    stmt = stmt.order_by(AbeyanceFragmentORM.event_timestamp.asc())

    result = await db.execute(stmt)
    fragments = list(result.scalars().all())
    if not fragments:
        raise HTTPException(status_code=404, detail="No fragments in time window")

    # Build combined context from all fragments
    chain_context = []
    for frag in fragments:
        entities = [e["identifier"] for e in (frag.extracted_entities or [])]
        chain_context.append(
            f"[{frag.source_type}] {frag.event_timestamp.isoformat()} | "
            f"entities: {', '.join(entities)} | "
            f"status: {frag.snap_status} | "
            f"{frag.raw_content}"
        )
    combined = "\n\n".join(chain_context)

    # Snap scores context
    snap_stmt = select(SnapDecisionRecordORM).where(
        SnapDecisionRecordORM.tenant_id == tid,
        SnapDecisionRecordORM.new_fragment_id.in_([f.id for f in fragments]),
    ).order_by(SnapDecisionRecordORM.evaluated_at.asc())
    snap_result = await db.execute(snap_stmt)
    snap_records = list(snap_result.scalars().all())

    snap_summary = []
    seen_pairs = set()
    for sr in snap_records:
        pair = tuple(sorted([str(sr.new_fragment_id), str(sr.candidate_fragment_id)]))
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        snap_summary.append(
            f"  {sr.failure_mode_profile}: score={sr.final_score:.3f} "
            f"(semantic={sr.score_semantic or 0:.3f}, "
            f"topological={sr.score_topological or 0:.3f}, "
            f"entity_overlap={sr.score_entity_overlap or 0:.3f})"
        )

    snap_text = "\n".join(snap_summary[:10]) if snap_summary else "No snap records available."

    # Generate 3 perspectives
    perspectives = {}
    prompts = {
        "telecom": (
            f"You are a senior telecom network engineer. Analyze this chain of "
            f"correlated network events and explain what happened from a network "
            f"operations perspective. Focus on the physical infrastructure, "
            f"protocol behavior, and service impact.\n\n"
            f"Events:\n{combined}\n\n"
            f"Correlation scores:\n{snap_text}\n\n"
            f"Provide a concise explanation (3-5 sentences) of the root cause "
            f"and how these events are connected."
        ),
        "technical": (
            f"You are a systems reliability engineer. Analyze this chain of "
            f"correlated monitoring events and explain the technical detection "
            f"and correlation mechanism. Focus on how the system identified "
            f"these events as related despite coming from different sources.\n\n"
            f"Events:\n{combined}\n\n"
            f"Correlation scores:\n{snap_text}\n\n"
            f"Provide a concise technical explanation (3-5 sentences) of "
            f"the correlation methodology and confidence levels."
        ),
        "executive": (
            f"You are a VP of Network Operations. Summarize this correlated "
            f"incident chain for a C-level audience. Focus on business impact, "
            f"detection speed, and resolution timeline.\n\n"
            f"Events:\n{combined}\n\n"
            f"Provide a concise executive summary (2-3 sentences) covering "
            f"impact, detection advantage, and outcome."
        ),
    }

    for perspective, prompt in prompts.items():
        raw = await tslam.generate(prompt, max_tokens=256, temperature=0.3)
        perspectives[perspective] = raw or f"[TSLAM generation unavailable for {perspective}]"

    return {
        "entity": entity_identifier,
        "fragment_count": len(fragments),
        "fragments": [
            {
                "id": str(f.id),
                "source_type": f.source_type,
                "source_ref": f.source_ref,
                "event_timestamp": f.event_timestamp.isoformat(),
                "snap_status": f.snap_status,
            }
            for f in fragments
        ],
        "snap_decisions": len(snap_records),
        "explanations": perspectives,
    }

