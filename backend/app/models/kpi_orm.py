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
    
    # Multi-tenant isolation (Part of Natural Primary Key)
    tenant_id = Column(String(255), primary_key=True)
    
    # Entity reference (Part of Natural Primary Key)
    entity_id = Column(String(255), primary_key=True)
    
    # Timestamp (Part of Natural Primary Key)
    timestamp = Column(
        DateTime(timezone=True),
        primary_key=True,
        default=datetime.utcnow,
        server_default=text("now()"),
        nullable=False,
    )
    
    # Metric details (Part of Natural Primary Key)
    metric_name = Column(String(100), primary_key=True)
    
    # Metric value
    value = Column(Float, nullable=False)
    
    # Additional context
    tags = Column(JSONB, nullable=False, default=dict)
    
    # Indexes are implicitly created for Primary Key, but we keep time-based ones for performance
    __table_args__ = (
        Index("ix_kpi_metrics_timestamp", "timestamp"),
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
        
        # Idempotency Fix: Ignore duplicates based on Primary Key 
        # (tenant_id, entity_id, metric_name, timestamp)
        stmt = stmt.on_conflict_do_nothing()
        
        await session.execute(stmt)
