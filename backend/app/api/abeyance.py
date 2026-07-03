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

import asyncio

from datetime import datetime, timezone
from typing import Any, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Security
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.database import async_session_maker, get_db
from backend.app.core.logging import get_logger
from backend.app.core.security import INCIDENT_READ, User, get_current_user
from backend.app.models.abeyance_orm import (
    AbeyanceFragmentORM,
    AccumulationEdgeORM,
    FragmentEntityRefORM,
    SnapDecisionRecordORM,
)
from backend.app.models.reconciliation_result_orm import ReconciliationResultORM
from backend.app.schemas.abeyance import (
    AbeyanceFragmentResponse,
    AbeyanceFragmentSummary,
    AccumulationClusterResponse,
    AccumulationEdgeResponse,
    EntityDivergenceFlag,
    EntityEvidenceItem,
    EntityInvestigationResponse,
    EntitySnapCard,
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

    # Build combined context from all fragments (truncate content for ARM speed)
    chain_context = []
    for frag in fragments:
        entities = [e["identifier"] for e in (frag.extracted_entities or [])]
        content = (frag.raw_content or "")[:300]
        chain_context.append(
            f"[{frag.source_type}] {frag.event_timestamp.isoformat()} | "
            f"entities: {', '.join(entities)} | "
            f"status: {frag.snap_status} | "
            f"{content}"
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

    async def _gen(name: str, prompt: str) -> tuple[str, str]:
        raw = await tslam.generate(prompt, max_tokens=128, temperature=0.3)
        return name, raw or f"[TSLAM generation unavailable for {name}]"

    results = await asyncio.gather(
        *[_gen(name, prompt) for name, prompt in prompts.items()]
    )
    for name, text in results:
        perspectives[name] = text

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



# ---------------------------------------------------------------------------
# GET /entity/{entity_identifier}/investigation
# Unified Abeyance + T-VEC investigation view for a single entity.
# ---------------------------------------------------------------------------

# In-flight lazy-embedding tasks keyed by "tenant::entity" so UI polling does
# not spawn duplicate background jobs.
_embedding_tasks: dict[str, asyncio.Task] = {}

SEMANTIC_DIM = TOPOLOGICAL_DIM = OPERATIONAL_DIM = 1536

_DIM_WEIGHT_KEY = {
    "semantic": "w_sem", "topological": "w_topo", "temporal": "w_temp",
    "operational": "w_oper", "entity_overlap": "w_ent",
}
_DIM_LABEL = {
    "semantic": "fault/semantic similarity", "topological": "shared topology",
    "temporal": "time proximity", "operational": "operational fingerprint",
    "entity_overlap": "shared entities",
}

# Map a reconciliation divergence type to the snap-engine weight profile, so an
# entity's snaps are labelled coherently with its actual divergence instead of an
# arbitrary highest-scoring profile (the profiles are scoring weights, not
# per-snap diagnoses; unclassified telemetry fragments get scored under all 5).
_DIV_TO_PROFILE = {
    "dark_node": "DARK_NODE",
    "dark_edge": "DARK_EDGE",
    "dark_attribute": "DARK_ATTRIBUTE",
    "identity_mutation": "IDENTITY_MUTATION",
    "phantom_node": "PHANTOM_CI",
}


def _snippet(raw: Optional[str], n: int = 160) -> str:
    if not raw:
        return ""
    s = raw.strip().replace("\n", " ")
    return s[:n] + ("…" if len(s) > n else "")


def _build_semantic_text(raw: Optional[str], entities: list) -> Optional[str]:
    if not raw:
        return None
    ent = ", ".join(e.get("identifier", "") for e in (entities or [])[:20])
    return f"{raw[:1000]} Entities: {ent}"


def _build_topo_text(entities: list, neighbourhood: dict) -> Optional[str]:
    if not entities:
        return None
    parts = [f"{e.get('identifier', '?')} ({e.get('domain', 'unknown')})" for e in entities[:20]]
    return f"Network topology context: {', '.join(parts)}"


def _build_operational_text(failure_modes: list, fingerprint: dict) -> Optional[str]:
    if not failure_modes:
        return None
    parts = []
    for fm in failure_modes[:5]:
        if isinstance(fm, dict):
            parts.append(f"{fm.get('divergence_type', 'unknown')}: {fm.get('rationale', '')}")
    time_bucket = (fingerprint or {}).get("traffic_cycle", {}).get("time_bucket", "unknown")
    parts.append(f"Traffic: {time_bucket}")
    return f"Operational context: {'; '.join(parts)}"


def _pad_or_trim(vec: list, target_dim: int) -> list:
    if len(vec) < target_dim:
        return vec + [0.0] * (target_dim - len(vec))
    return vec[:target_dim]


def _derive_why(dims: dict, weights_used: Optional[dict]) -> tuple[Optional[str], str]:
    """Turn per-dimension scores into a dominant driver + plain-English reason.

    Ranks dimensions by contribution (weight x score) so entity_overlap (often
    1.0) does not automatically dominate. Deterministic, no LLM. The reason is
    stated in terms of what links the evidence — no internal scoring-profile
    jargon.
    """
    contrib: dict = {}
    for dim, key in _DIM_WEIGHT_KEY.items():
        score = dims.get(dim)
        weight = (weights_used or {}).get(key)
        if score is not None and weight:
            contrib[dim] = float(weight) * float(score)
    if not contrib:
        return None, "Linked by shared entity"
    ranked = sorted(contrib, key=contrib.get, reverse=True)
    dominant = ranked[0]
    parts = [f"{_DIM_LABEL[d]} ({dims[d]:.2f})" for d in ranked[:2] if dims.get(d) is not None]
    return dominant, f"Linked by {', '.join(parts)}"


async def _entity_fragment_ids(session: AsyncSession, tenant_id: str, entity_identifier: str) -> list:
    result = await session.execute(
        select(FragmentEntityRefORM.fragment_id)
        .where(
            FragmentEntityRefORM.tenant_id == tenant_id,
            FragmentEntityRefORM.entity_identifier == entity_identifier,
        )
        .distinct()
    )
    return [row[0] for row in result.fetchall()]


async def _embed_entity_fragments(tenant_id: str, entity_identifier: str) -> None:
    """Background: compute T-VEC embeddings for this entity's un-embedded
    fragments, reusing the warm in-process model. Persists per fragment."""
    from sqlalchemy import update

    tvec = _get_services()["tvec"]
    try:
        async with async_session_maker() as session:
            ids = await _entity_fragment_ids(session, tenant_id, entity_identifier)
            if not ids:
                return
            res = await session.execute(
                select(AbeyanceFragmentORM).where(
                    AbeyanceFragmentORM.id.in_(ids),
                    AbeyanceFragmentORM.tenant_id == tenant_id,
                    AbeyanceFragmentORM.mask_semantic.is_(False),
                )
            )
            frags = list(res.scalars().all())
        for frag in frags:
            plan = [
                (_build_semantic_text(frag.raw_content or "", frag.extracted_entities or []), "semantic", SEMANTIC_DIM),
                (_build_topo_text(frag.extracted_entities or [], frag.topological_neighbourhood or {}), "topological", TOPOLOGICAL_DIM),
                (_build_operational_text(frag.failure_mode_tags or [], frag.operational_fingerprint or {}), "operational", OPERATIONAL_DIM),
            ]
            plan = [(t, c, d) for (t, c, d) in plan if t]
            if not plan:
                continue
            vecs = await tvec.embed_batch([t for t, _, _ in plan])
            patch: dict = {}
            for (_, col, dim), v in zip(plan, vecs):
                if v is None:
                    continue
                padded = _pad_or_trim(v, dim)
                if any(x != 0.0 for x in padded):
                    patch[f"emb_{col}"] = padded
                    patch[f"mask_{col}"] = True
            if not patch:
                continue
            async with async_session_maker() as session:
                await session.execute(
                    update(AbeyanceFragmentORM)
                    .where(AbeyanceFragmentORM.id == frag.id)
                    .values(**patch)
                )
                await session.commit()
    except Exception:
        logger.warning("Lazy embedding failed for entity %s", entity_identifier, exc_info=True)
    finally:
        _embedding_tasks.pop(f"{tenant_id}::{entity_identifier}", None)


@router.get("/entity/{entity_identifier}/investigation", response_model=EntityInvestigationResponse)
async def investigate_entity(
    entity_identifier: str,
    tenant_id: Optional[str] = Query(None),
    embed: bool = Query(True, description="Lazily compute missing T-VEC embeddings"),
    snap_limit: int = Query(30, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Security(get_current_user, scopes=[INCIDENT_READ]),
):
    """Unified investigation view for a single entity: evidence timeline,
    snaps with per-dimension 'why', and reconciliation divergence flags.

    Lazily embeds the entity's fragments (reusing the warm T-VEC model) so the
    semantic dimension becomes available without a full-corpus backfill.
    """
    tid = _resolve_tenant(current_user, tenant_id)

    frag_ids = await _entity_fragment_ids(db, tid, entity_identifier)

    # Reconciliation divergence flags — independent of abeyance fragments: a
    # Dark/Phantom entity may carry divergence records but reference no fragments.
    dres = await db.execute(
        select(ReconciliationResultORM)
        .where(
            ReconciliationResultORM.tenant_id == tid,
            ReconciliationResultORM.target_id == entity_identifier,
        )
        .order_by(ReconciliationResultORM.confidence.desc())
    )
    divergence = [
        EntityDivergenceFlag(
            divergence_type=d.divergence_type,
            confidence=d.confidence or 0.0,
            description=d.description,
            attribute_name=d.attribute_name,
            cmdb_value=d.cmdb_value,
            observed_value=d.observed_value,
        )
        for d in dres.scalars().all()
    ]

    if not frag_ids and not divergence:
        raise HTTPException(
            status_code=404,
            detail=f"No abeyance evidence or divergence records for entity {entity_identifier}",
        )
    frag_id_set = set(frag_ids)

    res = await db.execute(
        select(AbeyanceFragmentORM)
        .where(
            AbeyanceFragmentORM.id.in_(frag_ids),
            AbeyanceFragmentORM.tenant_id == tid,
        )
        .order_by(AbeyanceFragmentORM.event_timestamp.desc())
    )
    fragments = list(res.scalars().all())
    frag_by_id = {f.id: f for f in fragments}
    embedded_count = sum(1 for f in fragments if f.mask_semantic)

    evidence = [
        EntityEvidenceItem(
            fragment_id=f.id,
            source_type=f.source_type,
            event_timestamp=f.event_timestamp,
            snap_status=f.snap_status,
            current_decay_score=f.current_decay_score,
            snippet=_snippet(f.raw_content),
            primary_failure_mode=_primary_failure_mode(f),
            embedded=bool(f.mask_semantic),
        )
        for f in fragments
    ]

    # Lazy embedding trigger
    key = f"{tid}::{entity_identifier}"
    embedding_status = "ready"
    needs_embedding = any((f.raw_content and not f.mask_semantic) for f in fragments)
    existing = _embedding_tasks.get(key)
    if embed and needs_embedding:
        if existing is None or existing.done():
            _embedding_tasks[key] = asyncio.create_task(
                _embed_entity_fragments(tid, entity_identifier)
            )
        embedding_status = "computing"
    elif existing is not None and not existing.done():
        embedding_status = "computing"

    # Snaps involving the entity (dedup to best profile per fragment pair)
    res = await db.execute(
        select(SnapDecisionRecordORM)
        .where(
            SnapDecisionRecordORM.tenant_id == tid,
            or_(
                SnapDecisionRecordORM.new_fragment_id.in_(frag_ids),
                SnapDecisionRecordORM.candidate_fragment_id.in_(frag_ids),
            ),
        )
        .order_by(SnapDecisionRecordORM.final_score.desc())
    )
    best_by_pair: dict = {}
    for r in res.scalars().all():
        pair = frozenset((r.new_fragment_id, r.candidate_fragment_id))
        if pair not in best_by_pair:  # sorted desc -> first seen is best
            best_by_pair[pair] = r
    snap_records = list(best_by_pair.values())[:snap_limit]

    # Resolve pairs + load matched fragments (full rows, incl. embeddings)
    pair_list = []       # (record, ours_id, other_id)
    involved: set = set()
    for r in snap_records:
        ours = r.new_fragment_id if r.new_fragment_id in frag_id_set else r.candidate_fragment_id
        other = r.candidate_fragment_id if ours == r.new_fragment_id else r.new_fragment_id
        pair_list.append((r, ours, other))
        involved.update((ours, other))
    missing = involved - set(frag_by_id.keys())
    if missing:
        mres = await db.execute(
            select(AbeyanceFragmentORM).where(
                AbeyanceFragmentORM.id.in_(missing),
                AbeyanceFragmentORM.tenant_id == tid,
            )
        )
        for mf in mres.scalars().all():
            frag_by_id[mf.id] = mf

    # Entity sets for every involved fragment (needed for live re-scoring)
    ent_map: dict = {fid: set() for fid in involved}
    if involved:
        eres = await db.execute(
            select(FragmentEntityRefORM.fragment_id, FragmentEntityRefORM.entity_identifier)
            .where(
                FragmentEntityRefORM.tenant_id == tid,
                FragmentEntityRefORM.fragment_id.in_(involved),
            )
        )
        for fid, eid in eres.fetchall():
            ent_map.setdefault(fid, set()).add(eid)

    snap_engine = _get_services()["snap_engine_v3"]

    # Profiles that match this entity's actual divergence(s) — snaps prefer these
    # so labels stay coherent (a dark_node's snaps read as DARK_NODE, not a
    # random highest-scoring profile like PHANTOM_CI/IDENTITY_MUTATION).
    preferred_profiles = {
        _DIV_TO_PROFILE[d.divergence_type]
        for d in divergence
        if d.divergence_type in _DIV_TO_PROFILE
    }

    snaps = []
    for r, ours, other in pair_list:
        of = frag_by_id.get(ours)
        mf = frag_by_id.get(other)
        rescored = False
        dims = {
            "semantic": r.score_semantic,
            "topological": r.score_topological,
            "temporal": r.score_temporal,
            "operational": r.score_operational,
            "entity_overlap": r.score_entity_overlap,
        }
        weights = r.weights_used
        fmode = r.failure_mode_profile
        final = r.final_score
        # Re-score live against current embeddings when both sides are embedded,
        # so the "why" reflects T-VEC rather than the frozen historical record.
        if of is not None and mf is not None and of.emb_semantic is not None and mf.emb_semantic is not None:
            try:
                scored = snap_engine._score_pair(
                    of, mf, ent_map.get(ours, set()), ent_map.get(other, set()),
                )
                if scored:
                    pref = [s for s in scored if s["failure_mode_profile"] in preferred_profiles]
                    chosen = max(pref or scored, key=lambda s: s["final_score"])
                else:
                    chosen = None
                if chosen:
                    dims = {
                        "semantic": chosen["score_semantic"],
                        "topological": chosen["score_topological"],
                        "temporal": chosen["score_temporal"],
                        "operational": chosen["score_operational"],
                        "entity_overlap": chosen["score_entity_overlap"],
                    }
                    weights = chosen.get("weights_used")
                    fmode = chosen["failure_mode_profile"]
                    final = chosen["final_score"]
                    rescored = True
            except Exception:
                logger.warning("Live snap re-score failed", exc_info=True)

        dominant, why = _derive_why(dims, weights)
        # Honest label: use a REAL failure-mode classification only if one of the
        # fragments actually carries one; unclassified telemetry (KPI anomalies)
        # is a correlated-evidence link, not a CMDB failure mode.
        classified = (_primary_failure_mode(of) if of is not None else None) or \
                     (_primary_failure_mode(mf) if mf is not None else None)
        relation_label = classified.replace("_", " ").title() if classified else "Correlated anomaly"
        snaps.append(EntitySnapCard(
            fragment_id=ours,
            matched_fragment_id=other,
            matched_snippet=_snippet(mf.raw_content) if mf else "",
            matched_source_type=mf.source_type if mf else None,
            failure_mode=fmode,
            relation_label=relation_label,
            final_score=final,
            decision=r.decision,
            evaluated_at=r.evaluated_at,
            dimensions=dims,
            dominant_driver=dominant,
            why=why,
            rescored_live=rescored,
        ))

    snaps.sort(key=lambda c: c.final_score, reverse=True)

    return EntityInvestigationResponse(
        entity_identifier=entity_identifier,
        tenant_id=tid,
        embedding_status=embedding_status,
        fragment_count=len(fragments),
        embedded_count=embedded_count,
        evidence=evidence,
        snaps=snaps,
        divergence=divergence,
    )
