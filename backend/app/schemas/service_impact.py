"""
Service Impact & Alarm Correlation Schemas.

Shared contract used by: WS4 (correlation API), WS3 (frontend).
"""
from typing import Optional, List, Dict, Any
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, Field


class AlarmCluster(BaseModel):
    """A group of correlated alarms."""
    cluster_id: str | UUID
    alarm_count: int
    noise_reduction_pct: float
    root_cause_entity_id: Optional[str | UUID] = None
    root_cause_entity_name: Optional[str] = None
    severity: str
    created_at: datetime
    is_emergency_service: bool = False  # H&S §2.13
    ai_generated: bool = False
    ai_watermark: Optional[str] = None


class CustomerImpact(BaseModel):
    """A customer impacted by a service issue."""
    customer_id: str | UUID
    customer_name: str
    customer_external_id: str
    revenue_at_risk: Optional[float] = None
    pricing_status: str = "priced"  # "priced" | "unpriced"
    requires_manual_valuation: bool = False
    sla_penalty_risk: Optional[float] = None
    nps_score: Optional[float] = None
    has_recent_dispute: bool = False
    complaint_count: int = 0
    priority_score: Optional[float] = None


class ServiceImpactSummary(BaseModel):
    """Summary of service impact for a cluster or incident."""
    cluster_id: Optional[str | UUID] = None
    total_customers_impacted: int
    total_revenue_at_risk: Optional[float] = None
    unpriced_customer_count: int = 0
    customers: List[CustomerImpact]
    emergency_service_affected: bool = False
