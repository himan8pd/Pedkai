"""
Value Attribution API Router.

Provides endpoints for the discovery ledger, value events,
quarterly reports, illumination ratio, and Dark Graph Reduction Index.

LLD ref: §13 (Value Attribution Framework)
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Security
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.database import async_session_maker, get_db
from backend.app.core.logging import get_logger
from backend.app.core.security import INCIDENT_READ, User, get_current_user
from backend.app.schemas.abeyance import (
    DarkGraphIndexResponse,
    DiscoveryLedgerResponse,
    IlluminationRatioResponse,
    ValueEventResponse,
    ValueReportResponse,
)

logger = get_logger(__name__)
router = APIRouter()


def _get_value_service():
    from backend.app.services.abeyance.value_attribution import ValueAttributionService
    return ValueAttributionService(async_session_maker)


@router.get("/ledger", response_model=List[DiscoveryLedgerResponse])
async def get_discovery_ledger(
    tenant_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Security(get_current_user, scopes=[INCIDENT_READ]),
):
    """Get paginated discovery ledger entries.

    Each entry records a discovery made by PedkAI's Abeyance Memory
    subsystem — entities and relationships that were unknown to the CMDB.

    LLD ref: §13 (Value Attribution Framework)
    """
    tid = current_user.tenant_id or tenant_id
    if not tid:
        raise HTTPException(status_code=400, detail="tenant_id is required")

    service = _get_value_service()
    entries = await service.get_ledger(tid, limit=limit, offset=offset, session=db)
    return entries


@router.get("/events", response_model=List[ValueEventResponse])
async def get_value_events(
    tenant_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Security(get_current_user, scopes=[INCIDENT_READ]),
):
    """Get paginated value attribution events.

    Value events track the realised benefit of PedkAI discoveries:
    MTTR reduction, incident prevention, and topology accuracy improvements.

    LLD ref: §13 (Value Attribution Framework)
    """
    tid = current_user.tenant_id or tenant_id
    if not tid:
        raise HTTPException(status_code=400, detail="tenant_id is required")

    service = _get_value_service()
    events = await service.get_value_events(tid, limit=limit, offset=offset, session=db)
    return events


@router.get("/report", response_model=ValueReportResponse)
async def get_value_report(
    tenant_id: Optional[str] = Query(None),
    quarter: Optional[str] = Query(None, description="Quarter in YYYY-Q# format, e.g. 2026-Q1"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Security(get_current_user, scopes=[INCIDENT_READ]),
):
    """Get quarterly or cumulative value attribution report.

    Aggregates discovery counts, value events, illumination ratio,
    and Dark Graph Reduction Index for the specified period.

    LLD ref: §13 (Value Attribution Framework)
    """
    tid = current_user.tenant_id or tenant_id
    if not tid:
        raise HTTPException(status_code=400, detail="tenant_id is required")

    service = _get_value_service()
    report = await service.generate_quarterly_report(tid, period=quarter or "current", session=db)
    return report


@router.get("/illumination-ratio", response_model=IlluminationRatioResponse)
async def get_illumination_ratio(
    tenant_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Security(get_current_user, scopes=[INCIDENT_READ]),
):
    """Get the current illumination ratio.

    Illumination ratio = incidents where PedkAI-discovered entities
    were involved / total incidents. Higher is better.

    LLD ref: §13 (Value Attribution Framework)
    """
    tid = current_user.tenant_id or tenant_id
    if not tid:
        raise HTTPException(status_code=400, detail="tenant_id is required")

    service = _get_value_service()
    return await service.compute_illumination_ratio(tid, session=db)


@router.get("/dark-graph-index", response_model=DarkGraphIndexResponse)
async def get_dark_graph_index(
    tenant_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Security(get_current_user, scopes=[INCIDENT_READ]),
):
    """Get the Dark Graph Reduction Index.

    DGRI = 1 - (current_divergences / baseline_divergences).
    Measures how much of the "dark graph" PedkAI has illuminated.
    Value of 1.0 means all divergences resolved; 0.0 means no progress.

    LLD ref: §13 (Value Attribution Framework)
    """
    tid = current_user.tenant_id or tenant_id
    if not tid:
        raise HTTPException(status_code=400, detail="tenant_id is required")

    service = _get_value_service()
    return await service.compute_dark_graph_reduction_index(tid, session=db)
