"""
ORM Models for Network Entities (Phase 1.1).

Stores physical and logical network entities: sites, cells, routers, emergency service locations, etc.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, Index, String
from sqlalchemy.dialects.postgresql import JSONB, UUID

from backend.app.core.database import Base


class NetworkEntityORM(Base):
    """
    Represents a network entity (site, cell, gNodeB, emergency service location, etc.).

    Used for topology queries, impact analysis, and entity-scoped KPI tracking.
    """

    __tablename__ = "network_entities"

    # Primary Key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Tenancy
    tenant_id = Column(String(50), nullable=False, index=True)

    # Entity Classification
    entity_type = Column(
        String(50),
        nullable=False,
        index=True,
        # Valid types: SITE, GNODEB, CELL, SECTOR, ROUTER, SWITCH, EMERGENCY_SERVICE
    )

    # Identity
    name = Column(String(255), nullable=False)
    external_id = Column(
        String(255),
        nullable=True,
        index=True,
        # Vendor-provided NMS identifier (e.g. from Nokia NetAct, Ericsson ENM)
    )

    # Geography — DB columns are 'latitude'/'longitude', ORM attributes stay 'geo_lat'/'geo_lon'
    geo_lat = Column("latitude", Float, nullable=True, key="geo_lat")
    geo_lon = Column("longitude", Float, nullable=True, key="geo_lon")

    # Operational status (present in DB, was missing from ORM)
    operational_status = Column(String(50), nullable=True)

    # Rich domain metadata (present in DB as JSONB, was missing from ORM)
    attributes = Column(JSONB, nullable=True, default=dict)

    # Business Metadata
    # NOTE: These columns do NOT yet exist in the Telco2 DB. They are kept nullable
    # so that SQLAlchemy does not fail for tenants that have had ALTER TABLE run.
    # For Telco2, these will be NULL. Run the ALTER TABLE statements from
    # docs/TELCO2_IMPLEMENTATION_BRIEF.md item #6 to add them to the DB.
    revenue_weight = Column(
        Float,
        nullable=True,
        # Estimated monthly revenue flowing through this entity (for impact weighting)
    )
    sla_tier = Column(
        String(50),
        nullable=True,
        # SLA category: GOLD, SILVER, BRONZE (affects escalation priority)
    )

    # Embedding Configuration (for decision memory context injection)
    embedding_provider = Column(
        String(50),
        nullable=True,
        # e.g., "gemini", "minilm", "openai" (allows per-entity model selection)
    )
    embedding_model = Column(
        String(100),
        nullable=True,
        # e.g., "text-embedding-004", "all-minilm-l6-v2"
    )

    # Metadata
    last_seen_at = Column(DateTime, nullable=True)  # Last activity timestamp
    created_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at = Column(DateTime, nullable=True)  # Present in DB, was missing from ORM

    def __repr__(self) -> str:
        return f"NetworkEntityORM(id={self.id}, type={self.entity_type}, name={self.name}, tenant_id={self.tenant_id})"
