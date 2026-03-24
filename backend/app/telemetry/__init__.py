"""
Telemetry Pipeline — Controlled replay and streaming ingestion.

This package provides:
- Canonical Kafka topic definitions (topics.py)
- Production-equivalent message schemas (schemas.py)
- Parquet → Kafka replay producer (replay_producer.py)
- Kafka → DB consumers with batched writes (kafka_consumers.py)

Architectural constraint: downstream systems are unaware whether telemetry
originates from historical Parquet replay or a live network stream.
"""
