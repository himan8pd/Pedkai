"""
SQLAlchemy ORM model for KPI Metrics.

Stores time-series KPI data for anomaly detection and network performance monitoring.
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Column, DateTime, Float, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from backend.app.core.database import Base


class KPIMetricORM(Base):
    """
    SQLAlchemy ORM model for KPI Metrics.
    
    Designed for time-series storage of network metrics.
    """
    
    __tablename__ = "kpi_metrics"
    
    # Primary key
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    
    # Multi-tenant isolation
    tenant_id = Column(String(255), nullable=False, index=True)
    
    # Entity reference (cell site, node, customer, etc.)
    entity_id = Column(String(255), nullable=False, index=True)
    
    # Timestamp
    timestamp = Column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        server_default=text("now()"),
        nullable=False,
        index=True,
    )
    
    # Metric details
    metric_name = Column(String(100), nullable=False, index=True)
    value = Column(Float, nullable=False)
    
    # Additional context
    tags = Column(JSONB, nullable=False, default=dict)
    
    # Indexes for time-aware queries
    __table_args__ = (
        Index("ix_kpi_metrics_entity_metric_time", "entity_id", "metric_name", "timestamp"),
        Index("ix_kpi_metrics_tenant_time", "tenant_id", "timestamp"),
    )
    
    def __repr__(self) -> str:
        return f"<KPIMetric(entity={self.entity_id}, metric={self.metric_name}, value={self.value})>"

    @staticmethod
    async def bulk_insert(session, metrics_list: list):
        """
        Performs a batch insertion of metrics for high-volume ingestion.
        """
        from sqlalchemy.dialects.postgresql import insert
        
        if not metrics_list:
            return
            
        stmt = insert(KPIMetricORM).values(metrics_list)
        # In a real TSDB transition, we might use: 
        # stmt = stmt.on_conflict_do_nothing() 
        # or similar for idempotency if metrics are replayed.
        
        await session.execute(stmt)
