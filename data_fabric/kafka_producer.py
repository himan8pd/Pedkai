"""
Kafka Producer for publishing decision events and metrics.
"""

import json
from typing import Optional

from aiokafka import AIOKafkaProducer

from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger

settings = get_settings()
logger = get_logger(__name__)


class KafkaEventProducer:
    """Async Kafka producer for publishing events."""
    
    def __init__(self):
        self.producer: Optional[AIOKafkaProducer] = None
    
    async def start(self):
        """Start the Kafka producer."""
        logger.info(f"Starting Kafka producer on {settings.kafka_bootstrap_servers}")
        self.producer = AIOKafkaProducer(
            bootstrap_servers=settings.kafka_bootstrap_servers,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )
        await self.producer.start()
        logger.info("Kafka producer started successfully")
    
    async def stop(self):
        """Stop the Kafka producer."""
        if self.producer:
            await self.producer.stop()
            logger.info("Kafka producer stopped")
    
    async def publish(self, topic: str, event: dict):
        """Publish an event to a Kafka topic."""
        if not self.producer:
            raise RuntimeError("Producer not started. Call start() first.")
        
        await self.producer.send_and_wait(topic, event)


# Topics definition
class Topics:
    """Kafka topic names."""
    ALARMS = "pedkai.alarms"
    DECISIONS = "pedkai.decisions"
    OUTCOMES = "pedkai.outcomes"
    METRICS = "pedkai.metrics"


# Singleton instance
_producer: Optional[KafkaEventProducer] = None


async def get_kafka_producer() -> KafkaEventProducer:
    """Get the Kafka producer singleton."""
    global _producer
    if _producer is None:
        _producer = KafkaEventProducer()
    return _producer


async def publish_event(topic: str, event: dict):
    """Helper function to publish an event using the singleton producer."""
    producer = await get_kafka_producer()
    if not producer.producer:
        await producer.start()
    await producer.publish(topic, event)
