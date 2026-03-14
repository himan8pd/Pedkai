"""
ORM model for reconciliation_results table.

Stores divergences discovered by the signal-based ReconciliationEngine
when comparing CMDB declared state against operational signals
(KPI telemetry, alarms, neighbour relations).
"""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, String, Text
from sqlalchemy.dialects.postgresql import JSONB

from backend.app.core.database import Base


class ReconciliationResultORM(Base):
    """Stores individual divergences discovered during reconciliation."""

    __tablename__ = "reconciliation_results"

    result_id = Column(String, primary_key=True)          # SHA256 hash of (tenant+type+target)
    tenant_id = Column(String, nullable=False, index=True)
    run_id = Column(String, nullable=False, index=True)   # Groups results per run

    # Divergence classification
    divergence_type = Column(String, nullable=False, index=True)
    # dark_node | phantom_node | dark_attribute | dark_edge | phantom_edge

    entity_or_relationship = Column(String)               # 'entity' | 'relationship'
    target_id = Column(String, index=True)                # entity/edge ID
    target_type = Column(String)                          # NR_CELL, GNODEB, etc.
    domain = Column(String, index=True)                   # mobile_ran, fixed_access, etc.

    # Description of the divergence
    description = Column(Text)

    # Attribute-level divergence details
    attribute_name = Column(String)
    cmdb_value = Column(Text)                             # What the CMDB declares
    observed_value = Column(Text)                         # What operational signals report

    # Evidence / scoring
    confidence = Column(Float, default=1.0)               # 0.0–1.0 (signal-derived)
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
    total_divergences = Column(String)
    dark_nodes = Column(String, default="0")
    phantom_nodes = Column(String, default="0")
    identity_mutations = Column(String, default="0")      # Kept for schema compat, always "0"
    dark_attributes = Column(String, default="0")
    dark_edges = Column(String, default="0")
    phantom_edges = Column(String, default="0")

    # Operational inventory
    cmdb_entity_count = Column(String, default="0")
    observed_entity_count = Column(String, default="0")   # Distinct entities in signals
    cmdb_edge_count = Column(String, default="0")
    observed_edge_count = Column(String, default="0")     # Neighbour relations count

    error_message = Column(Text)
    started_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime(timezone=True))
