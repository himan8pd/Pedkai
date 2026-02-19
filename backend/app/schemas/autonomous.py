"""
Autonomous Shield Schemas.

Shared contract used by: WS5 (autonomous API), WS3 (frontend).
"""
from typing import Optional, List, Dict, Any
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, Field


class DriftPrediction(BaseModel):
    """Result of KPI drift detection."""
    entity_id: UUID
    entity_name: str
    metric_name: str
    current_value: float
    baseline_value: float
    drift_magnitude: float
    predicted_breach_time: Optional[datetime] = None
    confidence: float = Field(ge=0.0, le=1.0)
    detected_at: datetime
    ai_generated: bool = False
    ai_watermark: Optional[str] = None


class PreventiveRecommendation(BaseModel):
    """A recommended preventive action (human must execute)."""
    recommendation_id: UUID
    drift_prediction_id: Optional[UUID] = None
    action_description: str
    expected_benefit: str
    risk_if_ignored: str
    priority: str  # "critical", "high", "medium", "low"
    requires_change_request: bool = True
    ai_generated: bool = False
    ai_watermark: Optional[str] = None


class ChangeRequestOutput(BaseModel):
    """Structured change request for human engineer execution."""
    change_request_id: UUID
    recommendation_id: UUID
    title: str
    description: str
    affected_entities: List[str]
    rollback_plan: str
    created_at: datetime


class ValueProtected(BaseModel):
    """Counterfactual value metrics (auditable methodology)."""
    revenue_protected: Optional[float] = None
    incidents_prevented: Optional[int] = None
    uptime_gained_minutes: Optional[float] = None
    methodology_doc_url: str = "/docs/value_methodology.md"
    confidence_interval: Optional[str] = None


class ScorecardResponse(BaseModel):
    """Pedkai zone vs non-Pedkai zone comparison."""
    pedkai_zone_mttr_minutes: Optional[float] = None
    non_pedkai_zone_mttr_minutes: Optional[float] = None
    pedkai_zone_incident_count: int
    non_pedkai_zone_incident_count: Optional[int] = None
    improvement_pct: Optional[float] = None
    period_start: datetime
    period_end: datetime
    value_protected: ValueProtected
    baseline_status: Optional[str] = None
    baseline_note: Optional[str] = None
