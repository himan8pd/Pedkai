"""
In-Memory Event Bus (P1.6 — Phase 1).

Simple asyncio.Queue-based event bus for decoupled event publishing/subscription.
Serves as the internal message transport until Kafka integration in Phase 2.

Thread-Safe: asyncio.Queue is task-safe (not thread-safe).
Global Instance: Single queue shared across entire FastAPI application lifecycle.
"""
import asyncio
import logging
from typing import Any
from backend.app.events.schemas import BaseEvent

logger = logging.getLogger(__name__)

# Global event queue (single instance for entire application)
# This will be initialized in app startup
_event_bus: Any = None


def get_event_bus() -> asyncio.Queue:
    """
    Get the global event bus queue.
    
    Raises RuntimeError if bus not initialized.
    """
    global _event_bus
    if _event_bus is None:
        raise RuntimeError(
            "Event bus not initialized. Call initialize_event_bus() on app startup."
        )
    return _event_bus


def initialize_event_bus(maxsize: int = 10000) -> asyncio.Queue:
    """
    Initialize the global event bus (called during app startup).
    
    Args:
        maxsize: Maximum queue size (0 = unlimited)
    
    Returns:
        The initialized asyncio.Queue instance
    """
    global _event_bus
    _event_bus = asyncio.Queue(maxsize=maxsize)
    logger.info(f"Event bus initialized with maxsize={maxsize}")
    return _event_bus


async def publish_event(event: BaseEvent) -> None:
    """
    Publish an event to the bus.
    
    Args:
        event: Event to publish (must be BaseEvent subclass)
    
    Raises:
        asyncio.QueueFull: If queue is at capacity
        RuntimeError: If bus not initialized
    """
    bus = get_event_bus()
    try:
        bus.put_nowait(event)
        logger.debug(
            f"Event published: {event.event_type} (tenant={event.tenant_id}, "
            f"id={event.event_id[:8]}..., queue_size={bus.qsize()})"
        )
    except asyncio.QueueFull:
        logger.warning(
            f"Event bus full! Dropped event: {event.event_type} "
            f"(tenant={event.tenant_id}, id={event.event_id[:8]}...)"
        )
        raise


async def subscribe_events() -> BaseEvent:
    """
    Subscribe to events (blocking generator for worker loops).
    
    Yields:
        BaseEvent instances as they are published
    """
    bus = get_event_bus()
    while True:
        event = await bus.get()
        yield event
        bus.task_done()
