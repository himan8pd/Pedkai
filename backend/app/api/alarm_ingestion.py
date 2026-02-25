"""
Alarm Ingestion Webhook Endpoint (P1.6).

Accepts inbound alarms from external systems (OSS, monitoring, etc.)
and publishes them as events for downstream processing.
Implements REST accept pattern: receive, validate, queue, respond 202.
"""
import logging
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Security, status
from pydantic import BaseModel, Field

from backend.app.core.security import get_current_user, User, TMF642_READ, TMF642_WRITE
from backend.app.events.schemas import AlarmIngestedEvent
from backend.app.events.bus import publish_event

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/alarms",
    tags=["alarms"],
    responses={401: {"description": "Unauthorized"}},
)


class AlarmIngestionRequest(BaseModel):
    """
    Schema for incoming alarm ingestion request.
    
    Subset of AlarmIngestedEvent that the client provides;
    server fills in event_id, timestamp, and tenant_id.
    """
    
    entity_id: str = Field(
        description="Network entity UUID affected by alarm"
    )
    
    entity_external_id: Optional[str] = Field(
        default=None,
        description="Optional external system reference"
    )
    
    alarm_type: str = Field(
        description="Alarm category (e.g., LINK_DOWN, DEGRADATION)"
    )
    
    severity: str = Field(
        description="Severity: minor, major, critical"
    )
    
    raised_at: datetime = Field(
        description="When alarm was raised (may be historical)"
    )
    
    source_system: str = Field(
        description="Origin (e.g., oss_vendor, snmp, api)"
    )


class AlarmIngestionResponse(BaseModel):
    """Response from alarm ingestion endpoint."""
    
    event_id: str = Field(
        description="Event ID assigned by server"
    )
    
    tenant_id: str = Field(
        description="Tenant to which alarm was assigned"
    )
    
    status: str = Field(
        default="accepted",
        description="Status of ingestion"
    )


@router.post(
    "/ingest",
    response_model=AlarmIngestionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ingest external alarm",
    description="Accept and queue an alarm for processing",
)
async def ingest_alarm(
    request: AlarmIngestionRequest,
    current_user: User = Security(get_current_user, scopes=[TMF642_WRITE]),
) -> AlarmIngestionResponse:
    """
    Ingestion endpoint for external alarms.
    
    Process:
    1. Validate request schema
    2. Extract tenant from current user
    3. Create AlarmIngestedEvent with server-assigned event_id
    4. Publish to internal event bus
    5. Return 202 Accepted with event_id
    
    Authentication:
        Requires ALARM_WRITE scope. Tenant isolation via current_user.tenant_id.
    
    Args:
        request: Alarm data from external system
        current_user: Authenticated user (provides tenant_id for isolation)
    
    Returns:
        202 with event_id (no response body awaited by client)
    
    Raises:
        401: If unauthenticated or insufficient scope
        422: If request validation fails
        503: If event bus is full
    """
    tenant_id = current_user.tenant_id or "default"
    
    try:
        # Create event with server-assigned tracking IDs
        event = AlarmIngestedEvent(
            tenant_id=tenant_id,
            entity_id=request.entity_id,
            entity_external_id=request.entity_external_id,
            alarm_type=request.alarm_type,
            severity=request.severity,
            raised_at=request.raised_at,
            source_system=request.source_system,
        )
        
        # Publish to internal queue for async processing
        await publish_event(event)
        
        logger.info(
            f"Alarm ingested: type={request.alarm_type}, "
            f"severity={request.severity}, "
            f"entity_id={request.entity_id}, "
            f"tenant={tenant_id}, "
            f"event_id={event.event_id[:8]}..."
        )
        
        return AlarmIngestionResponse(
            event_id=event.event_id,
            tenant_id=tenant_id,
            status="accepted"
        )
        
    except ValueError as e:
        logger.warning(f"Invalid alarm request: {e}")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Failed to ingest alarm: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Event bus unavailable",
        )
