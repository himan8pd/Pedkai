"""
SQLAlchemy ORM model for Decision Traces.

Maps the Pydantic DecisionTrace schema to PostgreSQL with JSONB storage
for flexible nested structures and pgvector for semantic similarity search.
"""

from datetime import datetime
from typing import Optional
from uuid import uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, DateTime, Float, Index, Integer, String, text, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from backend.app.core.database import Base
from backend.app.core.config import get_settings

settings = get_settings()


class DecisionTraceORM(Base):
    """
    SQLAlchemy ORM model for Decision Traces.
    """
    
    __tablename__ = "decision_traces"
    
    # ... (rest of the fields) ...
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4, server_default=text("gen_random_uuid()"))
    tenant_id = Column(String(255), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, server_default=text("now()"), nullable=False)
    decision_made_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    trigger_type = Column(String(50), nullable=False, index=True)
    trigger_id = Column(String(255), nullable=True)
    trigger_description = Column(Text, nullable=False)
    context = Column(JSONB, nullable=False, default=dict)
    constraints = Column(JSONB, nullable=False, default=list)
    options_considered = Column(JSONB, nullable=False, default=list)
    decision_summary = Column(Text, nullable=False)
    tradeoff_rationale = Column(Text, nullable=False)
    action_taken = Column(Text, nullable=False)
    decision_maker = Column(String(255), nullable=False)
    confidence_score = Column(Float, default=0.0)
    outcome = Column(JSONB, nullable=True)
    embedding = Column(Vector(settings.embedding_dimension), nullable=True)
    tags = Column(JSONB, nullable=False, default=list)
    domain = Column(String(50), nullable=False, default="anops", index=True)
    
    # TMF642 Compliance Fields (Phase 3 - Revised)
    ack_state = Column(String(50), default="unacknowledged", nullable=False)  # unacknowledged | acknowledged
    external_correlation_id = Column(String(255), nullable=True)  # Vendor-provided correlation ID
    internal_correlation_id = Column(String(255), nullable=True)  # Pedkai RCA-calculated correlation ID
    probable_cause = Column(String(100), nullable=True)           # TMF enumerated cause
    
    # Finding #4: This is now a cached aggregate of DecisionFeedbackORM
    feedback_score = Column(Integer, default=0, nullable=False)
    
    __table_args__ = (
        Index("ix_decision_traces_tenant_domain", "tenant_id", "domain"),
        Index("ix_decision_traces_tenant_created", "tenant_id", "created_at"),
    )

class DecisionFeedbackORM(Base):
    """
    Finding #4: Multi-operator feedback junction table.
    Enables audit trail and prevents a single operator from overwriting community feedback.
    """
    __tablename__ = "decision_feedback"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4, server_default=text("gen_random_uuid()"))
    decision_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    operator_id = Column(String(255), nullable=False, index=True)
    score = Column(Integer, nullable=False) # 1 for upvote, -1 for downvote
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, server_default=text("now()"), nullable=False)
    
    __table_args__ = (
        # Finding #4: One vote per operator per decision
        Index("ix_feedback_decision_operator", "decision_id", "operator_id", unique=True),
    )
