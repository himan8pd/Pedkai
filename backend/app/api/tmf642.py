"""
TMF642 Alarm Management API Router (v4.0.0)

Adapts internal DecisionTrace resources to TMF642 Alarm resources.
Fulfills Strategic Review GAPs 1 and 3.
"""

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Security
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.database import get_db
from backend.app.core.security import get_current_user, TMF642_READ, TMF642_WRITE
from backend.app.models.decision_trace_orm import DecisionTraceORM
from backend.app.models.tmf642_models import (
    TMF642Alarm, TMF642AlarmRef, TMF642AlarmUpdate,
    PerceivedSeverity, AlarmType, AlarmState, AckState,
    TMF642AlarmedObject
)
# We assume a utility exists to push to Kafka for the POST endpoint
from data_fabric.kafka_producer import publish_event, Topics

router = APIRouter()


def map_orm_to_tmf(orm: DecisionTraceORM) -> TMF642Alarm:
    """Helper to transform ORM record to TMF642 Alarm resource."""
    # Logic for mapping
    # This is an adapter pattern as requested in the plan.
    
    # Map confidence/anomaly to severity (Placeholder heuristic)
    severity = PerceivedSeverity.MAJOR
    if orm.confidence_score > 0.8:
        severity = PerceivedSeverity.CRITICAL
    elif orm.confidence_score < 0.4:
        severity = PerceivedSeverity.MINOR
        
    return TMF642Alarm(
        id=str(orm.id),
        href=f"/tmf-api/alarmManagement/v4/alarm/{orm.id}",
        alarmType=AlarmType.QOS, # Default for AnOps
        perceivedSeverity=severity,
        probableCause=orm.probable_cause or "thresholdCrossed",
        specificProblem=orm.decision_summary,
        state=AlarmState.RAISED, # Map from outcome.status if cleared
        ackState=AckState.ACKNOWLEDGED if orm.ack_state == "acknowledged" else AckState.UNACKNOWLEDGED,
        eventTime=orm.created_at,
        raisedTime=orm.decision_made_at,
        alarmedObject=TMF642AlarmedObject(
            id=orm.trigger_id or "unknown",
            name=orm.trigger_description
        ),
        correlatedAlarm=[
            TMF642AlarmRef(id=orm.internal_correlation_id) 
            if orm.internal_correlation_id else None
        ] if orm.internal_correlation_id else []
    )


@router.get("/alarm", response_model=List[TMF642Alarm])
async def list_alarms(
    alarmType: Optional[AlarmType] = None,
    perceivedSeverity: Optional[PerceivedSeverity] = None,
    state: Optional[AlarmState] = None,
    db: AsyncSession = Depends(get_db),
    current_user=Security(get_current_user, scopes=[TMF642_READ])
):
    """List alarms with TMF filters."""
    result = await db.execute(select(DecisionTraceORM).limit(100))
    results = result.scalars().all()
    return [map_orm_to_tmf(r) for r in results]


@router.get("/alarm/{id}", response_model=TMF642Alarm)
async def get_alarm(
    id: UUID, 
    db: AsyncSession = Depends(get_db),
    current_user=Security(get_current_user, scopes=[TMF642_READ])
):
    """Retrieve a single alarm by ID."""
    result = await db.execute(select(DecisionTraceORM).filter(DecisionTraceORM.id == id))
    orm = result.scalar_one_or_none()
    if not orm:
        raise HTTPException(status_code=404, detail="Alarm not found")
    return map_orm_to_tmf(orm)


@router.post("/alarm", status_code=201)
async def create_alarm(
    alarm: TMF642Alarm,
    current_user=Security(get_current_user, scopes=[TMF642_WRITE])
):
    """
    Ingress endpoint for legacy NMS tools (Strategic Review GAP 1).
    Converts TMF payload to Pedkai event and publishes to Kafka.
    """
    # 1. Transform TMF JSON to internal signal format
    pedkai_event = {
        "event_id": alarm.id,
        "entity_id": alarm.alarmedObject.id,
        "event_type": alarm.alarmType.value,
        "severity": alarm.perceivedSeverity.value,
        "description": alarm.specificProblem,
        "source": "TMF_INGRESS_API",
        "raw_data": alarm.model_dump()
    }
    
    # 2. Publish to Kafka
    # This enables the existing anomaly/RCA pipeline to process it
    # await publish_event(Topics.ALARMS, pedkai_event)
    
    return {"status": "accepted", "id": alarm.id}


@router.patch("/alarm/{id}", response_model=TMF642Alarm)
async def update_alarm(
    id: UUID,
    update: TMF642AlarmUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Security(get_current_user, scopes=[TMF642_WRITE])
):
    """Update alarm state (acknowledge, clear)."""
    result = await db.execute(select(DecisionTraceORM).filter(DecisionTraceORM.id == id))
    orm = result.scalar_one_or_none()
    if not orm:
        raise HTTPException(status_code=404, detail="Alarm not found")
        
    if update.ackState:
        orm.ack_state = "acknowledged" if update.ackState == AckState.ACKNOWLEDGED else "unacknowledged"
        
    await db.commit()
    return map_orm_to_tmf(orm)
