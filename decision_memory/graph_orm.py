"""
Network Entity ORM Models

SQLAlchemy models for storing network entities and relationships
in PostgreSQL with JSONB for flexible attributes.

NOTE: NetworkEntityORM moved to backend.app.models.network_entity_orm
This module re-exports for backward compatibility.
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Column, DateTime, Float, Index, String, Integer, ForeignKey, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from backend.app.core.database import Base

# Import canonical NetworkEntityORM from backend.app.models
from backend.app.models.network_entity_orm import NetworkEntityORM  # noqa: F401


class EntityRelationshipORM(Base):
    """SQLAlchemy model for entity relationships."""
    
    __tablename__ = "entity_relationships"
    
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    tenant_id = Column(String(255), nullable=False, index=True)
    
    # Source entity
    source_entity_id = Column(
        UUID(as_uuid=True),
        ForeignKey("network_entities.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_entity_type = Column(String(50), nullable=False)
    
    # Target entity
    target_entity_id = Column(
        UUID(as_uuid=True),
        ForeignKey("network_entities.id", ondelete="CASCADE"),
        nullable=False,
    )
    target_entity_type = Column(String(50), nullable=False)
    
    # Relationship
    relationship_type = Column(String(50), nullable=False, index=True)
    weight = Column(Float, nullable=True)
    attributes = Column(JSONB, nullable=False, default=dict)
    
    # Timestamps
    created_at = Column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        server_default=text("now()"),
    )
    valid_from = Column(DateTime(timezone=True), nullable=True)
    valid_until = Column(DateTime(timezone=True), nullable=True)
    
    # Indexes for graph traversal
    __table_args__ = (
        Index("ix_relationships_source", "source_entity_id"),
        Index("ix_relationships_target", "target_entity_id"),
        Index("ix_relationships_type", "tenant_id", "relationship_type"),
    )
