"""
Audit Trail ORM Models for Regulatory Compliance (P4.4)

Stores persistent audit entries for all incident lifecycle actions.
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, DateTime, JSON, ForeignKey
from backend.app.core.database import Base


class IncidentAuditEntryORM(Base):
    """
    Persistent audit trail for an incident.
    Mandatory for regulatory filing (OFCOM/ICO).
    """
    __tablename__ = "incident_audit_entries"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    incident_id = Column(String(36), index=True, nullable=False)
    tenant_id = Column(String(50), nullable=False, index=True)
    
    timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    action = Column(String(100), nullable=False)
    action_type = Column(String(50), nullable=False)  # human | automated | rl_system
    actor = Column(String(255), nullable=False)
    details = Column(Text, nullable=True)
    
    # Distributed tracing and matching
    trace_id = Column(String(128), nullable=True)
    
    # AI Metadata if related to an LLM step
    llm_model_version = Column(String(100), nullable=True)
    llm_prompt_hash = Column(String(32), nullable=True)
    
    def __repr__(self):
        return f"<IncidentAuditEntry {self.action} by {self.actor} for {self.incident_id}>"
