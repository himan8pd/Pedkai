"""Data Fabric package - Event streaming and ingestion."""

from data_fabric.kafka_consumer import (
    KafkaEventConsumer,
    KafkaEventProducer,
    Topics,
    get_kafka_consumer,
    get_kafka_producer,
)
from data_fabric.event_handlers import (
    handle_alarm_event,
    handle_outcome_event,
    handle_metrics_event,
)

__all__ = [
    "KafkaEventConsumer",
    "KafkaEventProducer",
    "Topics",
    "get_kafka_consumer",
    "get_kafka_producer",
    "handle_alarm_event",
    "handle_outcome_event",
    "handle_metrics_event",
]
