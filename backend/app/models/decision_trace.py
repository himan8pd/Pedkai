"""
Pedkai Decision Trace Models

These models represent the core Context Graph / Decision Memory schema.
Each decision captured by Pedkai includes the full reasoning chain:
- What context was available
- What constraints were binding
- What options were considered
- What tradeoff was made
- What outcome resulted
"""

from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class DecisionOutcome(str, Enum):
    """Outcome status of a decision."""
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILURE = "failure"
    PENDING = "pending"


class ConstraintType(str, Enum):
    """Types of constraints that can bind a decision."""
    SLA = "sla"
    REGULATORY = "regulatory"
    CAPACITY = "capacity"
    MAINTENANCE_WINDOW = "maintenance_window"
    COST = "cost"
    RISK = "risk"
    OPERATIONAL = "operational"


class Constraint(BaseModel):
    """A constraint that was binding during the decision."""
    type: ConstraintType
    description: str
    severity: str = Field(description="How binding: hard, soft, preference")
    value: Optional[str] = None


class Option(BaseModel):
    """An option that was considered during the decision."""
    id: str
    description: str
    risk_assessment: str
    estimated_impact: str
    was_chosen: bool = False
    rejection_reason: Optional[str] = None


class KPISnapshot(BaseModel):
    """Point-in-time snapshot of relevant KPIs."""
    throughput_mbps: Optional[float] = None
    latency_ms: Optional[float] = None
    packet_loss_pct: Optional[float] = None
    availability_pct: Optional[float] = None
    cpu_utilization_pct: Optional[float] = None
    memory_utilization_pct: Optional[float] = None
    custom_metrics: dict = Field(default_factory=dict)


class DecisionContext(BaseModel):
    """The context available when the decision was made."""
    alarm_ids: list[str] = Field(default_factory=list)
    ticket_ids: list[str] = Field(default_factory=list)
    affected_entities: list[str] = Field(
        default_factory=list,
        description="Cell sites, devices, services affected"
    )
    kpi_snapshot: Optional[KPISnapshot] = None
    related_decision_ids: list[UUID] = Field(
        default_factory=list,
        description="Previous decisions that informed this one"
    )
    external_context: dict = Field(
        default_factory=dict,
        description="Weather, events, maintenance schedules, etc."
    )


class DecisionOutcomeRecord(BaseModel):
    """The outcome of the decision after execution."""
    status: DecisionOutcome
    resolution_time_minutes: Optional[float] = None
    customer_impact_count: int = 0
    sla_violated: bool = False
    actual_vs_expected: Optional[str] = None
    follow_up_required: bool = False
    learnings: Optional[str] = Field(
        None,
        description="What we learned that can inform future decisions"
    )


class DecisionTrace(BaseModel):
    """
    Core Decision Trace model - the heart of the Context Graph.
    
    Captures the full reasoning chain for every significant decision:
    - WHY was this decision made?
    - WHAT evidence was consulted?
    - WHAT constraints were binding?
    - WHAT options were considered?
    - WHAT tradeoff was made?
    - WHAT was the outcome?
    
    This is NOT a graph database record - it's a structured document
    that stores decision memory in PostgreSQL with JSONB.
    """
    id: UUID = Field(default_factory=uuid4)
    tenant_id: str = Field(description="Multi-tenant isolation")
    
    # When
    created_at: datetime = Field(default_factory=datetime.utcnow)
    decision_made_at: datetime = Field(default_factory=datetime.utcnow)
    
    # What triggered this decision
    trigger_type: str = Field(description="alarm, ticket, scheduled, manual")
    trigger_id: Optional[str] = None
    trigger_description: str
    
    # The full context available at decision time
    context: DecisionContext
    
    # Constraints that shaped the decision
    constraints: list[Constraint] = Field(default_factory=list)
    
    # Options that were considered
    options_considered: list[Option] = Field(default_factory=list)
    
    # The actual decision made
    decision_summary: str = Field(
        description="Plain English description of what was decided"
    )
    tradeoff_rationale: str = Field(
        description="Why this option was chosen over others"
    )
    action_taken: str = Field(description="Specific action executed")
    
    # Who/what made the decision
    decision_maker: str = Field(
        description="human:<user_id>, system:pedkai, or hybrid"
    )
    confidence_score: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="For AI-assisted decisions"
    )
    
    # The outcome (may be updated later)
    outcome: Optional[DecisionOutcomeRecord] = None
    
    # For vector similarity search
    embedding: Optional[list[float]] = Field(
        None,
        description="Vector embedding for semantic search"
    )
    
    # Metadata
    tags: list[str] = Field(default_factory=list)
    domain: str = Field(
        default="network_ops",
        description="anops, capacity, customer_experience, etc."
    )
    
    # TMF642 Compliance Fields (Phase 3 - Revised)
    ack_state: str = Field(
        default="unacknowledged",
        description="unacknowledged or acknowledged"
    )
    external_correlation_id: Optional[str] = Field(
        None,
        description="Vendor-provided correlation ID"
    )
    internal_correlation_id: Optional[str] = Field(
        None,
        description="Pedkai RCA-calculated correlation ID"
    )
    probable_cause: Optional[str] = Field(
        None,
        description="TMF enumerated cause"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "id": "550e8400-e29b-41d4-a716-446655440000",
                "tenant_id": "vodafone-uk",
                "trigger_type": "alarm",
                "trigger_id": "ALM-2024-0001",
                "trigger_description": "High packet loss on Cell-XYZ",
                "context": {
                    "alarm_ids": ["ALM-2024-0001", "ALM-2024-0002"],
                    "affected_entities": ["cell-xyz", "enodeb-123"],
                    "kpi_snapshot": {
                        "throughput_mbps": 45.2,
                        "latency_ms": 23.0,
                        "packet_loss_pct": 5.2
                    }
                },
                "constraints": [
                    {
                        "type": "sla",
                        "description": "Enterprise customer 99.99% uptime",
                        "severity": "hard"
                    }
                ],
                "options_considered": [
                    {
                        "id": "opt-1",
                        "description": "Restart baseband unit",
                        "risk_assessment": "5 minute outage",
                        "estimated_impact": "Full resolution",
                        "was_chosen": False,
                        "rejection_reason": "SLA violation risk"
                    },
                    {
                        "id": "opt-2",
                        "description": "Failover to adjacent cell",
                        "risk_assessment": "Capacity strain on neighbor",
                        "estimated_impact": "Immediate mitigation",
                        "was_chosen": True
                    }
                ],
                "decision_summary": "Execute failover to adjacent cell",
                "tradeoff_rationale": "Avoid SLA violation; neighbor at 68% capacity can absorb load",
                "action_taken": "Executed traffic steering to Cell-ABC",
                "decision_maker": "system:pedkai",
                "confidence_score": 0.87,
                "outcome": {
                    "status": "success",
                    "resolution_time_minutes": 12,
                    "customer_impact_count": 0,
                    "sla_violated": False,
                    "learnings": "Failover effective when neighbor <70% loaded"
                },
                "domain": "anops",
                "tags": ["ran", "packet-loss", "failover"]
            }
        }


class DecisionTraceCreate(BaseModel):
    """Schema for creating a new decision trace."""
    tenant_id: str
    trigger_type: str
    trigger_id: Optional[str] = None
    trigger_description: str
    context: DecisionContext
    constraints: list[Constraint] = Field(default_factory=list)
    options_considered: list[Option] = Field(default_factory=list)
    decision_summary: str
    tradeoff_rationale: str
    action_taken: str
    decision_maker: str
    confidence_score: float = 0.0
    domain: str = "anops"
    tags: list[str] = Field(default_factory=list)


class DecisionTraceUpdate(BaseModel):
    """Schema for updating a decision trace (mainly for outcome)."""
    outcome: Optional[DecisionOutcomeRecord] = None
    tags: Optional[list[str]] = None


class SimilarDecisionQuery(BaseModel):
    """Query for finding similar past decisions."""
    tenant_id: str
    current_context: DecisionContext
    domain: Optional[str] = None
    min_similarity: float = Field(default=0.7, ge=0.0, le=1.0)
    limit: int = Field(default=5, ge=1, le=20)
