"""
Event bus and schemas for Pedkai platform.

Events enable decoupled, asynchronous communication between services.
All events are tenant-aware (tenant_id is mandatory) for strict isolation.

Phase 1 (current): In-memory asyncio.Queue
Phase 2: Kafka broker integration
Phase 3: Event sourcing and CQRS patterns
"""

from backend.app.events.schemas import (
    BaseEvent,
    AlarmIngestedEvent,
    SleepingCellDetectedEvent,
    AlarmClusterCreatedEvent,
    IncidentCreatedEvent,
)

__all__ = [
    "BaseEvent",
    "AlarmIngestedEvent",
    "SleepingCellDetectedEvent",
    "AlarmClusterCreatedEvent",
    "IncidentCreatedEvent",
]
