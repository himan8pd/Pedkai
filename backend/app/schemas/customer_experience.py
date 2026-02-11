"""
Pydantic Schemas for Phase 14: Customer Experience Intelligence.
"""
from typing import Optional, List
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, Field

class CustomerBase(BaseModel):
    external_id: str
    name: Optional[str] = None
    churn_risk_score: float = Field(0.0, ge=0.0, le=1.0)
    associated_site_id: Optional[str] = None

class CustomerCreate(CustomerBase):
    pass

class CustomerSchema(CustomerBase):
    id: UUID
    tenant_id: str
    created_at: datetime

    class Config:
        from_attributes = True

class ProactiveCareSchema(BaseModel):
    id: UUID
    customer_id: UUID
    anomaly_id: Optional[UUID] = None
    channel: str
    status: str
    message_content: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True

class CXImpactAnalysis(BaseModel):
    anomaly_id: UUID
    impacted_customers: List[CustomerSchema]
    total_high_risk_count: int
