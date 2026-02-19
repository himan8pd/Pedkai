from datetime import datetime, timezone
import uuid
from sqlalchemy import Column, String, ForeignKey, DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import text
from backend.app.core.database import Base

class EntityRelationshipORM(Base):
    """
    Represents the Network Topology Graph (The "Context Graph").
    Used for RCA graph traversal and CX impact correlation.
    """
    __tablename__ = "topology_relationships"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Source Entity (e.g., "Cell-001")
    from_entity_id = Column(String(255), nullable=False, index=True)
    from_entity_type = Column(String(50), nullable=False) # e.g., "cell", "router"

    # Relationship Type (e.g., "connected_to", "powers", "serves")
    relationship_type = Column(String(50), nullable=False)

    # Target Entity (e.g., "Router-B")
    to_entity_id = Column(String(255), nullable=False, index=True)
    to_entity_type = Column(String(50), nullable=False)

    # Multi-tenant isolation (Phase 15.3)
    tenant_id = Column(String(50), nullable=False, index=True)

    # Metadata (e.g., "fiber", "microwave", "10Gbps")
    properties = Column(String, nullable=True) # JSON or string for simplicity

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), server_default=func.now(), nullable=False)
