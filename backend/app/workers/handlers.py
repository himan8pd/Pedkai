"""
Handler Registry for Pedkai Event Bus (P1.7).

Maps event types to handler functions. Handlers are coroutine functions
that consume events from the bus and perform domain-specific processing.

Phase 1: Simple logging handlers
Phase 2: Correlation, incident creation, anomaly detection handlers
Phase 3: Full orchestration pipeline
"""
import asyncio
import logging
from typing import Callable, Dict, Any
from datetime import datetime, timedelta, timezone

from backend.app.events.schemas import BaseEvent, AlarmIngestedEvent, AlarmClusterCreatedEvent
from backend.app.events.bus import publish_event
from backend.app.services.alarm_correlation import AlarmCorrelationService
from backend.app.core.database import async_session_maker

logger = logging.getLogger(__name__)

# Handler registry: event_type → handler function
_handlers: Dict[str, Callable] = {}

# In-memory buffers for P2.1: tenant_id -> {alarms: list, timer: Task|None, lock: asyncio.Lock}
_buffers: Dict[str, Dict[str, Any]] = {}

# Sliding window for correlation (seconds). Default 5 minutes.
_WINDOW_SECONDS = 5 * 60


def register_handler(event_type: str, handler: Callable) -> None:
    _handlers[event_type] = handler
    logger.info(f"Handler registered: {event_type} → {handler.__name__}")


def get_handler(event_type: str) -> Callable:
    return _handlers.get(event_type)


def has_handler(event_type: str) -> bool:
    return event_type in _handlers


async def handle_event(event: BaseEvent) -> None:
    """Dispatch event to registered handler."""
    handler = get_handler(event.event_type)
    if not handler:
        logger.debug(f"No handler for event type: {event.event_type}")
        return

    try:
        await handler(event)
        logger.debug(f"Event handled: {event.event_type} (id={event.event_id[:8]}...)")
    except Exception as e:
        logger.error(f"Handler failed for {event.event_type}: {e}", exc_info=True)


async def _flush_tenant(tenant_id: str) -> None:
    """Internal: correlate buffered alarms for a tenant and publish clusters."""
    buf = _buffers.get(tenant_id)
    if not buf:
        return

    async with buf["lock"]:
        alarms = buf.get("alarms", [])
        # Clear buffer and cancel timer reference
        buf["alarms"] = []
        t = buf.get("timer")
        if t and not t.done():
            try:
                t.cancel()
            except Exception:
                pass
        buf["timer"] = None

    if not alarms:
        logger.debug(f"No alarms to correlate for tenant {tenant_id}")
        return

    # Use correlation service (sync correlate_alarms) with session_factory
    try:
        svc = AlarmCorrelationService(session_factory=async_session_maker)
        clusters = svc.correlate_alarms(alarms)
        logger.info(f"Correlated {len(alarms)} alarms → {len(clusters)} clusters (tenant={tenant_id})")

        # Publish cluster events
        for cluster in clusters:
            import uuid as _uuid
            evt = AlarmClusterCreatedEvent(
                tenant_id=tenant_id,
                cluster_id=str(_uuid.uuid4()),
                alarm_count=cluster.get("alarm_count", 0),
                root_cause_entity_id=cluster.get("root_cause_entity_id"),
                severity=cluster.get("severity", "minor"),
                is_emergency_service=cluster.get("is_emergency_service", False),
            )
            await publish_event(evt)

    except Exception as e:
        logger.error(f"Error during correlation flush for tenant {tenant_id}: {e}", exc_info=True)


async def _schedule_flush(tenant_id: str) -> None:
    await asyncio.sleep(_WINDOW_SECONDS)
    await _flush_tenant(tenant_id)


async def alarm_ingested_handler(event: BaseEvent) -> None:
    """P2.1 handler: buffer alarms per-tenant, correlate on window close or size threshold."""
    if not isinstance(event, AlarmIngestedEvent):
        # Accept any BaseEvent that looks like an alarm
        try:
            # Best-effort mapping
            alarm = {
                "entity_id": getattr(event, "entity_id", None),
                "alarm_type": getattr(event, "alarm_type", None),
                "severity": getattr(event, "severity", "minor"),
                "raised_at": getattr(event, "raised_at", None),
                "entity_type": getattr(event, "entity_type", None),
                "is_emergency_service": getattr(event, "is_emergency_service", False),
            }
            tenant_id = getattr(event, "tenant_id", "default")
        except Exception:
            logger.debug("Received non-alarm event in alarm_ingested_handler; dropping")
            return
    else:
        alarm = event.dict()
        tenant_id = event.tenant_id

    # Ensure buffer exists
    if tenant_id not in _buffers:
        _buffers[tenant_id] = {"alarms": [], "timer": None, "lock": asyncio.Lock()}

    buf = _buffers[tenant_id]

    async with buf["lock"]:
        buf["alarms"].append(alarm)
        # If buffer exceeds threshold, flush immediately
        if len(buf["alarms"]) >= 100:
            logger.info(f"Buffer size >=100 for tenant {tenant_id}, flushing immediately")
            # cancel timer if present
            t = buf.get("timer")
            if t and not t.done():
                try:
                    t.cancel()
                except Exception:
                    pass
                buf["timer"] = None

            # Flush outside lock
            asyncio.create_task(_flush_tenant(tenant_id))
            return

        # Sliding window: cancel existing timer and reschedule
        t = buf.get("timer")
        if t and not t.done():
            try:
                t.cancel()
            except Exception:
                pass
        # Schedule new flush _WINDOW_SECONDS from now
        task = asyncio.create_task(_schedule_flush(tenant_id))
        buf["timer"] = task


# Register P2.1 handler (replaces earlier Phase-1 logger)
register_handler("alarm_ingested", alarm_ingested_handler)


async def flush_buffer(tenant_id: str) -> None:
    """Public helper for tests: force flush the tenant buffer now."""
    await _flush_tenant(tenant_id)


# P2.2: Alarm cluster -> incident creation handler registration
from backend.app.events.schemas import IncidentCreatedEvent
from backend.app.services.incident_service import create_incident_from_cluster
from backend.app.events.bus import publish_event
from backend.app.core.database import async_session_maker


async def _handle_alarm_cluster_created(event: BaseEvent) -> None:
    # Best-effort mapping
    data = getattr(event, 'dict', None)
    tenant_id = getattr(event, 'tenant_id', 'default')
    cluster_id = getattr(event, 'cluster_id', None) or getattr(event, 'event_id', None)

    # Determine primary entity (use root_cause_entity_id if present)
    entity_id = getattr(event, 'root_cause_entity_id', None)

    # Build IncidentCreate payload minimal fields
    from backend.app.schemas.incidents import IncidentCreate
    payload = IncidentCreate(
        tenant_id=tenant_id,
        title=f"Auto-created incident from cluster {cluster_id}",
        severity=getattr(event, 'severity', 'minor'),
        entity_id=entity_id,
        entity_external_id=None,
    )

    # Create incident using a DB session
    async with async_session_maker() as session:
        try:
            incident = await create_incident_from_cluster(payload, session, tenant_id=tenant_id)
            # Emit IncidentCreatedEvent
            evt = IncidentCreatedEvent(
                tenant_id=tenant_id,
                incident_id=incident.id,
                severity=incident.severity,
                entity_id=incident.entity_id,
                cluster_id=cluster_id,
            )
            await publish_event(evt)
        except Exception as e:
            logger.error(f"Failed to auto-create incident from cluster {cluster_id}: {e}", exc_info=True)


register_handler("alarm_cluster_created", _handle_alarm_cluster_created)
