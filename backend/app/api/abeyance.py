"""
Abeyance Memory API Router.

Provides endpoints for fragment ingestion, retrieval, snap history,
and accumulation graph queries.

LLD ref: §5 (Fragment Model), §9 (Snap Engine), §10 (Accumulation Graph)
"""

from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Security
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.database import async_session_maker, get_db
from backend.app.core.logging import get_logger
from backend.app.core.security import INCIDENT_READ, User, get_current_user
from backend.app.models.abeyance_orm import (
    AbeyanceFragmentORM,
    AccumulationEdgeORM,
    FragmentEntityRefORM,
)
from backend.app.schemas.abeyance import (
    AbeyanceFragmentResponse,
    AbeyanceFragmentSummary,
    AccumulationClusterResponse,
    AccumulationEdgeResponse,
    RawEvidence,
    SnapHistoryEntry,
    SnapStatus,
)

logger = get_logger(__name__)
router = APIRouter()


@router.post("/ingest", response_model=AbeyanceFragmentResponse, status_code=201)
async def ingest_evidence(
    payload: RawEvidence,
    db: AsyncSession = Depends(get_db),
    current_user: User = Security(get_current_user, scopes=[INCIDENT_READ]),
):
    """Submit raw evidence for enrichment and snap evaluation.

    The enrichment chain processes the evidence through:
    1. Entity resolution
    2. Topology expansion
    3. Operational fingerprinting
    4. Failure mode classification + embedding generation

    Then the snap engine evaluates the enriched fragment against existing
    abeyance fragments for potential snaps.

    LLD ref: §6 (Enrichment Chain), §9 (Snap Engine)
    """
    from backend.app.services.abeyance.enrichment_chain import EnrichmentChain
    from backend.app.services.abeyance.shadow_topology import get_shadow_topology
    from backend.app.services.abeyance.snap_engine import SnapEngine
    from backend.app.services.embedding_service import get_embedding_service

    tenant_id = current_user.tenant_id or payload.tenant_id
    if not tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id is required")

    # Build enrichment chain
    embedding_svc = get_embedding_service()
    shadow_topo = get_shadow_topology(async_session_maker)
    chain = EnrichmentChain(
        embedding_service=embedding_svc,
        shadow_topology=shadow_topo,
        session_factory=async_session_maker,
    )

    # Enrich the raw evidence into a fragment
    fragment = await chain.enrich(payload, tenant_id, session=db)
    db.add(fragment)
    await db.flush()

    # Run snap evaluation
    try:
        from backend.app.services.event_bus import EventBus
        event_bus = EventBus.get_instance()
        snap_engine = SnapEngine(
            session_factory=async_session_maker,
            shadow_topology=shadow_topo,
            event_bus=event_bus,
        )
        snap_result = await snap_engine.evaluate(fragment, tenant_id, session=db)
        logger.info(
            f"Snap evaluation: fragment={fragment.id}, "
            f"snaps={len(snap_result.snaps)}, "
            f"near_misses={len(snap_result.near_misses)}"
        )
    except Exception as e:
        logger.warning(f"Snap evaluation failed (fragment stored): {e}")

    return AbeyanceFragmentResponse.model_validate(fragment)


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
    tid = current_user.tenant_id or tenant_id
    if not tid:
        raise HTTPException(status_code=400, detail="tenant_id is required")

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

    # Tenant check
    if current_user.tenant_id and fragment.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail=f"Fragment {fragment_id} not found")

    return AbeyanceFragmentResponse.model_validate(fragment)


@router.get("/snap-history", response_model=List[SnapHistoryEntry])
async def get_snap_history(
    tenant_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Security(get_current_user, scopes=[INCIDENT_READ]),
):
    """Query successful snaps and near-misses.

    Returns fragments that have been snapped to hypotheses, ordered by
    most recent snap first.

    LLD ref: §9 (Snap Engine)
    """
    tid = current_user.tenant_id or tenant_id
    if not tid:
        raise HTTPException(status_code=400, detail="tenant_id is required")

    result = await db.execute(
        select(AbeyanceFragmentORM)
        .where(
            AbeyanceFragmentORM.tenant_id == tid,
            AbeyanceFragmentORM.snap_status == SnapStatus.SNAPPED.value,
        )
        .order_by(AbeyanceFragmentORM.updated_at.desc())
        .offset(offset)
        .limit(limit)
    )
    fragments = result.scalars().all()

    snaps = []
    for f in fragments:
        snaps.append(SnapHistoryEntry(
            fragment_id=f.id,
            snapped_to=f.snapped_hypothesis_id,
            snap_score=0.0,
            failure_mode=_primary_failure_mode(f),
            snapped_at=f.updated_at,
        ))
    return snaps


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
    tid = current_user.tenant_id or tenant_id
    if not tid:
        raise HTTPException(status_code=400, detail="tenant_id is required")

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


@router.get("/accumulation-graph/clusters", response_model=List[AccumulationClusterResponse])
async def get_accumulation_clusters(
    tenant_id: Optional[str] = Query(None),
    min_members: int = Query(3, ge=2),
    db: AsyncSession = Depends(get_db),
    current_user: User = Security(get_current_user, scopes=[INCIDENT_READ]),
):
    """List current accumulation clusters above the size threshold.

    Uses connected component detection on the accumulation graph.

    LLD ref: §10 (Accumulation Graph)
    """
    from backend.app.services.abeyance.accumulation_graph import AccumulationGraphService

    tid = current_user.tenant_id or tenant_id
    if not tid:
        raise HTTPException(status_code=400, detail="tenant_id is required")

    service = AccumulationGraphService(async_session_maker)
    clusters = await service.detect_clusters(tid, min_members=min_members, session=db)
    return clusters


def _primary_failure_mode(fragment: AbeyanceFragmentORM) -> Optional[str]:
    """Get the primary failure mode from a fragment's tags."""
    tags = fragment.failure_mode_tags or []
    if not tags or not isinstance(tags, list):
        return None
    best = max(tags, key=lambda t: t.get("confidence", 0) if isinstance(t, dict) else 0)
    return best.get("divergence_type") if isinstance(best, dict) else None
