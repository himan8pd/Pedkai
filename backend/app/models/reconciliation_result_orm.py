"""
ORM model for reconciliation_results table.

Stores divergences discovered by the ReconciliationEngine when comparing
CMDB declared state against ground truth reality.
"""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, String, Text
from sqlalchemy.dialects.postgresql import JSONB

from backend.app.core.database import Base


class ReconciliationResultORM(Base):
    """Stores individual divergences discovered during reconciliation."""

    __tablename__ = "reconciliation_results"

    result_id = Column(String, primary_key=True)          # SHA256 hash of (tenant+from+to+type)
    tenant_id = Column(String, nullable=False, index=True)
    run_id = Column(String, nullable=False, index=True)   # Groups results per run

    # Divergence classification
    divergence_type = Column(String, nullable=False, index=True)
    # dark_node | phantom_node | identity_mutation | dark_attribute
    # dark_edge | phantom_edge

    entity_or_relationship = Column(String)               # 'entity' | 'relationship'
    target_id = Column(String, index=True)                # entity/edge ID
    target_type = Column(String)                          # NR_CELL, GNODEB, etc.
    domain = Column(String, index=True)                   # mobile_ran, fixed_access, etc.

    # Description of the divergence
    description = Column(Text)

    # Attribute-level divergence details
    attribute_name = Column(String)
    cmdb_value = Column(Text)
    ground_truth_value = Column(Text)

    # Identity mutation details
    cmdb_external_id = Column(Text)
    gt_external_id = Column(Text)

    # Evidence / scoring
    confidence = Column(Float, default=1.0)               # 0.0–1.0
    extra = Column(JSONB)                                  # Additional context

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class ReconciliationRunORM(Base):
    """Tracks each reconciliation run with summary statistics."""

    __tablename__ = "reconciliation_runs"

    run_id = Column(String, primary_key=True)
    tenant_id = Column(String, nullable=False, index=True)
    triggered_by = Column(String, default="manual")       # 'manual' | 'scheduled'
    status = Column(String, default="running")            # 'running' | 'complete' | 'error'

    # Summary counts
    total_divergences = Column(String)                    # Store as str to avoid None issues
    dark_nodes = Column(String, default="0")
    phantom_nodes = Column(String, default="0")
    identity_mutations = Column(String, default="0")
    dark_attributes = Column(String, default="0")
    dark_edges = Column(String, default="0")
    phantom_edges = Column(String, default="0")

    # Entity accuracy metrics
    cmdb_entity_count = Column(String, default="0")
    gt_entity_count = Column(String, default="0")
    confirmed_entity_count = Column(String, default="0")
    cmdb_edge_count = Column(String, default="0")
    gt_edge_count = Column(String, default="0")
    confirmed_edge_count = Column(String, default="0")

    # Scoring against pre-seeded manifest
    manifest_count = Column(String, default="0")
    detected_in_manifest = Column(String, default="0")
    recall_score = Column(Float)                          # detected / manifest
    precision_score = Column(Float)                       # manifest_hits / engine_total
    f1_score = Column(Float)

    error_message = Column(Text)
    started_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime(timezone=True))
