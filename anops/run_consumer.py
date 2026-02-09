"""
Entry point for the ANOps Detection Service (Consumer).

Listens to Kafka topics and processes metrics/events.
"""

import asyncio
import logging

from backend.app.core.database import engine, metrics_engine
from data_fabric.event_handlers import (
    handle_alarm_event,
    handle_metrics_event,
    handle_outcome_event,
)
from data_fabric.kafka_consumer import Topics, get_kafka_consumer

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def main():
    """Start the consumer service."""
    consumer = await get_kafka_consumer()
    
    # Register handlers
    # Alarm -> Decision Trigger
    consumer.register_handler("alarm", handle_alarm_event)
    
    # Metrics -> Anomaly Detection
    consumer.register_handler("metric", handle_metrics_event)
    
    # Outcome -> Feedback Loop
    consumer.register_handler("outcome", handle_outcome_event)
    
    logger.info("🚀 Starting ANOps Consumer Service...")
    await consumer.start()
    
    try:
        await consumer.consume()
    except KeyboardInterrupt:
        logger.info("🛑 Stopping consumer...")
    finally:
        await consumer.stop()
        await engine.dispose()
        await metrics_engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
