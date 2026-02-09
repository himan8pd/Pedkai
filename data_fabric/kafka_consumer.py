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

settings = get_settings()


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
    
    async def start(self):
        """Start the Kafka consumer."""
        self.consumer = AIOKafkaConsumer(
            *self.topics,
            bootstrap_servers=settings.kafka_bootstrap_servers,
            group_id=self.group_id,
            value_deserializer=lambda m: json.loads(m.decode("utf-8")),
            auto_offset_reset="earliest",
        )
        await self.consumer.start()
        self._running = True
        print(f"🎧 Kafka consumer started, listening on: {self.topics}")
    
    async def stop(self):
        """Stop the Kafka consumer."""
        self._running = False
        if self.consumer:
            await self.consumer.stop()
            print("👋 Kafka consumer stopped")
    
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
                    event_data = message.value
                    event_type = event_data.get("event_type", "unknown")
                    
                    if event_type in self._handlers:
                        await self._handlers[event_type](event_data)
                    else:
                        print(f"⚠️ No handler for event type: {event_type}")
                
                except Exception as e:
                    print(f"❌ Error processing message: {e}")
        
        except asyncio.CancelledError:
            print("Consumer cancelled")
        
        finally:
            await self.stop()


# Topics definition
class Topics:
    """Kafka topic names."""
    ALARMS = "pedkai.alarms"
    DECISIONS = "pedkai.decisions"
    OUTCOMES = "pedkai.outcomes"
    METRICS = "pedkai.metrics"


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
