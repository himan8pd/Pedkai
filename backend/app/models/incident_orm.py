"""
ORM Model for Incident Lifecycle.

Stores incidents with full audit trail for the 3 human gate approval steps.
SQLite-compatible: UUIDs stored as String, no FK constraints.
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, Index, String, Text, DateTime, JSON

from backend.app.core.database import Base


class IncidentORM(Base):
    __tablename__ = "incidents"

    # Primary key — stored as String for SQLite compatibility
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # Core fields
    tenant_id = Column(String(100), nullable=False, index=True)
    title = Column(String(500), nullable=False)
    severity = Column(String(20), nullable=False, index=True)  # Legacy raw severity value
    status = Column(String(30), nullable=False, default="anomaly", index=True)  # IncidentStatus values

    # ITIL v4 Priority Matrix fields
    impact = Column(String(20), nullable=True)    # high | medium | low
    urgency = Column(String(20), nullable=True)   # high | medium | low
    priority = Column(String(20), nullable=True, index=True)  # P1 | P2 | P3 | P4 | P5

    # Entity reference (no FK constraint for SQLite compatibility)
    entity_id = Column(String(36), nullable=True, index=True)
    entity_external_id = Column(String(255), nullable=True)

    # Decision trace reference
    decision_trace_id = Column(String(36), nullable=True)

    # AI reasoning
    reasoning_chain = Column(JSON, nullable=True)  # List[ReasoningStep]
    resolution_summary = Column(Text, nullable=True)
    kpi_snapshot = Column(JSON, nullable=True)

    # LLM audit
    llm_model_version = Column(String(100), nullable=True)
    llm_prompt_hash = Column(String(32), nullable=True)

    # Human Gate 1: Sitrep approval
    sitrep_approved_by = Column(String(255), nullable=True)
    sitrep_approved_at = Column(DateTime(timezone=True), nullable=True)

    # Human Gate 2: Action approval
    action_approved_by = Column(String(255), nullable=True)
    action_approved_at = Column(DateTime(timezone=True), nullable=True)

    # Human Gate 3: Close
    closed_by = Column(String(255), nullable=True)
    closed_at = Column(DateTime(timezone=True), nullable=True)

    # Standard timestamps
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=True, onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("ix_incidents_tenant_created", "tenant_id", "created_at"),
        Index("ix_incidents_tenant_closed", "tenant_id", "closed_at", "created_at"),
    )
