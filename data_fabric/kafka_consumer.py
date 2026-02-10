"""
Kafka Consumer for Decision Events.

Consumes events from Kafka topics and creates decision traces.
Events can come from:
- Alarm systems
- Ticketing systems
- Manual operator actions
- Automated decision systems
"""

import asyncio
import json
from typing import Callable, Optional

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger
from data_fabric.alarm_normalizer import AlarmNormalizer

settings = get_settings()
logger = get_logger(__name__)


class KafkaEventConsumer:
    """Async Kafka consumer for decision-related events."""
    
    def __init__(
        self,
        topics: list[str],
        group_id: Optional[str] = None,
    ):
        self.topics = topics
        self.group_id = group_id or settings.kafka_consumer_group
        self.consumer: Optional[AIOKafkaConsumer] = None
        self._running = False
        self._handlers: dict[str, Callable] = {}
        self.normalizer = AlarmNormalizer()
    
    async def start(self):
        """Start the Kafka consumer."""
        logger.info(f"Starting Kafka consumer for topics: {self.topics}")
        self.consumer = AIOKafkaConsumer(
            *self.topics,
            bootstrap_servers=settings.kafka_bootstrap_servers,
            group_id=self.group_id,
            value_deserializer=lambda m: json.loads(m.decode("utf-8")),
            auto_offset_reset="earliest",
        )
        await self.consumer.start()
        self._running = True
        logger.info("Kafka consumer started successfully")
    
    async def stop(self):
        """Stop the Kafka consumer."""
        self._running = False
        if self.consumer:
            await self.consumer.stop()
            logger.info("Kafka consumer stopped")
    
    def register_handler(self, event_type: str, handler: Callable):
        """Register a handler function for a specific event type."""
        self._handlers[event_type] = handler
    
    async def consume(self):
        """
        Main consume loop.
        
        Reads messages and dispatches to registered handlers.
        """
        if not self.consumer:
            raise RuntimeError("Consumer not started. Call start() first.")
        
        try:
            async for message in self.consumer:
                if not self._running:
                    break
                
                try:
                    raw_event = message.value
                    
                    # Phase 3: Check for vendor-specific signatures
                    vendor = "generic"
                    if isinstance(raw_event, str) and "<alarmEvent>" in raw_event:
                        vendor = "ericsson"
                    elif isinstance(raw_event, dict) and "sourceIndicator" in raw_event:
                        vendor = "nokia"
                        
                    # Normalize if it's external vendor data
                    if vendor != "generic":
                        event_data = self.normalizer.normalize(raw_event, vendor)
                        event_type = "alarm" # Standard dispatcher type
                    else:
                        event_data = raw_event
                        event_type = event_data.get("event_type", "unknown")
                    
                    if event_type in self._handlers:
                        await self._handlers[event_type](event_data)
                    else:
                        logger.warning(f"No handler for event type: {event_type}")
                
                except Exception as e:
                    logger.error(f"Error processing message: {e}", exc_info=True)
        
        except asyncio.CancelledError:
            logger.info("Consumer cancelled")
        
        finally:
            await self.stop()


# Topics are now imported from data_fabric.kafka_producer
from data_fabric.kafka_producer import Topics


# Singleton instances
_consumer: Optional[KafkaEventConsumer] = None


async def get_kafka_consumer() -> KafkaEventConsumer:
    """Get the Kafka consumer singleton."""
    global _consumer
    if _consumer is None:
        _consumer = KafkaEventConsumer(
            topics=[Topics.ALARMS, Topics.OUTCOMES, Topics.METRICS]
        )
    return _consumer
