"""
API Router for Phase 14: Customer Experience Intelligence.
"""
from typing import List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.database import get_db, async_session_maker
from backend.app.core.security import (
    get_current_user, 
    User, 
    CX_READ, 
    CX_WRITE
)
from backend.app.schemas.customer_experience import (
    CustomerSchema, 
    ProactiveCareSchema, 
    CXImpactAnalysis
)
from backend.app.services.cx_intelligence import CXIntelligenceService

router = APIRouter()

@router.get("/impact/{anomaly_id}", response_model=CXImpactAnalysis)
async def get_cx_impact_analysis(
    anomaly_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Identify high-risk customers impacted by a specific network anomaly.
    """
    service = CXIntelligenceService(db)
    impacted = await service.identify_impacted_customers(anomaly_id)
    
    return CXImpactAnalysis(
        anomaly_id=anomaly_id,
        impacted_customers=impacted,
        total_high_risk_count=len(impacted)
    )

@router.post("/proactive-care/{anomaly_id}", response_model=List[ProactiveCareSchema], status_code=status.HTTP_201_CREATED)
async def trigger_proactive_care(
    anomaly_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Trigger proactive care automation for all high-risk customers impacted by an anomaly.
    """
    service = CXIntelligenceService(db)
    impacted = await service.identify_impacted_customers(anomaly_id)
    
    if not impacted:
        raise HTTPException(status_code=404, detail="No high-risk impacted customers found for this anomaly.")

    customer_ids = [c.id for c in impacted]
    records = await service.trigger_proactive_care(customer_ids, anomaly_id)
    
    return records
