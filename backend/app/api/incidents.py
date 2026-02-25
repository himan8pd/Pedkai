"""
Incident Lifecycle API Router.

Implements the full incident lifecycle with 3 mandatory human gate approval steps.
Human gates cannot be bypassed — the API enforces lifecycle ordering.

WS2 — Incident Lifecycle Management.
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Security, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from backend.app.core.database import get_db
from backend.app.core.security import (
    get_current_user, User,
    INCIDENT_READ, INCIDENT_APPROVE_SITREP, INCIDENT_APPROVE_ACTION, INCIDENT_CLOSE,
)
from backend.app.schemas.incidents import (
    IncidentCreate, IncidentResponse, IncidentStatus, IncidentSeverity,
    ApprovalRequest, AuditTrailEntry, ReasoningStep,
)
from backend.app.models.incident_orm import IncidentORM
from backend.app.models.network_entity_orm import NetworkEntityORM
from backend.app.models.audit_orm import IncidentAuditEntryORM
from backend.app.services.decision_repository import DecisionTraceRepository
from backend.app.services.rl_evaluator import get_rl_evaluator
from backend.app.core.database import async_session_maker
from backend.app.middleware.trace import correlation_id_ctx

logger = logging.getLogger(__name__)
router = APIRouter()

# Lifecycle ordering — cannot skip stages
_LIFECYCLE_ORDER = [
    IncidentStatus.ANOMALY,
    IncidentStatus.DETECTED,
    IncidentStatus.RCA,
    IncidentStatus.SITREP_DRAFT,
    IncidentStatus.SITREP_APPROVED,
    IncidentStatus.RESOLVING,
    IncidentStatus.RESOLUTION_APPROVED,
    IncidentStatus.RESOLVED,
    IncidentStatus.CLOSED,
    IncidentStatus.LEARNING,
]

# Stages that require a human gate before advancing
_HUMAN_GATE_REQUIRED_BEFORE = {
    IncidentStatus.SITREP_APPROVED: "approve-sitrep",
    IncidentStatus.RESOLUTION_APPROVED: "approve-action",
    IncidentStatus.CLOSED: "close",
}


def _next_status(current: str) -> Optional[str]:
    """Get the next status in the lifecycle."""
    try:
        idx = _LIFECYCLE_ORDER.index(IncidentStatus(current))
        if idx + 1 < len(_LIFECYCLE_ORDER):
            return _LIFECYCLE_ORDER[idx + 1].value
    except (ValueError, IndexError):
        pass
    return None


async def _log_audit_event(
    db: AsyncSession,
    incident_id: str,
    tenant_id: str,
    action: str,
    action_type: str,
    actor: str,
    details: Optional[str] = None,
    trace_id: Optional[str] = None,
    llm_model_version: Optional[str] = None,
    llm_prompt_hash: Optional[str] = None,
) -> None:
    """Helper to log persistent audit entries for regulatory compliance."""
    # Get current trace_id from context if not provided
    if not trace_id:
        try:
            trace_id = correlation_id_ctx.get()
        except LookupError:
            pass

    entry = IncidentAuditEntryORM(
        incident_id=incident_id,
        tenant_id=tenant_id,
        action=action,
        action_type=action_type,
        actor=actor,
        details=details,
        trace_id=trace_id,
        llm_model_version=llm_model_version,
        llm_prompt_hash=llm_prompt_hash,
    )
    db.add(entry)
    await db.flush()


@router.post("/", response_model=IncidentResponse, status_code=201)
async def create_incident(
    payload: IncidentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Security(get_current_user, scopes=[INCIDENT_READ]),
):
    """
    Create a new incident.
    If entity_type is EMERGENCY_SERVICE, severity is forced to critical (P1).
    """
    # P1.2 Fix: Detect emergency service via string match (resilient fallback) and DB lookup
    is_emergency = False
    severity = payload.severity
    
    entity_id_str = str(payload.entity_id) if payload.entity_id else ""
    external_id_str = payload.entity_external_id or ""
    
    if "EMERGENCY" in entity_id_str.upper() or "EMERGENCY" in external_id_str.upper():
        is_emergency = True
        
    if not is_emergency and payload.entity_id:
        try:
            # P1.2: Use NetworkEntityORM instead of raw SQL
            entity_result = await db.execute(
                select(NetworkEntityORM).where(
                    and_(
                        NetworkEntityORM.id == payload.entity_id,
                        NetworkEntityORM.entity_type == 'EMERGENCY_SERVICE'
                    )
                )
            )
            entity = entity_result.scalars().first()
            is_emergency = entity is not None
        except Exception as e:
            logger.warning(f"Emergency service DB check failed: {e}")

    if is_emergency:
        severity = IncidentSeverity.CRITICAL

    incident = IncidentORM(
        id=str(uuid.uuid4()),
        tenant_id=current_user.tenant_id or payload.tenant_id,
        title=payload.title,
        severity=severity.value,
        status=IncidentStatus.ANOMALY.value,
        entity_id=str(payload.entity_id) if payload.entity_id else None,
        entity_external_id=payload.entity_external_id,
        created_at=datetime.now(timezone.utc),
    )
    db.add(incident)
    await db.flush()

    # Log initial audit event
    await _log_audit_event(
        db, incident.id, incident.tenant_id,
        action="ANOMALY_DETECTED",
        action_type="automated",
        actor="pedkai-platform",
        details=f"Incident created with severity {incident.severity}",
    )

    return _to_response(incident)


@router.get("/", response_model=List[IncidentResponse])
async def list_incidents(
    status: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    tenant_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Security(get_current_user, scopes=[INCIDENT_READ]),
):
    """List incidents with optional filters."""
    query = select(IncidentORM)
    # Finding S-1 Fix: Mandatory tenant filtering
    tid = current_user.tenant_id or tenant_id
    if not tid and current_user.role != "admin":
         raise HTTPException(status_code=403, detail="Tenant ID required for non-admin users.")
    
    if tid:
        query = query.where(IncidentORM.tenant_id == tid)

    result = await db.execute(query.order_by(IncidentORM.created_at.desc()).limit(100))
    incidents = result.scalars().all()
    return [_to_response(i) for i in incidents]


@router.get("/{incident_id}", response_model=IncidentResponse)
async def get_incident(
    incident_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Security(get_current_user, scopes=[INCIDENT_READ]),
):
    """Get incident detail with reasoning chain."""
    incident = await _get_or_404(db, incident_id, current_user.tenant_id)
    return _to_response(incident)


@router.post("/{incident_id}/generate-sitrep", response_model=IncidentResponse)
async def generate_sitrep(
    incident_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Security(get_current_user, scopes=[INCIDENT_READ]),
):
    """
    Generate an AI SITREP for the incident.
    Populates audit trail fields and reasoning summary.
    """
    incident = await _get_or_404(db, incident_id, current_user.tenant_id)

    # RCA and context logic (simulated for PoC or fetched from DB)
    from backend.app.services.llm_service import get_llm_service
    llm_service = get_llm_service()

    # Context enrichment logic
    incident_context = {
        "entity_id": incident.entity_id,
        "entity_name": incident.entity_external_id or "Unknown",
        "entity_type": "EMERGENCY_SERVICE" if incident.severity == "critical" else "NETWORK_ELEMENT",
        "severity": incident.severity,
        "title": incident.title,
        "metrics": {"load": 75, "latency_ms": 120}
    }

    # Fetch similar decisions (placeholder for task 4.x)
    similar_decisions = []

    # Populate audit trail fields — Amendment #7
    llm_response = await llm_service.generate_sitrep(
        incident_context=incident_context,
        similar_decisions=similar_decisions,
        session=db
    )
    
    incident.llm_model_version = llm_response.get("model_version", "unknown")
    incident.llm_prompt_hash = llm_response.get("prompt_hash", "")
    incident.resolution_summary = llm_response.get("text", "")
    incident.status = IncidentStatus.SITREP_DRAFT.value
    
    incident.updated_at = datetime.now(timezone.utc)
    
    # Log audit event for SITREP generation
    await _log_audit_event(
        db, incident.id, incident.tenant_id,
        action="SITREP_GENERATED",
        action_type="automated",
        actor="llm_service",
        details="AI SITREP generated via Gemini Flash",
        llm_model_version=incident.llm_model_version,
        llm_prompt_hash=incident.llm_prompt_hash,
    )

    await db.commit()
    await db.refresh(incident)
    
    return _to_response(incident)


@router.patch("/{incident_id}/advance", response_model=IncidentResponse)
async def advance_lifecycle(
    incident_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Security(get_current_user, scopes=[INCIDENT_READ]),
):
    """
    Advance incident to next lifecycle stage.
    Enforces: cannot advance past sitrep_draft without calling approve-sitrep first.
    """
    incident = await _get_or_404(db, incident_id, current_user.tenant_id)
    next_status = _next_status(incident.status)

    if not next_status:
        raise HTTPException(status_code=400, detail="Incident is already at the final lifecycle stage.")

    # Human gate enforcement
    gate = _HUMAN_GATE_REQUIRED_BEFORE.get(IncidentStatus(next_status))
    if gate:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Cannot advance to '{next_status}' via this endpoint. "
                f"Use POST /{incident_id}/{gate} to complete the required human gate first."
            ),
        )

    incident.status = next_status
    incident.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return _to_response(incident)


@router.post("/{incident_id}/approve-sitrep", response_model=IncidentResponse)
async def approve_sitrep(
    incident_id: str,
    payload: ApprovalRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Security(get_current_user, scopes=[INCIDENT_APPROVE_SITREP]),
):
    """Human Gate 1: Approve situation report. Requires incident:approve_sitrep scope."""
    incident = await _get_or_404(db, incident_id, current_user.tenant_id)

    if incident.status not in (IncidentStatus.SITREP_DRAFT.value, IncidentStatus.DETECTED.value, IncidentStatus.RCA.value):
        raise HTTPException(
            status_code=400,
            detail=f"Incident must be in sitrep_draft/detected/rca status to approve sitrep. Current: {incident.status}"
        )

    incident.status = IncidentStatus.SITREP_APPROVED.value
    incident.sitrep_approved_by = payload.approved_by
    incident.sitrep_approved_at = datetime.now(timezone.utc)
    incident.updated_at = datetime.now(timezone.utc)
    await db.flush()

    # Log audit event
    await _log_audit_event(
        db, incident.id, incident.tenant_id,
        action="SITREP_APPROVED",
        action_type="human",
        actor=payload.approved_by,
        details="Engineer reviewed and approved SITREP (Human Gate 1)",
    )

    return _to_response(incident)


@router.post("/{incident_id}/approve-action", response_model=IncidentResponse)
async def approve_action(
    incident_id: str,
    payload: ApprovalRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Security(get_current_user, scopes=[INCIDENT_APPROVE_ACTION]),
):
    """Human Gate 2: Approve resolution action. Requires incident:approve_action scope."""
    incident = await _get_or_404(db, incident_id, current_user.tenant_id)

    if incident.status not in (IncidentStatus.SITREP_APPROVED.value, IncidentStatus.RESOLVING.value):
        raise HTTPException(
            status_code=400,
            detail=f"Incident must have sitrep approved before action can be approved. Current: {incident.status}"
        )

    incident.status = IncidentStatus.RESOLUTION_APPROVED.value
    incident.action_approved_by = payload.approved_by
    incident.action_approved_at = datetime.now(timezone.utc)
    incident.updated_at = datetime.now(timezone.utc)
    await db.flush()

    # Log audit event
    await _log_audit_event(
        db, incident.id, incident.tenant_id,
        action="ACTION_APPROVED",
        action_type="human",
        actor=payload.approved_by,
        details="Engineer approved resolution action (Human Gate 2)",
    )

    return _to_response(incident)


@router.post("/{incident_id}/close", response_model=IncidentResponse)
async def close_incident(
    incident_id: str,
    payload: ApprovalRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Security(get_current_user, scopes=[INCIDENT_CLOSE]),
):
    """Human Gate 3: Close incident. Requires incident:close scope."""
    incident = await _get_or_404(db, incident_id, current_user.tenant_id)

    if incident.status not in (IncidentStatus.RESOLUTION_APPROVED.value, IncidentStatus.RESOLVED.value):
        raise HTTPException(
            status_code=400,
            detail=f"Incident must be resolved before closing. Current: {incident.status}"
        )

    incident.status = IncidentStatus.CLOSED.value
    incident.closed_by = payload.approved_by
    incident.closed_at = datetime.now(timezone.utc)
    incident.updated_at = datetime.now(timezone.utc)
    await db.flush()

    # Log audit event
    await _log_audit_event(
        db, incident.id, incident.tenant_id,
        action="CLOSED",
        action_type="human",
        actor=payload.approved_by,
        details="Engineer confirmed resolution and closed incident (Human Gate 3)",
    )

    # P2.5: Trigger RL evaluation and feedback application for associated decision trace
    try:
        if incident.decision_trace_id:
            # Retrieve decision trace
            repo = DecisionTraceRepository(async_session_maker)
            decision = await repo.get_by_id(incident.decision_trace_id, session=db)
            if decision:
                rl = get_rl_evaluator(db_session=db)
                reward = await rl.evaluate_decision_outcome(decision)
                await rl.apply_feedback(decision.id, reward)
    except Exception as e:
        # Do not block incident close on RL errors; log and continue
        logger.exception(f"RL Evaluator integration failed during close_incident: {e}")
    return _to_response(incident)


@router.get("/{incident_id}/reasoning")
async def get_reasoning(
    incident_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Security(get_current_user, scopes=[INCIDENT_READ]),
):
    """Get the AI reasoning chain for an incident."""
    incident = await _get_or_404(db, incident_id, current_user.tenant_id)
    return {
        "incident_id": incident_id,
        "reasoning_chain": incident.reasoning_chain or [],
        "llm_model_version": incident.llm_model_version,
        "llm_prompt_hash": incident.llm_prompt_hash,
    }


@router.get("/{incident_id}/audit-trail")
async def get_audit_trail(
    incident_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Security(get_current_user, scopes=[INCIDENT_READ]),
):
    """Get the full audit trail for an incident.
    
    Enhanced with action_type and trace_id for compliance and auditability.
    Each automated or human action is logged with:
    - timestamp: When the action occurred
    - action_type: human | automated | rl_system (for governance classification)
    - trace_id: Distributed tracing ID linking to request logs
    """
    from backend.app.middleware.trace import correlation_id_ctx
    
    incident = await _get_or_404(db, incident_id, current_user.tenant_id)
    
    # Query persistent audit entries
    stmt = (
        select(IncidentAuditEntryORM)
        .where(IncidentAuditEntryORM.incident_id == incident_id)
        .order_by(IncidentAuditEntryORM.timestamp.asc())
    )
    result = await db.execute(stmt)
    entries = result.scalars().all()

    trail = [
        AuditTrailEntry(
            timestamp=e.timestamp,
            action=e.action,
            action_type=e.action_type,
            actor=e.actor,
            details=e.details,
            trace_id=e.trace_id,
            llm_model_version=e.llm_model_version,
            llm_prompt_hash=e.llm_prompt_hash,
        )
        for e in entries
    ]
    
    # Fallback for legacy incidents if no entries found (compute from dates)
    if not trail:
        trail.append(AuditTrailEntry(
            timestamp=incident.created_at,
            action="ANOMALY_DETECTED",
            action_type="automated",
            actor="pedkai-platform",
            details=f"Incident created with severity {incident.severity}",
            trace_id=incident.decision_trace_id
        ))
        if incident.sitrep_approved_at:
            trail.append(AuditTrailEntry(
                timestamp=incident.sitrep_approved_at,
                action="SITREP_APPROVED",
                action_type="human",
                actor=incident.sitrep_approved_by or "unknown",
                details="Engineer reviewed SITREP"
            ))
        if incident.action_approved_at:
            trail.append(AuditTrailEntry(
                timestamp=incident.action_approved_at,
                action="ACTION_APPROVED",
                action_type="human",
                actor=incident.action_approved_by or "unknown",
                details="Engineer approved action"
            ))
        if incident.closed_at:
            trail.append(AuditTrailEntry(
                timestamp=incident.closed_at,
                action="CLOSED",
                action_type="human",
                actor=incident.closed_by or "unknown",
                details="Incident closed"
            ))

    return {"incident_id": incident_id, "audit_trail": trail}


@router.get("/{incident_id}/audit-trail/csv")
async def get_audit_trail_csv(
    incident_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Security(get_current_user, scopes=[INCIDENT_READ]),
):
    """Export audit trail as CSV for regulatory filing.
    
    Returns a properly formatted CSV file suitable for audit, compliance, and regulatory teams.
    Includes action_type classification for governance purposes.
    """
    import csv
    from io import StringIO
    from fastapi.responses import StreamingResponse
    
    incident = await _get_or_404(db, incident_id, current_user.tenant_id)
    
    # Query persistent audit entries (reuse logic from JSON endpoint)
    stmt = (
        select(IncidentAuditEntryORM)
        .where(IncidentAuditEntryORM.incident_id == incident_id)
        .order_by(IncidentAuditEntryORM.timestamp.asc())
    )
    result = await db.execute(stmt)
    entries = result.scalars().all()
    
    trail = [
        {
            "timestamp": e.timestamp.isoformat(),
            "action": e.action,
            "action_type": e.action_type,
            "actor": e.actor,
            "details": e.details,
            "trace_id": e.trace_id,
        }
        for e in entries
    ]

    if not trail:
        # Fallback for legacy
        trail.append({
            "timestamp": incident.created_at.isoformat(),
            "action": "ANOMALY_DETECTED",
            "action_type": "automated",
            "actor": "pedkai-platform",
            "details": f"Incident created with severity {incident.severity}",
            "trace_id": incident.decision_trace_id,
        })
        if incident.sitrep_approved_at:
            trail.append({
                "timestamp": incident.sitrep_approved_at.isoformat(),
                "action": "SITREP_APPROVED",
                "action_type": "human",
                "actor": incident.sitrep_approved_by,
                "details": "Engineer approved SITREP",
                "trace_id": None,
            })
        if incident.action_approved_at:
            trail.append({
                "timestamp": incident.action_approved_at.isoformat(),
                "action": "ACTION_APPROVED",
                "action_type": "human",
                "actor": incident.action_approved_by,
                "details": "Engineer approved action",
                "trace_id": None,
            })
        if incident.closed_at:
            trail.append({
                "timestamp": incident.closed_at.isoformat(),
                "action": "CLOSED",
                "action_type": "human",
                "actor": incident.closed_by,
                "details": "Incident closed",
                "trace_id": None,
            })

    # Generate CSV with proper formatting
    output = StringIO()
    csv_writer = csv.DictWriter(
        output,
        fieldnames=["timestamp", "action", "action_type", "actor", "details", "trace_id"],
        quoting=csv.QUOTE_MINIMAL,
    )
    
    csv_writer.writeheader()
    for row in trail:
        csv_writer.writerow(row)
    
    csv_content = output.getvalue()
    
    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="incident-{incident_id}-audit-trail.csv"'
        }
    )


async def _get_or_404(db: AsyncSession, incident_id: str, tenant_id: Optional[str] = None) -> IncidentORM:
    query = select(IncidentORM).where(IncidentORM.id == incident_id)
    if tenant_id:
        query = query.where(IncidentORM.tenant_id == tenant_id)
    
    result = await db.execute(query)
    incident = result.scalar_one_or_none()
    if not incident:
        raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found or access denied")
    return incident


def _to_response(incident: IncidentORM) -> IncidentResponse:
    return IncidentResponse(
        id=incident.id,
        tenant_id=incident.tenant_id,
        title=incident.title,
        severity=IncidentSeverity(incident.severity),
        status=IncidentStatus(incident.status),
        entity_id=incident.entity_id,
        reasoning_chain=incident.reasoning_chain,
        resolution_summary=incident.resolution_summary,
        created_at=incident.created_at,
        updated_at=incident.updated_at,
        sitrep_approved_by=incident.sitrep_approved_by,
        sitrep_approved_at=incident.sitrep_approved_at,
        action_approved_by=incident.action_approved_by,
        action_approved_at=incident.action_approved_at,
        closed_by=incident.closed_by,
        closed_at=incident.closed_at,
        llm_model_version=incident.llm_model_version,
        ai_generated=True if incident.llm_model_version else False,
        ai_watermark="This content was generated by Pedkai AI (Gemini). It is advisory only and requires human review before action." if incident.llm_model_version else None,
    )
