"""
Shadow Topology API Router.

Provides endpoints for querying shadow entities, neighbourhood expansion,
and controlled CMDB export.

LLD ref: §8 (Shadow Topology Graph)
"""

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Security
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.database import async_session_maker, get_db
from backend.app.core.logging import get_logger
from backend.app.core.security import INCIDENT_READ, User, get_current_user
from backend.app.models.abeyance_orm import ShadowEntityORM
from backend.app.schemas.abeyance import (
    CmdbExportResponse,
    ShadowEntityResponse,
    ShadowNeighbourhoodResponse,
)

logger = get_logger(__name__)
router = APIRouter()


@router.get("/entities", response_model=List[ShadowEntityResponse])
async def list_shadow_entities(
    tenant_id: Optional[str] = Query(None),
    origin: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Security(get_current_user, scopes=[INCIDENT_READ]),
):
    """List shadow entities in the private topology graph.

    LLD ref: §8 (Shadow Topology Graph)
    """
    tid = current_user.tenant_id or tenant_id
    if not tid:
        raise HTTPException(status_code=400, detail="tenant_id is required")

    query = select(ShadowEntityORM).where(ShadowEntityORM.tenant_id == tid)

    if origin:
        query = query.where(ShadowEntityORM.origin == origin)

    query = query.order_by(ShadowEntityORM.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(query)
    entities = result.scalars().all()
    return [ShadowEntityResponse.model_validate(e) for e in entities]


@router.get("/neighbourhood/{entity_identifier}", response_model=ShadowNeighbourhoodResponse)
async def get_neighbourhood(
    entity_identifier: str,
    tenant_id: Optional[str] = Query(None),
    hops: int = Query(2, ge=1, le=5),
    db: AsyncSession = Depends(get_db),
    current_user: User = Security(get_current_user, scopes=[INCIDENT_READ]),
):
    """Get N-hop neighbourhood expansion for a shadow entity.

    Returns the entity and all entities reachable within the specified
    number of hops in the shadow topology graph.

    LLD ref: §8 (Shadow Topology Graph)
    """
    from backend.app.services.abeyance.shadow_topology import get_shadow_topology

    tid = current_user.tenant_id or tenant_id
    if not tid:
        raise HTTPException(status_code=400, detail="tenant_id is required")

    service = get_shadow_topology(async_session_maker)
    neighbourhood = await service.get_neighbourhood(
        tid, entity_identifier, hops=hops, session=db
    )

    if not neighbourhood:
        raise HTTPException(
            status_code=404,
            detail=f"Entity '{entity_identifier}' not found in shadow topology",
        )

    return neighbourhood


@router.post("/export/{relationship_id}", response_model=CmdbExportResponse)
async def export_to_cmdb(
    relationship_id: UUID,
    tenant_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Security(get_current_user, scopes=[INCIDENT_READ]),
):
    """Controlled export of a shadow relationship to CMDB.

    Sanitises the relationship data, retains competitive intelligence
    privately, and logs the export for audit.

    LLD ref: §8 (Shadow Topology Graph — CMDB Export)
    """
    from backend.app.services.abeyance.shadow_topology import get_shadow_topology

    tid = current_user.tenant_id or tenant_id
    if not tid:
        raise HTTPException(status_code=400, detail="tenant_id is required")

    service = get_shadow_topology(async_session_maker)
    try:
        export_log = await service.export_to_cmdb(tid, relationship_id, session=db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return CmdbExportResponse.model_validate(export_log)
