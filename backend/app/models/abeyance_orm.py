"""
SQLAlchemy ORM models for the Abeyance Memory subsystem.

Remediated per Forensic Audit findings:
- Unified fragment model (eliminates split-brain, Audit §3.1)
- Fragment history for provenance (Audit §7.1, §7.2, §7.3)
- Snap decision records (Audit §7.1)
- Cluster snapshots (Audit §7.3)
- GIN indexes on JSONB columns (Audit §5.1)
- Tenant isolation on all tables (Audit §9.1, §9.2, §9.3)

Invariants enforced:
- INV-1: Fragment lifecycle via SnapStatus enum (deterministic state machine)
- INV-6: raw_content size bounded (64KB check at application layer)
- INV-7: tenant_id on every table, every index
- INV-10: fragment_history and snap_decision_record are append-only
"""

from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean, CheckConstraint, Column, DateTime, Float, Index, Integer, String, Text,
    UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from backend.app.core.database import Base


# ---------------------------------------------------------------------------
# Fragment Lifecycle State Machine (INV-1)
# ---------------------------------------------------------------------------
# Valid transitions:
#   INGESTED  -> ACTIVE        (enrichment complete)
#   ACTIVE    -> NEAR_MISS     (near-miss threshold crossed)
#   ACTIVE    -> SNAPPED       (snap threshold crossed)
#   NEAR_MISS -> SNAPPED       (snap threshold crossed)
#   NEAR_MISS -> ACTIVE        (decay resets near-miss status)
#   ACTIVE    -> STALE         (decay_score < stale_threshold)
#   NEAR_MISS -> STALE         (decay_score < stale_threshold)
#   STALE     -> EXPIRED       (decay_score < expiration_threshold)
#   EXPIRED   -> COLD          (archived to cold storage)
#   SNAPPED is terminal for automated processes (INV-5)
#
VALID_TRANSITIONS = {
    "INGESTED":  {"ACTIVE"},
    "ACTIVE":    {"NEAR_MISS", "SNAPPED", "STALE"},
    "NEAR_MISS": {"SNAPPED", "ACTIVE", "STALE"},
    "STALE":     {"EXPIRED"},
    "EXPIRED":   {"COLD"},
    "SNAPPED":   set(),  # Terminal — no automated exit (INV-5)
    "COLD":      set(),  # Terminal
}

# Maximum raw content size in bytes (INV-6)
MAX_RAW_CONTENT_BYTES = 65536


class AbeyanceFragmentORM(Base):
    """Core fragment storage — the sole canonical fragment model.

    Eliminates split-brain (Audit §3.1) by serving as the single source
    of truth for all abeyance state.  DecisionTraceORM abeyance fields
    are deprecated and must not be used for abeyance logic.
    """

    __tablename__ = "abeyance_fragment"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(String(100), nullable=False)

    # Source identification (LLD §5)
    source_type = Column(String(50), nullable=False)
    source_ref = Column(String(500), nullable=True)
    source_engineer_id = Column(String(255), nullable=True)

    # Raw content — bounded by MAX_RAW_CONTENT_BYTES (INV-6)
    raw_content = Column(Text, nullable=True)

    # Enrichment fields (LLD §6)
    extracted_entities = Column(JSONB, nullable=False, default=list, server_default='[]')
    topological_neighbourhood = Column(JSONB, nullable=False, default=dict, server_default='{}')
    operational_fingerprint = Column(JSONB, nullable=False, default=dict, server_default='{}')
    failure_mode_tags = Column(JSONB, nullable=False, default=list, server_default='[]')
    temporal_context = Column(JSONB, nullable=False, default=dict, server_default='{}')

    # --- v3.0 Four-Column Embedding Architecture (LLD v3.0 §2.5) ---
    emb_semantic = Column(Vector(1536), nullable=True)
    emb_topological = Column(Vector(1536), nullable=True)
    emb_temporal = Column(Vector(256), nullable=True)
    emb_operational = Column(Vector(1536), nullable=True)

    # Per-dimension validity masks (INV-11, INV-13)
    mask_semantic = Column(Boolean, nullable=False, default=False, server_default='false')
    mask_topological = Column(Boolean, nullable=False, default=False, server_default='false')
    mask_operational = Column(Boolean, nullable=False, default=False, server_default='false')
    # emb_temporal has no mask; sinusoidal encoding always succeeds

    # Operational polarity for conflict detection (Mechanism #6)
    polarity = Column(String(10), nullable=True)  # UP / DOWN / NEUTRAL

    # Schema version for dual-write migration (LLD v3.0 §5)
    embedding_schema_version = Column(Integer, nullable=False, default=3, server_default='3')

    # --- Legacy columns (retained for dual-write migration period, LLD v3.0 §5.3) ---
    # Embedding validity mask (v2 format)
    embedding_mask = Column(JSONB, nullable=False, default=lambda: [True, False, True, False],
                            server_default='[true, false, true, false]')
    # Embeddings (v2 format)
    enriched_embedding = Column(Vector(1536), nullable=True)
    raw_embedding = Column(Vector(768), nullable=True)

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

    # Decay and relevance (LLD §11, remediated per Audit §2.2)
    base_relevance = Column(Float, nullable=False, default=1.0, server_default='1.0')
    current_decay_score = Column(Float, nullable=False, default=1.0, server_default='1.0')
    near_miss_count = Column(Integer, nullable=False, default=0, server_default='0')

    # Fragment lifecycle (INV-1)
    snap_status = Column(
        String(20), nullable=False, default='INGESTED', server_default='INGESTED'
    )
    snapped_hypothesis_id = Column(UUID(as_uuid=True), nullable=True)

    # Hard lifetime bound (INV-6)
    max_lifetime_days = Column(Integer, nullable=False, default=730, server_default='730')

    # Deduplication key (Phase 7, §7.3)
    dedup_key = Column(String(500), nullable=True)

    __table_args__ = (
        Index("ix_abeyance_fragment_tenant_status", "tenant_id", "snap_status"),
        Index("ix_abeyance_fragment_tenant_created", "tenant_id", "created_at"),
        Index("ix_abeyance_fragment_tenant_decay", "tenant_id", "current_decay_score",
              postgresql_where="snap_status IN ('ACTIVE', 'NEAR_MISS')"),
        # GIN indexes for targeted retrieval (Audit §5.1, LLD §9)
        Index("ix_abeyance_fragment_failure_modes", "failure_mode_tags",
              postgresql_using="gin", postgresql_ops={"failure_mode_tags": "jsonb_path_ops"}),
        Index("ix_abeyance_fragment_entities", "extracted_entities",
              postgresql_using="gin", postgresql_ops={"extracted_entities": "jsonb_path_ops"}),
        # Deduplication (Phase 7, §7.3)
        UniqueConstraint("tenant_id", "dedup_key", name="uq_fragment_dedup"),
        # v3 CHECK constraints for mask/embedding coherence (INV-13)
        CheckConstraint(
            "emb_semantic IS NOT NULL OR mask_semantic = FALSE",
            name="ck_frag_mask_semantic",
        ),
        CheckConstraint(
            "emb_topological IS NOT NULL OR mask_topological = FALSE",
            name="ck_frag_mask_topological",
        ),
        CheckConstraint(
            "emb_operational IS NOT NULL OR mask_operational = FALSE",
            name="ck_frag_mask_operational",
        ),
    )


class FragmentEntityRefORM(Base):
    """Entity references with topological distance."""

    __tablename__ = "fragment_entity_ref"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    fragment_id = Column(UUID(as_uuid=True), nullable=False)
    entity_id = Column(UUID(as_uuid=True), nullable=True)
    entity_identifier = Column(String(500), nullable=False)
    entity_domain = Column(String(50), nullable=True)
    topological_distance = Column(Integer, nullable=False, default=0, server_default='0')
    tenant_id = Column(String(100), nullable=False)  # INV-7

    __table_args__ = (
        Index("ix_fer_entity_identifier_tenant", "entity_identifier", "tenant_id"),
        Index("ix_fer_fragment_tenant", "fragment_id", "tenant_id"),
        Index("ix_fer_entity_id_tenant", "entity_id", "tenant_id"),
    )


class AccumulationEdgeORM(Base):
    """Weak affinity links between fragments (LLD §10).

    Bounded per INV-9: MAX_EDGES_PER_FRAGMENT enforced at application layer.
    Tenant isolation per INV-7: tenant_id in pair uniqueness constraint.
    """

    __tablename__ = "accumulation_edge"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(String(100), nullable=False)  # INV-7
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
        # Tenant-scoped uniqueness (Audit §9.2)
        Index("ix_accum_edge_pair", "tenant_id", "fragment_a_id", "fragment_b_id", unique=True),
        Index("ix_accum_edge_frag_a", "tenant_id", "fragment_a_id"),
        Index("ix_accum_edge_frag_b", "tenant_id", "fragment_b_id"),
    )


# ---------------------------------------------------------------------------
# Provenance Tables (INV-10: append-only)
# ---------------------------------------------------------------------------

class FragmentHistoryORM(Base):
    """Append-only fragment state change log (Audit §7.2).

    Every mutation to a fragment's state is recorded here. Updates/deletes
    on this table are prohibited (enforced by DB trigger + application guard).
    """

    __tablename__ = "fragment_history"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    fragment_id = Column(UUID(as_uuid=True), nullable=False)
    tenant_id = Column(String(100), nullable=False)
    event_type = Column(String(30), nullable=False)
    # CREATED, ENRICHED, DECAY_UPDATE, NEAR_MISS, SNAPPED,
    # STALE, EXPIRED, COLD_ARCHIVED, BOOST_APPLIED
    event_timestamp = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
    )
    old_state = Column(JSONB, nullable=True)
    new_state = Column(JSONB, nullable=True)
    event_detail = Column(JSONB, nullable=True)

    __table_args__ = (
        Index("ix_fh_fragment_time", "fragment_id", "event_timestamp"),
        Index("ix_fh_tenant_time", "tenant_id", "event_timestamp"),
    )


class SnapDecisionRecordORM(Base):
    """Persisted snap evaluation record (LLD v3.0 §2.6).

    Stores the full scoring breakdown for every snap evaluation that
    reaches the scoring stage, regardless of outcome.
    v3: Five explicit per-dimension score columns (INV-14).
    """

    __tablename__ = "snap_decision_record"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(String(100), nullable=False)
    new_fragment_id = Column(UUID(as_uuid=True), nullable=False)
    candidate_fragment_id = Column(UUID(as_uuid=True), nullable=False)
    evaluated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
    )
    failure_mode_profile = Column(String(50), nullable=False)

    # v3: Five explicit per-dimension scores (INV-14)
    score_semantic = Column(Float, nullable=True)
    score_topological = Column(Float, nullable=True)
    score_temporal = Column(Float, nullable=True)
    score_operational = Column(Float, nullable=True)
    score_entity_overlap = Column(Float, nullable=False)

    # Mask and weight audit trail
    masks_active = Column(JSONB, nullable=False)
    weights_used = Column(JSONB, nullable=False)
    weights_base = Column(JSONB, nullable=True)  # Original profile weights for Outcome Calibration

    # Legacy v2 field (kept during migration)
    component_scores = Column(JSONB, nullable=True)

    raw_composite = Column(Float, nullable=False)
    temporal_modifier = Column(Float, nullable=False)
    final_score = Column(Float, nullable=False)
    threshold_applied = Column(Float, nullable=False)
    decision = Column(String(20), nullable=False)  # SNAP, NEAR_MISS, AFFINITY, NONE
    multiple_comparisons_k = Column(Integer, nullable=False, default=1)

    __table_args__ = (
        Index("ix_sdr_tenant_time", "tenant_id", "evaluated_at"),
        Index("ix_sdr_new_frag", "new_fragment_id"),
    )


class ClusterSnapshotORM(Base):
    """Persisted cluster evaluation record (Audit §7.3).

    Captures cluster membership and scoring at the moment of evaluation.
    """

    __tablename__ = "cluster_snapshot"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(String(100), nullable=False)
    evaluated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
    )
    member_fragment_ids = Column(JSONB, nullable=False)
    edges = Column(JSONB, nullable=False)
    cluster_score = Column(Float, nullable=False)
    correlation_discount = Column(Float, nullable=False)
    adjusted_score = Column(Float, nullable=False)
    threshold = Column(Float, nullable=False)
    decision = Column(String(20), nullable=False)  # SNAP, NO_SNAP

    __table_args__ = (
        Index("ix_cs_tenant_time", "tenant_id", "evaluated_at"),
    )


# ---------------------------------------------------------------------------
# Shadow Topology (LLD §8)
# ---------------------------------------------------------------------------

class ShadowEntityORM(Base):
    """PedkAI's private topology node."""

    __tablename__ = "shadow_entity"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(String(100), nullable=False)
    entity_identifier = Column(String(500), nullable=False)
    entity_domain = Column(String(50), nullable=True)
    origin = Column(String(30), nullable=False, default='CMDB_DECLARED', server_default='CMDB_DECLARED')
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
    """PedkAI's private topology edge."""

    __tablename__ = "shadow_relationship"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(String(100), nullable=False)
    from_entity_id = Column(UUID(as_uuid=True), nullable=False)
    to_entity_id = Column(UUID(as_uuid=True), nullable=False)
    relationship_type = Column(String(50), nullable=False)
    origin = Column(String(30), nullable=False, default='CMDB_DECLARED', server_default='CMDB_DECLARED')
    discovery_hypothesis_id = Column(UUID(as_uuid=True), nullable=True)
    confidence = Column(Float, nullable=False, default=1.0, server_default='1.0')
    discovered_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )
    evidence_summary = Column(JSONB, nullable=False, default=dict, server_default='{}')
    exported_to_cmdb = Column(Boolean, nullable=False, default=False, server_default='false')
    exported_at = Column(DateTime(timezone=True), nullable=True)
    cmdb_reference_tag = Column(String(255), nullable=True)

    __table_args__ = (
        Index("ix_shadow_rel_from_tenant", "from_entity_id", "tenant_id"),
        Index("ix_shadow_rel_to_tenant", "to_entity_id", "tenant_id"),
    )


class CmdbExportLogORM(Base):
    """Audit trail for CMDB exports."""

    __tablename__ = "cmdb_export_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(String(100), nullable=False)
    relationship_id = Column(UUID(as_uuid=True), nullable=True)
    entity_id = Column(UUID(as_uuid=True), nullable=True)
    export_type = Column(String(30), nullable=False)
    exported_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )
    exported_payload = Column(JSONB, nullable=False, default=dict, server_default='{}')
    retained_payload = Column(JSONB, nullable=False, default=dict, server_default='{}')
    cmdb_reference_tag = Column(String(255), nullable=True)


# ---------------------------------------------------------------------------
# Value Attribution (LLD §13)
# ---------------------------------------------------------------------------

class DiscoveryLedgerORM(Base):
    """Permanent record of every PedkAI discovery."""

    __tablename__ = "discovery_ledger"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(String(100), nullable=False, index=True)
    hypothesis_id = Column(UUID(as_uuid=True), nullable=True)
    discovery_type = Column(String(50), nullable=False)
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
    status = Column(String(20), nullable=False, default='ACTIVE', server_default='ACTIVE')

    __table_args__ = (
        Index("ix_discovery_entities_gin", "discovered_entities",
              postgresql_using="gin", postgresql_ops={"discovered_entities": "jsonb_path_ops"}),
    )


class ValueEventORM(Base):
    """Individual value realization event."""

    __tablename__ = "value_event"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(String(100), nullable=False, index=True)
    ledger_entry_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    event_type = Column(String(50), nullable=False)
    event_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )
    event_detail = Column(JSONB, nullable=False, default=dict, server_default='{}')
    attributed_value_hours = Column(Float, nullable=True)
    attributed_value_currency = Column(Float, nullable=True)
    attribution_rationale = Column(Text, nullable=True)
