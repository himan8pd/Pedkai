"""
ORM Models for KPI Samples (Phase 1.3).

Stores structured time-series KPI measurements for network entities.
Enables efficient querying of historical KPI values for impact analysis and anomaly detection.
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Float, DateTime, Index, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from backend.app.core.database import Base


class KpiSampleORM(Base):
    """
    Represents a single KPI measurement for a network entity at a point in time.
    
    Enables time-series queries like:
    - "What was PRB utilization for cell X between T1 and T2?"
    - "What is the 30-day rolling average latency for site Y?"
    - "Which entities had anomalous KPI values in the last hour?"
    
    Used for anomaly detection baselines, impact analysis context injection, and SLA tracking.
    """
    __tablename__ = "kpi_samples"

    # Primary Key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Tenancy
    tenant_id = Column(String(50), nullable=False, index=True)
    
    # Entity Reference (FK to network_entities)
    entity_id = Column(
        UUID(as_uuid=True),
        ForeignKey("network_entities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    
    # Metric Identity
    metric_name = Column(
        String(100),
        nullable=False,
        index=True,
        # Valid metric names: PRB_UTIL, LATENCY_MS, CONGESTION_RATE, BANDWIDTH_UTIL,
        # CONNECTION_COUNT, DISCONNECTION_RATE, SIGNALING_LOAD, THROUGHPUT_MBPS, etc.
    )
    
    # Measurement
    value = Column(
        Float,
        nullable=False,
        # Unitless; interpretation depends on metric_name
        # PRB_UTIL: 0-100 (percent)
        # LATENCY_MS: milliseconds
        # BANDWIDTH_UTIL: 0-100 (percent)
        # CONNECTION_COUNT: integer count (as float for time-series)
    )
    
    # Temporal Metadata
    timestamp = Column(
        DateTime(timezone=True),
        nullable=False,
        # UTC timestamp when measurement was taken
    )
    
    # Source System
    source = Column(
        String(50),
        nullable=False,
        # Origin system identifier (e.g., 'RAN_TELEMETRY', 'BSS', 'EXTERNAL_API', 'SYNTHETIC_TEST')
    )
    
    # Composite indexes for efficient time-series range queries
    __table_args__ = (
        # Primary query pattern: (entity, metric, time DESC) for recent values
        Index('ix_kpi_entity_metric_time', 'entity_id', 'metric_name', 'timestamp'),
        # Aggregation pattern: tenant filtering first for multi-tenancy
        Index('ix_kpi_tenant_entity_metric', 'tenant_id', 'entity_id', 'metric_name'),
    )
    
    def __repr__(self) -> str:
        return f"KpiSampleORM(entity={self.entity_id}, metric={self.metric_name}, value={self.value}, ts={self.timestamp})"
