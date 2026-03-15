"""
SQLAlchemy ORM models for the Abeyance Memory subsystem.

Implements the data model specified in ABEYANCE_MEMORY_LLD.md §5, §8, §10, §13, §14.
Maps to PostgreSQL with pgvector for semantic search and JSONB for flexible
enrichment storage.
"""

from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean, Column, DateTime, Float, Index, Integer, String, Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from backend.app.core.database import Base


class AbeyanceFragmentORM(Base):
    """Core fragment storage — the atomic unit of abeyance evidence.

    Implements LLD §5 (The Fragment Model) and §14 (Class Design).
    Each fragment represents a piece of evidence that enters Abeyance Memory,
    normalised with three faces: what it says, what it touches, and what was
    happening around it.
    """

    __tablename__ = "abeyance_fragment"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(String(100), nullable=False, index=True)

    # Source identification (LLD §5 Source Type Characteristics)
    source_type = Column(String(50), nullable=False)  # TICKET_TEXT, ALARM, TELEMETRY_EVENT, CLI_OUTPUT, CHANGE_RECORD, CMDB_DELTA
    source_ref = Column(String(500), nullable=True)  # Back-reference to originating record
    source_engineer_id = Column(String(255), nullable=True)

    # Raw content (Face 1 — what it says)
    raw_content = Column(Text, nullable=True)

    # Enrichment fields (LLD §6 Enrichment Chain outputs)
    extracted_entities = Column(JSONB, nullable=False, default=list, server_default='[]')
    topological_neighbourhood = Column(JSONB, nullable=False, default=dict, server_default='{}')
    operational_fingerprint = Column(JSONB, nullable=False, default=dict, server_default='{}')
    failure_mode_tags = Column(JSONB, nullable=False, default=list, server_default='[]')
    temporal_context = Column(JSONB, nullable=False, default=dict, server_default='{}')

    # Embeddings (LLD §6 Step 4 + §7)
    enriched_embedding = Column(Vector(1536), nullable=True)  # 512 semantic + 384 topo + 256 temporal + 384 operational
    raw_embedding = Column(Vector(768), nullable=True)  # Raw content only

    # Timestamps
    event_timestamp = Column(DateTime(timezone=True), nullable=True)
    ingestion_timestamp = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
    )
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
    )
    updated_at = Column(DateTime(timezone=True), nullable=True)

    # Decay and relevance (LLD §11)
    base_relevance = Column(Float, nullable=False, default=1.0, server_default='1.0')
    current_decay_score = Column(Float, nullable=False, default=1.0, server_default='1.0')
    near_miss_count = Column(Integer, nullable=False, default=0, server_default='0')

    # Snap status (LLD §5, §9)
    snap_status = Column(String(20), nullable=False, default='ABEYANCE', server_default='ABEYANCE')  # ABEYANCE | SNAPPED | EXPIRED | COLD
    snapped_hypothesis_id = Column(UUID(as_uuid=True), nullable=True)

    __table_args__ = (
        Index("ix_abeyance_fragment_tenant_status", "tenant_id", "snap_status"),
        Index("ix_abeyance_fragment_tenant_created", "tenant_id", "created_at"),
    )


class FragmentEntityRefORM(Base):
    """Entity references with topological distance.

    Implements LLD §5 (FRAGMENT_ENTITY_REF schema).
    Links fragments to network entities at varying topological distances
    (0 = directly referenced, 1 = 1-hop, 2 = 2-hop from Shadow Topology).
    """

    __tablename__ = "fragment_entity_ref"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    fragment_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    entity_id = Column(UUID(as_uuid=True), nullable=True)
    entity_identifier = Column(String(500), nullable=False)  # Human-readable: LTE-8842-A
    entity_domain = Column(String(50), nullable=True)  # RAN, TRANSPORT, CORE, IP, VNF, SITE
    topological_distance = Column(Integer, nullable=False, default=0, server_default='0')
    tenant_id = Column(String(100), nullable=False)

    __table_args__ = (
        Index("ix_fer_entity_identifier_tenant", "entity_identifier", "tenant_id"),
    )


class AccumulationEdgeORM(Base):
    """Weak affinity links between fragments in the Accumulation Graph.

    Implements LLD §10 (The Accumulation Graph) data model.
    Captures pairwise affinity scores that are below the snap threshold
    but above the affinity threshold, enabling multi-fragment cluster detection.
    """

    __tablename__ = "accumulation_edge"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(String(100), nullable=False, index=True)
    fragment_a_id = Column(UUID(as_uuid=True), nullable=False)
    fragment_b_id = Column(UUID(as_uuid=True), nullable=False)
    affinity_score = Column(Float, nullable=False)
    strongest_failure_mode = Column(String(50), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )
    last_updated = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )

    __table_args__ = (
        Index("ix_accum_edge_pair", "fragment_a_id", "fragment_b_id", unique=True),
    )


class ShadowEntityORM(Base):
    """PedkAI's private topology node.

    Implements LLD §8 (The Shadow Topology) SHADOW_ENTITY schema.
    Contains both CMDB-declared and PedkAI-discovered entities with
    enrichment metadata that is never exported to customer systems.
    """

    __tablename__ = "shadow_entity"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(String(100), nullable=False)
    entity_identifier = Column(String(500), nullable=False)  # Human-readable: LTE-8842-A
    entity_domain = Column(String(50), nullable=True)  # RAN, TRANSPORT, CORE, IP, VNF, SITE
    origin = Column(String(30), nullable=False, default='CMDB_DECLARED', server_default='CMDB_DECLARED')  # CMDB_DECLARED | PEDKAI_DISCOVERED | PEDKAI_CORRECTED
    discovery_hypothesis_id = Column(UUID(as_uuid=True), nullable=True)
    first_seen = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )
    last_evidence = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )
    attributes = Column(JSONB, nullable=False, default=dict, server_default='{}')
    cmdb_attributes = Column(JSONB, nullable=False, default=dict, server_default='{}')
    enrichment_value = Column(Float, nullable=False, default=0.0, server_default='0.0')

    __table_args__ = (
        Index("ix_shadow_entity_tenant_identifier", "tenant_id", "entity_identifier", unique=True),
    )


class ShadowRelationshipORM(Base):
    """PedkAI's private topology edge.

    Implements LLD §8 (The Shadow Topology) SHADOW_RELATIONSHIP schema.
    Evidence summary and scoring metadata are NEVER exported to customer
    CMDB — only sanitised CI/relationship data goes through the export adapter.
    """

    __tablename__ = "shadow_relationship"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(String(100), nullable=False)
    from_entity_id = Column(UUID(as_uuid=True), nullable=False)
    to_entity_id = Column(UUID(as_uuid=True), nullable=False)
    relationship_type = Column(String(50), nullable=False)  # serves | connects_to | depends_on | backed_by
    origin = Column(String(30), nullable=False, default='CMDB_DECLARED', server_default='CMDB_DECLARED')
    discovery_hypothesis_id = Column(UUID(as_uuid=True), nullable=True)
    confidence = Column(Float, nullable=False, default=1.0, server_default='1.0')
    discovered_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )
    evidence_summary = Column(JSONB, nullable=False, default=dict, server_default='{}')  # NEVER EXPORTED
    exported_to_cmdb = Column(Boolean, nullable=False, default=False, server_default='false')
    exported_at = Column(DateTime(timezone=True), nullable=True)
    cmdb_reference_tag = Column(String(255), nullable=True)

    __table_args__ = (
        Index("ix_shadow_rel_from", "from_entity_id", "tenant_id"),
        Index("ix_shadow_rel_to", "to_entity_id", "tenant_id"),
    )


class CmdbExportLogORM(Base):
    """Audit trail for Shadow Topology exports to customer CMDB.

    Implements LLD §8 CMDB_EXPORT_LOG schema.
    Records both what was sent to the CMDB (sanitised) and what was
    retained in the Shadow Topology (proprietary).
    """

    __tablename__ = "cmdb_export_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(String(100), nullable=False)
    relationship_id = Column(UUID(as_uuid=True), nullable=True)
    entity_id = Column(UUID(as_uuid=True), nullable=True)
    export_type = Column(String(30), nullable=False)  # NEW_CI | NEW_RELATIONSHIP | ATTRIBUTE_CORRECTION
    exported_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )
    exported_payload = Column(JSONB, nullable=False, default=dict, server_default='{}')
    retained_payload = Column(JSONB, nullable=False, default=dict, server_default='{}')
    cmdb_reference_tag = Column(String(255), nullable=True)


class DiscoveryLedgerORM(Base):
    """Value Attribution: permanent record of every PedkAI discovery.

    Implements LLD §13 (Value Attribution Methodology) DISCOVERY_LEDGER schema.
    Every hypothesis that reaches ACCEPTED status creates a ledger entry
    linking the discovery to affected entities and relationships.
    """

    __tablename__ = "discovery_ledger"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(String(100), nullable=False, index=True)
    hypothesis_id = Column(UUID(as_uuid=True), nullable=True)
    discovery_type = Column(String(50), nullable=False)  # DARK_NODE | DARK_EDGE | PHANTOM_CI | IDENTITY_MUTATION | DARK_ATTRIBUTE
    discovered_entities = Column(JSONB, nullable=False, default=list, server_default='[]')
    discovered_relationships = Column(JSONB, nullable=False, default=list, server_default='[]')
    cmdb_reference_tag = Column(String(255), nullable=True)
    discovered_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )
    cmdb_exported_at = Column(DateTime(timezone=True), nullable=True)
    discovery_confidence = Column(Float, nullable=False, default=0.0, server_default='0.0')
    status = Column(String(20), nullable=False, default='ACTIVE', server_default='ACTIVE')  # ACTIVE | SUPERSEDED | INVALIDATED


class ValueEventORM(Base):
    """Value Attribution: individual value realization event.

    Implements LLD §13 VALUE_EVENT schema.
    Tracks the ongoing business impact of PedkAI discoveries — MTTR savings,
    licence reclamations, outage prevention, and illumination credit.
    """

    __tablename__ = "value_event"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(String(100), nullable=False, index=True)
    ledger_entry_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    event_type = Column(String(50), nullable=False)  # INCIDENT_RESOLUTION | MTTR_REDUCTION | LICENCE_SAVING | OUTAGE_PREVENTION | DARK_GRAPH_REDUCTION
    event_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )
    event_detail = Column(JSONB, nullable=False, default=dict, server_default='{}')
    attributed_value_hours = Column(Float, nullable=True)
    attributed_value_currency = Column(Float, nullable=True)
    attribution_rationale = Column(Text, nullable=True)
