"""
ORM model for entity_relationships table.

Stores raw CMDB-declared relationships between network entities.
Populated by the tenant data loader (Step 2) from cmdb_declared_relationships.parquet.
Distinct from topology_relationships, which is used for live graph traversal.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, String
from sqlalchemy.dialects.postgresql import JSONB, UUID

from backend.app.core.database import Base


class EntityRelationshipORM(Base):
    """Raw CMDB-declared relationship between two network entities."""

    __tablename__ = "entity_relationships"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(String(100), nullable=False, index=True)

    source_entity_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    source_entity_type = Column(String(100), nullable=False)

    target_entity_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    target_entity_type = Column(String(100), nullable=False)

    relationship_type = Column(String(100), nullable=False, index=True)
    weight = Column(Float, nullable=True)
    attributes = Column(JSONB, nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
