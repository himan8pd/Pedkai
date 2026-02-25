"""
Background Event Consumer (P1.7).

Async task that runs alongside FastAPI on startup, consuming events
from the bus and dispatching to registered handlers.

Decouples event production (ingestion endpoint, sensors) from consumption
(correlation, incident creation, anomaly detection).
"""
import asyncio
import logging
from backend.app.events.bus import get_event_bus
from backend.app.workers.handlers import handle_event

logger = logging.getLogger(__name__)


async def event_consumer_loop() -> None:
    """
    Main event consumer loop.
    
    Infinite loop that:
    1. Waits for event from bus
    2. Dispatches to handler
    3. Marks event done
    4. Continues
    
    Runs as a background asyncio.Task, does not block API.
    """
    logger.info("🚀 Event consumer started")
    bus = get_event_bus()
    
    try:
        while True:
            try:
                # Wait for next event (blocks if queue empty)
                event = await bus.get()
                logger.debug(
                    f"Event dequeued: {event.event_type} "
                    f"(tenant={event.tenant_id}, id={event.event_id[:8]}..., "
                    f"queue_size={bus.qsize()})"
                )
                
                # Dispatch to handler
                await handle_event(event)
                
                # Mark as processed
                bus.task_done()
                
            except Exception as e:
                logger.error(f"Consumer loop error: {e}", exc_info=True)
                # Continue despite errors to avoid losing messages
                await asyncio.sleep(0.1)
    
    except asyncio.CancelledError:
        logger.info("Event consumer cancelled")
        raise


async def start_event_consumer() -> asyncio.Task:
    """
    Start the event consumer as a background task.
    
    Returns:
        The asyncio.Task running the consumer loop
    """
    task = asyncio.create_task(event_consumer_loop())
    try:
        # Give consumer a moment to start and check for initialization errors
        await asyncio.wait_for(asyncio.sleep(0.1), timeout=1.0)
    except asyncio.TimeoutError:
        pass  # Expected
    
    return task
