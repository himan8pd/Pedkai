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


class IncidentImpact(str, Enum):
    """ITIL v4 Impact — effect on business processes."""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class IncidentUrgency(str, Enum):
    """ITIL v4 Urgency — how quickly resolution is required."""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class IncidentPriority(str, Enum):
    """ITIL v4 Priority — derived from Impact x Urgency matrix.

    Impact / Urgency |  High       |  Medium  |  Low
    High             |  P1 Critical|  P2 High |  P3 Medium
    Medium           |  P2 High    |  P3 Med  |  P4 Low
    Low              |  P3 Medium  |  P4 Low  |  P5 Info
    """
    P1 = "P1"  # Critical
    P2 = "P2"  # High
    P3 = "P3"  # Medium
    P4 = "P4"  # Low
    P5 = "P5"  # Informational


# Keep legacy enum for backward compatibility with IncidentCreate callers
class IncidentSeverity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MAJOR = "major"
    MEDIUM = "medium"
    MINOR = "minor"
    WARNING = "warning"


# Mapping from legacy severity to ITIL fields
SEVERITY_TO_ITIL = {
    "critical": (IncidentImpact.HIGH, IncidentUrgency.HIGH, IncidentPriority.P1),
    "high":     (IncidentImpact.HIGH, IncidentUrgency.MEDIUM, IncidentPriority.P2),
    "major":    (IncidentImpact.HIGH, IncidentUrgency.MEDIUM, IncidentPriority.P2),
    "medium":   (IncidentImpact.MEDIUM, IncidentUrgency.MEDIUM, IncidentPriority.P3),
    "minor":    (IncidentImpact.MEDIUM, IncidentUrgency.LOW, IncidentPriority.P3),
    "warning":  (IncidentImpact.LOW, IncidentUrgency.MEDIUM, IncidentPriority.P4),
}


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
    id: str  # Accepts both UUIDs and custom IDs like INC-CL-PAPILLON-xxx
    tenant_id: str
    title: str
    # ITIL v4 Priority Matrix
    impact: Optional[str] = None        # high | medium | low
    urgency: Optional[str] = None       # high | medium | low
    priority: Optional[str] = None      # P1 | P2 | P3 | P4 | P5
    severity: Optional[str] = None      # Legacy raw severity value
    status: IncidentStatus
    entity_id: Optional[str] = None
    entity_external_id: Optional[str] = None
    reasoning_chain: Optional[List[Dict[str, Any]]] = None  # Flexible shape for different data sources
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
    action_type: str  # human | automated | rl_system
    actor: str
    details: Optional[str] = None
    trace_id: Optional[str] = None
    llm_model_version: Optional[str] = None
    llm_prompt_hash: Optional[str] = None
