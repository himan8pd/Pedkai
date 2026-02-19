"""
Incident Lifecycle Schemas and Enums.

Shared contract used by: WS1 (topology), WS2 (incidents), WS3 (frontend), WS4 (correlation).
DO NOT modify this file without checking all consumers.
"""
from enum import Enum
from typing import Optional, List, Dict, Any
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, Field


class IncidentStatus(str, Enum):
    """Incident lifecycle stages. Three stages require human gate approval."""
    ANOMALY = "anomaly"
    DETECTED = "detected"
    RCA = "rca"
    SITREP_DRAFT = "sitrep_draft"
    SITREP_APPROVED = "sitrep_approved"      # Human Gate 1
    RESOLVING = "resolving"
    RESOLUTION_APPROVED = "resolution_approved"  # Human Gate 2
    RESOLVED = "resolved"
    CLOSED = "closed"                          # Human Gate 3
    LEARNING = "learning"


class IncidentSeverity(str, Enum):
    CRITICAL = "critical"  # P1
    MAJOR = "major"        # P2
    MINOR = "minor"        # P3
    WARNING = "warning"    # P4


class ReasoningStep(BaseModel):
    """A single step in the AI reasoning chain."""
    step_number: int
    description: str
    evidence: Optional[str] = None
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    source: Optional[str] = None  # e.g., "topology_graph", "kpi_data", "decision_memory"


class IncidentCreate(BaseModel):
    tenant_id: str
    title: str
    severity: IncidentSeverity
    entity_id: Optional[str | UUID] = None
    entity_external_id: Optional[str] = None


class IncidentResponse(BaseModel):
    id: UUID
    tenant_id: str
    title: str
    severity: IncidentSeverity
    status: IncidentStatus
    entity_id: Optional[str | UUID] = None
    reasoning_chain: Optional[List[ReasoningStep]] = None
    resolution_summary: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    # Audit fields
    sitrep_approved_by: Optional[str] = None
    sitrep_approved_at: Optional[datetime] = None
    action_approved_by: Optional[str] = None
    action_approved_at: Optional[datetime] = None
    closed_by: Optional[str] = None
    closed_at: Optional[datetime] = None
    llm_model_version: Optional[str] = None
    ai_generated: bool = False
    ai_watermark: Optional[str] = None

    class Config:
        from_attributes = True


class ApprovalRequest(BaseModel):
    """Request body for human gate approval endpoints."""
    approved_by: str
    reason: Optional[str] = None


class AuditTrailEntry(BaseModel):
    timestamp: datetime
    action: str
    actor: str
    details: Optional[str] = None
    llm_model_version: Optional[str] = None
    llm_prompt_hash: Optional[str] = None
