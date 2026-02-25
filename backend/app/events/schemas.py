"""
Event Schema Definitions for Pedkai Event Bus (P1.5).

All events follow a canonical schema with mandatory tenant_id field
to ensure tenant isolation across the event processing pipeline.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field


class BaseEvent(BaseModel):
    """
    Base event schema with mandatory tenant isolation fields.
    
    All domain events in Pedkai MUST extend this class to ensure:
    - Unique event tracking (event_id, trace_id)
    - Tenant isolation (tenant_id is REQUIRED, no default)
    - Temporal tracking (timestamp)
    - Event categorization (event_type)
    """
    
    event_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique event identifier (UUID)"
    )
    
    tenant_id: str = Field(
        ...,  # Required, no default
        description="Tenant identifier for isolation. Must be provided at event creation."
    )
    
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when event was created"
    )
    
    event_type: str = Field(
        description="Event type discriminator (e.g., 'alarm_ingested', 'incident_created')"
    )
    
    trace_id: Optional[str] = Field(
        default=None,
        description="Distributed trace ID for cross-service correlation (OpenTelemetry)"
    )
    
    class Config:
        """Pydantic config for event models."""
        use_enum_values = True


class AlarmIngestedEvent(BaseEvent):
    """
    Event emitted when a new alarm is ingested from an external source.
    
    Used by P1.6 alarm_ingestion endpoint and P2.1 alarm correlation handler.
    """
    
    event_type: str = Field(default="alarm_ingested", frozen=True)
    
    entity_id: str = Field(
        description="UUID of the network entity that triggered the alarm"
    )
    
    entity_external_id: Optional[str] = Field(
        default=None,
        description="External system identifier for the entity"
    )
    
    alarm_type: str = Field(
        description="Alarm category (e.g., 'LINK_DOWN', 'CELL_DEGRADATION', 'POWER_SUPPLY')"
    )
    
    severity: str = Field(
        description="Severity level: minor, major, or critical"
    )
    
    raised_at: datetime = Field(
        description="Timestamp when alarm was raised (may precede ingestion)"
    )
    
    source_system: str = Field(
        description="Origin system (e.g., 'oss_vendor', 'snmp', 'manual')"
    )


class SleepingCellDetectedEvent(BaseEvent):
    """
    Event emitted when a cell stops sending KPI updates (anomaly detection).
    
    Used by P2.4 sleeping cell detector for proactive monitoring.
    """
    
    event_type: str = Field(default="sleeping_cell_detected", frozen=True)
    
    entity_id: str = Field(
        description="UUID of the cell/sector that stopped reporting"
    )
    
    z_score: float = Field(
        description="Statistical deviation from baseline (-3.0 indicates 3 std devs below mean)"
    )
    
    baseline_mean: float = Field(
        description="Historical 7-day mean for comparison"
    )
    
    current_value: Optional[float] = Field(
        default=None,
        description="Latest observed value (if present)"
    )
    
    metric_name: str = Field(
        description="KPI metric being monitored (e.g., 'traffic_volume', 'latency_ms')"
    )


class AlarmClusterCreatedEvent(BaseEvent):
    """
    Event emitted when alarms are correlated into a cluster.
    
    Used by P2.1 to trigger incident creation.
    """
    
    event_type: str = Field(default="alarm_cluster_created", frozen=True)
    
    cluster_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique cluster identifier"
    )
    
    alarm_count: int = Field(
        description="Number of alarms in this cluster"
    )
    
    root_cause_entity_id: Optional[str] = Field(
        default=None,
        description="Most likely root cause entity"
    )
    
    severity: str = Field(
        description="Highest severity alarm in cluster"
    )
    
    is_emergency_service: bool = Field(
        default=False,
        description="Whether cluster affects emergency services"
    )


class IncidentCreatedEvent(BaseEvent):
    """
    Event emitted when an incident is auto-created from alarms.
    
    Used by P2.2 incident creation handler.
    """
    
    event_type: str = Field(default="incident_created", frozen=True)
    
    incident_id: str = Field(
        description="Unique incident identifier"
    )
    
    severity: str = Field(
        description="Incident severity"
    )
    
    entity_id: Optional[str] = Field(
        default=None,
        description="Primary affected entity"
    )
    
    cluster_id: Optional[str] = Field(
        default=None,
        description="Associated alarm cluster ID"
    )
