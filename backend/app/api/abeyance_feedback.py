"""
Abeyance Snap Feedback API Router (WIR-01).

Exposes ``POST /snap-feedback`` so an operator's verdict on a snap decision
reaches ``OutcomeCalibrationService.record_feedback`` (Feedback Loop A).

On a true-positive verdict (CONFIRMED / TRUE_POSITIVE) the confirmed snap is
also written to the value-attribution ledger as a discovery plus an
INCIDENT_RESOLUTION value event, so operator confirmations feed the value
report.

Kept separate from ``api/abeyance.py`` deliberately (single-responsibility
router). Service access mirrors that module's lazy singleton pattern so all
abeyance services share one ProvenanceLogger / RedisNotifier.
"""

from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Security
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.database import get_db
from backend.app.core.logging import get_logger
from backend.app.core.security import INCIDENT_READ, User, get_current_user
from backend.app.models.abeyance_orm import SnapDecisionRecordORM
from backend.app.services.abeyance import create_abeyance_services

logger = get_logger(__name__)
router = APIRouter()

# TP-set verdicts (mirrors OutcomeCalibrationService.record_feedback semantics).
_TP_VERDICTS = {"TRUE_POSITIVE", "CONFIRMED"}


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


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class SnapFeedbackRequest(BaseModel):
    snap_decision_record_id: UUID
    verdict: Literal["TRUE_POSITIVE", "CONFIRMED", "FALSE_POSITIVE", "REJECTED"]
    resolution_action: Optional[str] = None
    notes: Optional[str] = None
    attributed_hours: Optional[float] = None


# ---------------------------------------------------------------------------
# POST /snap-feedback
# ---------------------------------------------------------------------------

@router.post("/snap-feedback", status_code=201)
async def submit_snap_feedback(
    payload: SnapFeedbackRequest,
    tenant_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Security(get_current_user, scopes=[INCIDENT_READ]),
):
    """Record an operator verdict on a snap decision (Feedback Loop A).

    On a true-positive verdict (CONFIRMED / TRUE_POSITIVE) the confirmed snap is
    additionally written to the value-attribution ledger as a discovery and an
    INCIDENT_RESOLUTION value event.

    Returns ``{feedback_id, value_ledger_id}`` where ``value_ledger_id`` is
    ``None`` for false-positive verdicts.
    """
    tid = _resolve_tenant(current_user, tenant_id)

    # Validate the snap decision record exists for this tenant.
    result = await db.execute(
        select(SnapDecisionRecordORM).where(
            SnapDecisionRecordORM.id == payload.snap_decision_record_id,
            SnapDecisionRecordORM.tenant_id == tid,
        )
    )
    record = result.scalars().first()
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=f"Snap decision record {payload.snap_decision_record_id} not found",
        )

    services = _get_services()
    calibration = services["outcome_calibration"]
    value_attribution = services["value_attribution"]

    feedback = await calibration.record_feedback(
        session=db,
        tenant_id=tid,
        snap_decision_record_id=payload.snap_decision_record_id,
        operator_verdict=payload.verdict,
        resolution_action=payload.resolution_action,
        notes=payload.notes,
    )

    value_ledger_id: Optional[UUID] = None
    if payload.verdict in _TP_VERDICTS:
        ledger_entry_id = await value_attribution.record_discovery(
            session=db,
            tenant_id=tid,
            hypothesis_id=payload.snap_decision_record_id,
            discovery_type="SNAP_CONFIRMED",
            discovered_entities=[],
            discovered_relationships=[],
            confidence=record.final_score,
        )
        await value_attribution.record_value_event(
            session=db,
            tenant_id=tid,
            ledger_entry_id=ledger_entry_id,
            event_type="INCIDENT_RESOLUTION",
            attributed_hours=payload.attributed_hours,
            rationale="operator confirmed snap",
        )
        value_ledger_id = ledger_entry_id

    await db.commit()

    return {
        "feedback_id": str(feedback.id),
        "value_ledger_id": str(value_ledger_id) if value_ledger_id else None,
    }
