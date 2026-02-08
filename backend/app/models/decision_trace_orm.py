"""
SQLAlchemy ORM model for Decision Traces.

Maps the Pydantic DecisionTrace schema to PostgreSQL with JSONB storage
for flexible nested structures and pgvector for semantic similarity search.
"""

from datetime import datetime
from typing import Optional
from uuid import uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, DateTime, Float, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from backend.app.core.database import Base
from backend.app.core.config import get_settings

settings = get_settings()


class DecisionTraceORM(Base):
    """
    SQLAlchemy ORM model for Decision Traces.
    
    Uses JSONB for flexible storage of:
    - context (alarms, KPIs, affected entities)
    - constraints (SLAs, regulations)
    - options_considered
    - outcome
    
    Uses pgvector for semantic similarity search on decision embeddings.
    """
    
    __tablename__ = "decision_traces"
    
    # Primary key
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    
    # Multi-tenant isolation
    tenant_id = Column(String(255), nullable=False, index=True)
    
    # Timestamps
    created_at = Column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        server_default=text("now()"),
        nullable=False,
    )
    decision_made_at = Column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False,
    )
    
    # Trigger information
    trigger_type = Column(String(50), nullable=False, index=True)
    trigger_id = Column(String(255), nullable=True)
    trigger_description = Column(String(1000), nullable=False)
    
    # JSONB fields for flexible nested data
    context = Column(JSONB, nullable=False, default=dict)
    constraints = Column(JSONB, nullable=False, default=list)
    options_considered = Column(JSONB, nullable=False, default=list)
    
    # Decision details
    decision_summary = Column(String(2000), nullable=False)
    tradeoff_rationale = Column(String(2000), nullable=False)
    action_taken = Column(String(2000), nullable=False)
    
    # Decision maker
    decision_maker = Column(String(255), nullable=False)
    confidence_score = Column(Float, default=0.0)
    
    # Outcome (JSONB for flexibility)
    outcome = Column(JSONB, nullable=True)
    
    # Vector embedding for semantic similarity search
    embedding = Column(
        Vector(settings.embedding_dimension),
        nullable=True,
    )
    
    # Metadata
    tags = Column(JSONB, nullable=False, default=list)
    domain = Column(String(50), nullable=False, default="anops", index=True)
    
    # Indexes for common queries
    __table_args__ = (
        Index("ix_decision_traces_tenant_domain", "tenant_id", "domain"),
        Index("ix_decision_traces_tenant_created", "tenant_id", "created_at"),
        Index(
            "ix_decision_traces_embedding",
            "embedding",
            postgresql_using="ivfflat",
            postgresql_with={"lists": 100},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )
    
    def __repr__(self) -> str:
        return f"<DecisionTrace(id={self.id}, trigger={self.trigger_type})>"
