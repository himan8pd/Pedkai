"""
Kafka Consumers for telemetry ingestion.

Consumes from domain-specific telemetry topics and writes to TimescaleDB
with batched inserts for efficiency.

These consumers are agnostic to the telemetry source — they work identically
whether the producer is the Parquet replay service or a live network feed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

from backend.app.core.config import get_settings
from backend.app.telemetry.topics import TelemetryTopics

logger = logging.getLogger(__name__)
settings = get_settings()

# SQL for creating the telemetry hypertable (idempotent)
_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS telemetry_records (
    tenant_id   VARCHAR(100)    NOT NULL,
    entity_id   VARCHAR(255)    NOT NULL,
    timestamp   TIMESTAMPTZ     NOT NULL,
    domain      VARCHAR(50)     NOT NULL,
    entity_type VARCHAR(50),
    metrics     JSONB           NOT NULL,
    PRIMARY KEY (tenant_id, entity_id, timestamp, domain)
);
"""

_CREATE_HYPERTABLE_SQL = """
SELECT create_hypertable(
    'telemetry_records', 'timestamp',
    if_not_exists => TRUE,
    migrate_data  => TRUE
);
"""

_CREATE_INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS ix_telemetry_domain_ts ON telemetry_records (domain, timestamp DESC);",
    "CREATE INDEX IF NOT EXISTS ix_telemetry_tenant_entity ON telemetry_records (tenant_id, entity_id, timestamp DESC);",
]

_ENABLE_COMPRESSION_SQL = """
ALTER TABLE telemetry_records SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'tenant_id, domain, entity_id',
    timescaledb.compress_orderby = 'timestamp DESC'
);
"""

_ADD_COMPRESSION_POLICY_SQL = """
SELECT add_compression_policy('telemetry_records', INTERVAL '2 days', if_not_exists => true);
"""

_ADD_RETENTION_POLICY_SQL = """
SELECT add_retention_policy('telemetry_records', INTERVAL '{days} days', if_not_exists => true);
"""

# Alarms table (mirrors events_alarms Parquet schema)
_CREATE_ALARMS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS telemetry_alarms (
    alarm_id            VARCHAR(255)    NOT NULL,
    tenant_id           VARCHAR(100)    NOT NULL,
    entity_id           VARCHAR(255)    NOT NULL,
    entity_type         VARCHAR(50),
    alarm_type          VARCHAR(100)    NOT NULL,
    severity            VARCHAR(20)     NOT NULL,
    raised_at           TIMESTAMPTZ     NOT NULL,
    cleared_at          TIMESTAMPTZ,
    source_system       VARCHAR(100),
    probable_cause      TEXT,
    domain              VARCHAR(50),
    additional_text     TEXT,
    correlation_group_id VARCHAR(255),
    PRIMARY KEY (tenant_id, alarm_id)
);
"""

_CREATE_ALARM_INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS ix_alarm_raised ON telemetry_alarms (raised_at DESC);",
    "CREATE INDEX IF NOT EXISTS ix_alarm_entity ON telemetry_alarms (tenant_id, entity_id, raised_at DESC);",
    "CREATE INDEX IF NOT EXISTS ix_alarm_severity ON telemetry_alarms (severity, raised_at DESC);",
]

# Upsert for telemetry records
_UPSERT_TELEMETRY_SQL = """
INSERT INTO telemetry_records (tenant_id, entity_id, timestamp, domain, entity_type, metrics)
VALUES (:tenant_id, :entity_id, :timestamp, :domain, :entity_type, :metrics)
ON CONFLICT (tenant_id, entity_id, timestamp, domain) DO NOTHING;
"""

# Upsert for alarms
_UPSERT_ALARM_SQL = """
INSERT INTO telemetry_alarms (
    alarm_id, tenant_id, entity_id, entity_type, alarm_type, severity,
    raised_at, cleared_at, source_system, probable_cause, domain,
    additional_text, correlation_group_id
) VALUES (
    :alarm_id, :tenant_id, :entity_id, :entity_type, :alarm_type, :severity,
    :raised_at, :cleared_at, :source_system, :probable_cause, :domain,
    :additional_text, :correlation_group_id
) ON CONFLICT (tenant_id, alarm_id) DO NOTHING;
"""

# Domain mapping from topic to domain label
_TOPIC_TO_DOMAIN = {
    TelemetryTopics.RAN_KPI: "ran",
    TelemetryTopics.TRANSPORT_KPI: "transport",
    TelemetryTopics.FIXED_BROADBAND_KPI: "fixed_broadband",
    TelemetryTopics.CORE_KPI: "core",
    TelemetryTopics.ENTERPRISE_KPI: "enterprise",
    TelemetryTopics.POWER_KPI: "power",
}

# Entity ID column per topic (same as topics.py but for consumer-side)
_TOPIC_ENTITY_COL = {
    TelemetryTopics.RAN_KPI: "cell_id",
    TelemetryTopics.TRANSPORT_KPI: "entity_id",
    TelemetryTopics.FIXED_BROADBAND_KPI: "entity_id",
    TelemetryTopics.CORE_KPI: "entity_id",
    TelemetryTopics.ENTERPRISE_KPI: "entity_id",
    TelemetryTopics.POWER_KPI: "site_id",
}

# Columns to exclude from the metrics JSONB (they're stored as top-level columns)
_META_COLUMNS = {
    "tenant_id", "entity_id", "cell_id", "site_id", "timestamp",
    "entity_type", "domain", "raised_at",
}


async def initialize_telemetry_tables() -> None:
    """
    Create telemetry tables and hypertables in TimescaleDB.

    Safe to call multiple times (idempotent).
    """
    from sqlalchemy import text

    from backend.app.core.database import metrics_session_maker

    async with metrics_session_maker() as session:
        # Create tables
        await session.execute(text(_CREATE_TABLE_SQL))
        await session.execute(text(_CREATE_ALARMS_TABLE_SQL))
        await session.commit()

        # Create hypertable
        try:
            await session.execute(text(_CREATE_HYPERTABLE_SQL))
            await session.commit()
        except Exception as e:
            await session.rollback()
            # Hypertable may already exist
            if "already a hypertable" not in str(e).lower():
                logger.warning("Hypertable creation note: %s", e)

        # Create indexes
        for idx_sql in _CREATE_INDEXES_SQL + _CREATE_ALARM_INDEXES_SQL:
            await session.execute(text(idx_sql))
        await session.commit()

        # Enable compression
        try:
            await session.execute(text(_ENABLE_COMPRESSION_SQL))
            await session.execute(text(_ADD_COMPRESSION_POLICY_SQL))
            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.warning("Compression setup note: %s", e)

        # Retention policy (if configured)
        retention_days = settings.timescale_retention_days
        if retention_days > 0:
            try:
                await session.execute(
                    text(_ADD_RETENTION_POLICY_SQL.format(days=retention_days))
                )
                await session.commit()
                logger.info("Retention policy: %d days", retention_days)
            except Exception as e:
                await session.rollback()
                logger.warning("Retention policy note: %s", e)

    logger.info("Telemetry tables initialized in TimescaleDB")


def _parse_kpi_message(msg: dict[str, Any], topic: str) -> dict[str, Any] | None:
    """Parse a KPI telemetry message into a DB row dict."""
    domain = _TOPIC_TO_DOMAIN.get(topic)
    if not domain:
        return None

    entity_col = _TOPIC_ENTITY_COL.get(topic, "entity_id")
    entity_id = msg.get(entity_col)
    tenant_id = msg.get("tenant_id")
    timestamp = msg.get("timestamp")

    if not entity_id or not tenant_id or not timestamp:
        return None

    # Extract entity_type if present
    entity_type = msg.get("entity_type") or msg.get("rat_type") or msg.get("site_type")

    # Build metrics JSONB — everything except meta columns
    metrics = {}
    for k, v in msg.items():
        if k not in _META_COLUMNS and v is not None:
            metrics[k] = v

    return {
        "tenant_id": tenant_id,
        "entity_id": str(entity_id),
        "timestamp": timestamp,
        "domain": domain,
        "entity_type": entity_type,
        "metrics": json.dumps(metrics),
    }


def _parse_alarm_message(msg: dict[str, Any]) -> dict[str, Any] | None:
    """Parse an alarm message into a DB row dict."""
    alarm_id = msg.get("alarm_id")
    tenant_id = msg.get("tenant_id")
    entity_id = msg.get("entity_id")
    raised_at = msg.get("raised_at")

    if not alarm_id or not tenant_id or not entity_id or not raised_at:
        return None

    return {
        "alarm_id": alarm_id,
        "tenant_id": tenant_id,
        "entity_id": entity_id,
        "entity_type": msg.get("entity_type"),
        "alarm_type": msg.get("alarm_type", "UNKNOWN"),
        "severity": msg.get("severity", "minor"),
        "raised_at": raised_at,
        "cleared_at": msg.get("cleared_at"),
        "source_system": msg.get("source_system"),
        "probable_cause": msg.get("probable_cause"),
        "domain": msg.get("domain"),
        "additional_text": msg.get("additional_text"),
        "correlation_group_id": msg.get("correlation_group_id"),
    }


class TelemetryConsumer:
    """
    Kafka consumer for telemetry topics with batched DB writes.

    Consumes from all telemetry topics, accumulates messages in memory,
    and flushes to TimescaleDB in batches for efficiency.
    """

    def __init__(
        self,
        bootstrap_servers: str | None = None,
        group_id: str | None = None,
        batch_size: int | None = None,
        flush_interval: float | None = None,
    ):
        self.bootstrap_servers = bootstrap_servers or settings.kafka_bootstrap_servers
        self.group_id = group_id or settings.telemetry_consumer_group
        self.batch_size = batch_size or settings.consumer_batch_size
        self.flush_interval = flush_interval or settings.consumer_flush_interval_seconds
        self._consumer = None
        self._running = False
        self._kpi_buffer: list[dict[str, Any]] = []
        self._alarm_buffer: list[dict[str, Any]] = []
        self._last_flush = time.monotonic()
        self._total_consumed = 0
        self._total_written = 0

    async def start(self) -> None:
        """Initialize the Kafka consumer and connect."""
        from aiokafka import AIOKafkaConsumer

        topics = TelemetryTopics.all_topics()
        self._consumer = AIOKafkaConsumer(
            *topics,
            bootstrap_servers=self.bootstrap_servers,
            group_id=self.group_id,
            value_deserializer=lambda m: json.loads(m.decode("utf-8")),
            auto_offset_reset="earliest",
            enable_auto_commit=True,
            max_poll_records=self.batch_size,
        )
        await self._consumer.start()
        self._running = True
        logger.info(
            "Telemetry consumer started: topics=%s, group=%s",
            topics,
            self.group_id,
        )

    async def stop(self) -> None:
        """Flush remaining buffer and stop the consumer."""
        self._running = False
        await self._flush()
        if self._consumer:
            await self._consumer.stop()
            self._consumer = None
        logger.info(
            "Telemetry consumer stopped. Consumed: %d, Written: %d",
            self._total_consumed,
            self._total_written,
        )

    async def run(self) -> None:
        """
        Main consume loop. Runs until stopped.

        Accumulates messages in buffers and flushes to DB when batch
        size is reached or flush interval expires.
        """
        if not self._consumer:
            raise RuntimeError("Consumer not started. Call start() first.")

        try:
            async for message in self._consumer:
                if not self._running:
                    break

                try:
                    self._process_message(message.topic, message.value)
                    self._total_consumed += 1
                except Exception as e:
                    logger.error("Error processing message: %s", e)

                # Check flush conditions
                buffer_full = (
                    len(self._kpi_buffer) >= self.batch_size
                    or len(self._alarm_buffer) >= self.batch_size
                )
                interval_elapsed = (
                    time.monotonic() - self._last_flush >= self.flush_interval
                )

                if buffer_full or interval_elapsed:
                    await self._flush()

        except asyncio.CancelledError:
            logger.info("Telemetry consumer cancelled")
            await self._flush()
        except Exception as e:
            logger.error("Consumer error: %s", e, exc_info=True)
            await self._flush()

    def _process_message(self, topic: str, msg: dict[str, Any]) -> None:
        """Route a message to the appropriate buffer."""
        if topic == TelemetryTopics.ALARMS:
            parsed = _parse_alarm_message(msg)
            if parsed:
                self._alarm_buffer.append(parsed)
        else:
            parsed = _parse_kpi_message(msg, topic)
            if parsed:
                self._kpi_buffer.append(parsed)

    async def _flush(self) -> None:
        """Flush accumulated buffers to the database."""
        kpi_batch = self._kpi_buffer
        alarm_batch = self._alarm_buffer
        self._kpi_buffer = []
        self._alarm_buffer = []
        self._last_flush = time.monotonic()

        if not kpi_batch and not alarm_batch:
            return

        from sqlalchemy import text

        from backend.app.core.database import metrics_session_maker

        try:
            async with metrics_session_maker() as session:
                if kpi_batch:
                    await session.execute(
                        text(_UPSERT_TELEMETRY_SQL),
                        kpi_batch,
                    )
                    self._total_written += len(kpi_batch)

                if alarm_batch:
                    await session.execute(
                        text(_UPSERT_ALARM_SQL),
                        alarm_batch,
                    )
                    self._total_written += len(alarm_batch)

                await session.commit()

            if self._total_consumed % 10_000 < self.batch_size:
                logger.info(
                    "Telemetry consumer: consumed=%d, written=%d (kpi_batch=%d, alarm_batch=%d)",
                    self._total_consumed,
                    self._total_written,
                    len(kpi_batch),
                    len(alarm_batch),
                )
        except Exception as e:
            logger.error("DB write error (batch lost): %s", e)


async def start_telemetry_consumer() -> asyncio.Task:
    """
    Start the telemetry consumer as a background asyncio task.

    Returns the task handle for lifecycle management.
    """
    await initialize_telemetry_tables()

    consumer = TelemetryConsumer()
    await consumer.start()

    async def _run_loop():
        try:
            await consumer.run()
        except asyncio.CancelledError:
            await consumer.stop()
        except Exception as e:
            logger.error("Telemetry consumer crashed: %s", e, exc_info=True)
            await consumer.stop()

    task = asyncio.create_task(_run_loop(), name="telemetry-consumer")
    logger.info("Telemetry consumer background task started")
    return task
