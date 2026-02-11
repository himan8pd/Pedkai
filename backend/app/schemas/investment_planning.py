"""
Pydantic schemas for AI-Driven Capacity Planning.
"""
from datetime import datetime
from typing import List, Dict, Any, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field

class SitePlacement(BaseModel):
    name: str
    lat: float
    lon: float
    cost: float
    backhaul: str

class DensificationCreate(BaseModel):
    region_name: str
    budget_limit: float
    target_kpi: Optional[str] = "prb_utilization"
    parameters: Optional[Dict[str, Any]] = Field(default_factory=dict)

class DensificationSchema(DensificationCreate):
    id: UUID
    tenant_id: str
    status: str
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)

class InvestmentPlanSchema(BaseModel):
    id: UUID
    request_id: UUID
    total_estimated_cost: float
    expected_kpi_improvement: float
    rationale: str
    site_placements: List[SitePlacement]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
