"""
API Router for AI-Driven Capacity Planning.
"""
from typing import List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.database import get_db
from backend.app.core.security import (
    get_current_user, 
    User, 
    CAPACITY_READ, 
    CAPACITY_WRITE
)
from backend.app.models.investment_planning import DensificationRequestORM
from backend.app.schemas.investment_planning import DensificationCreate, DensificationSchema, InvestmentPlanSchema
from backend.app.services.capacity_engine import CapacityEngine

router = APIRouter()

@router.post("/", response_model=DensificationSchema, status_code=status.HTTP_201_CREATED)
async def create_densification_request(
    request: DensificationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Launch a new regional densification optimization.
    """
    db_request = DensificationRequestORM(
        tenant_id=current_user.tenant_id if hasattr(current_user, 'tenant_id') else "default",
        region_name=request.region_name,
        budget_limit=request.budget_limit,
        target_kpi=request.target_kpi,
        parameters=request.parameters
    )
    db.add(db_request)
    await db.commit()
    await db.refresh(db_request)
    
    # Trigger background optimization
    engine = CapacityEngine(db)
    await engine.optimize_densification(db_request.id)
    
    return db_request

@router.get("/", response_model=List[DensificationSchema])
async def list_densification_requests(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    List all regional densification requests.
    """
    query = select(DensificationRequestORM).where(
        DensificationRequestORM.tenant_id == (current_user.tenant_id if hasattr(current_user, 'tenant_id') else "default")
    ).order_by(desc(DensificationRequestORM.created_at))
    result = await db.execute(query)
    return result.scalars().all()

@router.get("/{request_id}/plan", response_model=InvestmentPlanSchema)
async def get_investment_plan(
    request_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Retrieve the optimized investment plan for a request.
    """
    # Logic to fetch plan from DB
    from backend.app.models.investment_planning import InvestmentPlanORM
    from sqlalchemy import select
    
    query = select(InvestmentPlanORM).where(InvestmentPlanORM.request_id == request_id)
    result = await db.execute(query)
    plan = result.scalar_one_or_none()
    
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found or still processing")
    
    return plan
