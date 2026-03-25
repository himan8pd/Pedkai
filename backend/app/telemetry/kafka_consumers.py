"""
Kafka Consumers for telemetry ingestion.

Consumes from domain-specific telemetry topics and writes to the EXISTING
production tables:

  - KPI metrics  → kpi_metrics (TimescaleDB, narrow/long format)
  - Alarms       → telco_events_alarms (PostgreSQL graph DB)

These consumers are agnostic to the telemetry source — they work identically
whether the producer is the Parquet replay service or a live network feed.
Downstream systems (reconciliation, sleeping cell detector, reports, SSE)
see no difference.

Design:
  - Wide-format Kafka messages are unpivoted to narrow (entity, metric, value)
    rows, exactly matching the format produced by load_telco2_tenant.py.
  - Alarms are inserted into the graph DB, where the SSE endpoint, correlation
    engine, and reports API already query them.
  - ON CONFLICT DO NOTHING everywhere for idempotency.
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


# ---------------------------------------------------------------------------
# SQL — writes into EXISTING tables (created by migrations / init_db)
# ---------------------------------------------------------------------------

# kpi_metrics lives in TimescaleDB (metrics DB).
# Column names match create-metrics-tables.sql and the ORM (KPIMetricORM).
_UPSERT_KPI_SQL = """
INSERT INTO kpi_metrics (timestamp, tenant_id, entity_id, kpi_name, kpi_value, metadata)
VALUES (:timestamp, :tenant_id, :entity_id, :kpi_name, :kpi_value, :metadata)
ON CONFLICT DO NOTHING
"""

# telco_events_alarms lives in the graph DB (PostgreSQL).
# Schema matches migration 014 and load_telco2_tenant.py.
_UPSERT_ALARM_SQL = """
INSERT INTO telco_events_alarms
    (alarm_id, tenant_id, entity_id, entity_type, alarm_type,
     severity, raised_at, cleared_at, source_system, probable_cause,
     domain, scenario_id, is_synthetic_scenario, additional_text,
     correlation_group_id)
VALUES
    (:alarm_id, :tenant_id, :entity_id, :entity_type, :alarm_type,
     :severity, :raised_at, :cleared_at, :source_system, :probable_cause,
     :domain, :scenario_id, :is_synthetic_scenario, :additional_text,
     :correlation_group_id)
ON CONFLICT (alarm_id) DO NOTHING
"""

# ---------------------------------------------------------------------------
# Domain & column mappings
# ---------------------------------------------------------------------------

# Topic → human-readable domain label (stored in metadata JSONB for context)
_TOPIC_TO_DOMAIN = {
    TelemetryTopics.RAN_KPI: "ran",
    TelemetryTopics.TRANSPORT_KPI: "transport",
    TelemetryTopics.FIXED_BROADBAND_KPI: "fixed_broadband",
    TelemetryTopics.CORE_KPI: "core",
    TelemetryTopics.ENTERPRISE_KPI: "enterprise",
    TelemetryTopics.POWER_KPI: "power",
}

# Which message field holds the entity ID for each topic
_TOPIC_ENTITY_COL = {
    TelemetryTopics.RAN_KPI: "cell_id",
    TelemetryTopics.TRANSPORT_KPI: "entity_id",
    TelemetryTopics.FIXED_BROADBAND_KPI: "entity_id",
    TelemetryTopics.CORE_KPI: "entity_id",
    TelemetryTopics.ENTERPRISE_KPI: "entity_id",
    TelemetryTopics.POWER_KPI: "site_id",
}

# Columns that are NEVER KPI values — they identify the entity or the row.
_IDENTITY_COLS = frozenset({
    "tenant_id", "timestamp", "cell_id", "entity_id", "site_id",
})

# Categorical/descriptor columns → stored in metadata JSONB, not as KPI values.
# Matches the METADATA_COLS set in load_telco2_tenant.py step_12.
_METADATA_JSON_CANDIDATES = frozenset({
    "rat_type", "band", "site_id", "vendor", "deployment_profile",
    "is_nsa_scg_leg", "entity_type", "site_type", "domain",
})

# Union of all non-KPI column names
_NON_KPI_COLS = _IDENTITY_COLS | _METADATA_JSON_CANDIDATES


# ---------------------------------------------------------------------------
# Message parsers
# ---------------------------------------------------------------------------

def _parse_kpi_message(msg: dict[str, Any], topic: str) -> list[dict[str, Any]]:
    """
    Unpivot a wide-format KPI message into narrow kpi_metrics rows.

    One Kafka message with N metric columns becomes N rows:
        (timestamp, tenant_id, entity_id, kpi_name, kpi_value, metadata)

    This is the same wide→long transformation that load_telco2_tenant.py
    performs at initial data load time.
    """
    entity_col = _TOPIC_ENTITY_COL.get(topic, "entity_id")
    entity_id = msg.get(entity_col)
    tenant_id = msg.get("tenant_id")
    timestamp_raw = msg.get("timestamp")

    if not entity_id or not tenant_id or not timestamp_raw:
        return []

    # asyncpg requires datetime objects, not ISO strings
    timestamp = (
        datetime.fromisoformat(timestamp_raw)
        if isinstance(timestamp_raw, str) else timestamp_raw
    )

    # Build metadata JSONB — categorical descriptors (non-null only).
    # Exclude the entity column itself to avoid storing it twice.
    domain = _TOPIC_TO_DOMAIN.get(topic, "unknown")
    metadata: dict[str, Any] = {"domain": domain}
    for k in _METADATA_JSON_CANDIDATES:
        if k != entity_col and k in msg and msg[k] is not None:
            metadata[k] = msg[k]
    metadata_json = json.dumps(metadata)

    # Unpivot: every key NOT in _NON_KPI_COLS with a non-null value is a KPI
    rows: list[dict[str, Any]] = []
    for k, v in msg.items():
        if k in _NON_KPI_COLS or v is None:
            continue
        try:
            kpi_value = float(v)
        except (TypeError, ValueError):
            continue  # Skip non-numeric values

        rows.append({
            "timestamp": timestamp,
            "tenant_id": tenant_id,
            "entity_id": str(entity_id),
            "kpi_name": k,
            "kpi_value": kpi_value,
            "metadata": metadata_json,
        })

    return rows


def _parse_alarm_message(msg: dict[str, Any]) -> dict[str, Any] | None:
    """
    Parse an alarm message into a telco_events_alarms row.

    Column mapping matches migration 014 and load_telco2_tenant.py step_8.
    """
    alarm_id = msg.get("alarm_id")
    tenant_id = msg.get("tenant_id")
    entity_id = msg.get("entity_id")
    raised_at_raw = msg.get("raised_at")

    if not alarm_id or not tenant_id or not entity_id or not raised_at_raw:
        return None

    # asyncpg requires datetime objects, not ISO strings
    raised_at = (
        datetime.fromisoformat(raised_at_raw)
        if isinstance(raised_at_raw, str) else raised_at_raw
    )
    cleared_at_raw = msg.get("cleared_at")
    cleared_at = (
        datetime.fromisoformat(cleared_at_raw)
        if isinstance(cleared_at_raw, str) and cleared_at_raw
        else cleared_at_raw
    )

    return {
        "alarm_id": alarm_id,
        "tenant_id": tenant_id,
        "entity_id": entity_id,
        "entity_type": msg.get("entity_type"),
        "alarm_type": msg.get("alarm_type", "UNKNOWN"),
        "severity": msg.get("severity", "minor"),
        "raised_at": raised_at,
        "cleared_at": cleared_at,
        "source_system": msg.get("source_system"),
        "probable_cause": msg.get("probable_cause"),
        "domain": msg.get("domain"),
        "scenario_id": msg.get("scenario_id"),
        "is_synthetic_scenario": msg.get("is_synthetic_scenario", False),
        "additional_text": msg.get("additional_text"),
        "correlation_group_id": msg.get("correlation_group_id"),
    }


# ---------------------------------------------------------------------------
# Consumer
# ---------------------------------------------------------------------------

class TelemetryConsumer:
    """
    Kafka consumer for telemetry topics with batched DB writes.

    Consumes from all telemetry topics, accumulates messages in memory,
    and flushes to the appropriate database in batches:
      - KPI rows  → kpi_metrics in TimescaleDB  (metrics_session_maker)
      - Alarm rows → telco_events_alarms in PostgreSQL (async_session_maker)

    When the Abeyance Memory fragment bridge is attached, the consumer
    also feeds events into the enrichment chain for fragment creation:
      - Every alarm → ALARM fragment
      - KPI anomalies (z > 3σ) → TELEMETRY_EVENT fragment

    LLD v3 ref: §4 (Data Fabric → Enrichment Chain)
    """

    def __init__(
        self,
        bootstrap_servers: str | None = None,
        group_id: str | None = None,
        batch_size: int | None = None,
        flush_interval: float | None = None,
        fragment_bridge: Any | None = None,
    ):
        self.bootstrap_servers = bootstrap_servers or settings.kafka_bootstrap_servers
        self.group_id = group_id or settings.telemetry_consumer_group
        self.batch_size = batch_size or settings.consumer_batch_size
        self.flush_interval = flush_interval or settings.consumer_flush_interval_seconds
        self._consumer = None
        self._running = False
        self._kpi_buffer: list[dict[str, Any]] = []
        self._alarm_buffer: list[dict[str, Any]] = []
        self._raw_alarm_buffer: list[dict[str, Any]] = []  # Raw msgs for fragment bridge
        self._last_flush = time.monotonic()
        self._total_consumed = 0
        self._total_kpi_written = 0
        self._total_alarm_written = 0

        # Abeyance Memory integration
        self._fragment_bridge = fragment_bridge
        self._anomaly_detector = None
        if fragment_bridge is not None:
            from backend.app.telemetry.fragment_bridge import AnomalyDetector
            self._anomaly_detector = AnomalyDetector(z_threshold=3.0)

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
            "Telemetry consumer stopped. Consumed: %d, KPI written: %d, Alarms written: %d",
            self._total_consumed,
            self._total_kpi_written,
            self._total_alarm_written,
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
                # Queue raw alarm for Abeyance Memory fragment bridge
                if self._fragment_bridge is not None:
                    self._raw_alarm_buffer.append(msg)
        else:
            # Unpivot wide → narrow: one message becomes many KPI rows
            rows = _parse_kpi_message(msg, topic)
            self._kpi_buffer.extend(rows)

            # Check for KPI anomalies → Abeyance Memory fragments
            if self._fragment_bridge is not None and self._anomaly_detector is not None:
                domain = _TOPIC_TO_DOMAIN.get(topic, "unknown")
                entity_col = _TOPIC_ENTITY_COL.get(topic, "entity_id")
                entity_id = str(msg.get(entity_col, ""))
                tenant_id = msg.get("tenant_id", "")
                timestamp_raw = msg.get("timestamp")
                timestamp = (
                    datetime.fromisoformat(timestamp_raw)
                    if isinstance(timestamp_raw, str) else timestamp_raw
                )

                for row in rows:
                    z = self._anomaly_detector.check(
                        entity_id, row["kpi_name"], row["kpi_value"]
                    )
                    if z is not None:
                        self._fragment_bridge.enqueue_anomaly(
                            entity_id=entity_id,
                            kpi_name=row["kpi_name"],
                            value=row["kpi_value"],
                            z_score=z,
                            domain=domain,
                            tenant_id=tenant_id,
                            timestamp=timestamp,
                        )

    async def _flush(self) -> None:
        """Flush accumulated buffers to their respective databases."""
        kpi_batch = self._kpi_buffer
        alarm_batch = self._alarm_buffer
        raw_alarm_batch = self._raw_alarm_buffer
        self._kpi_buffer = []
        self._alarm_buffer = []
        self._raw_alarm_buffer = []
        self._last_flush = time.monotonic()

        # Feed raw alarms to Abeyance Memory fragment bridge (non-blocking)
        if self._fragment_bridge is not None and raw_alarm_batch:
            for raw_alarm in raw_alarm_batch:
                self._fragment_bridge.enqueue_alarm(raw_alarm)

        if not kpi_batch and not alarm_batch:
            return

        from sqlalchemy import text

        # KPI rows → kpi_metrics in TimescaleDB (metrics DB)
        if kpi_batch:
            try:
                from backend.app.core.database import metrics_session_maker

                async with metrics_session_maker() as session:
                    await session.execute(text(_UPSERT_KPI_SQL), kpi_batch)
                    await session.commit()
                self._total_kpi_written += len(kpi_batch)
            except Exception as e:
                logger.error(
                    "KPI DB write error (%d rows lost): %s", len(kpi_batch), e
                )

        # Alarm rows → telco_events_alarms in graph DB (PostgreSQL)
        if alarm_batch:
            try:
                from backend.app.core.database import async_session_maker

                async with async_session_maker() as session:
                    await session.execute(text(_UPSERT_ALARM_SQL), alarm_batch)
                    await session.commit()
                self._total_alarm_written += len(alarm_batch)
            except Exception as e:
                logger.error(
                    "Alarm DB write error (%d rows lost): %s", len(alarm_batch), e
                )

        # Periodic progress log
        total_written = self._total_kpi_written + self._total_alarm_written
        if self._total_consumed % 5_000 < (self.batch_size + 1):
            logger.info(
                "Telemetry consumer: consumed=%d msgs | kpi_rows=%d | alarm_rows=%d "
                "(batch: kpi=%d, alarm=%d)",
                self._total_consumed,
                self._total_kpi_written,
                self._total_alarm_written,
                len(kpi_batch),
                len(alarm_batch),
            )


async def start_telemetry_consumer() -> tuple[asyncio.Task, asyncio.Task | None]:
    """
    Start the telemetry consumer as a background asyncio task.

    Tables (kpi_metrics, telco_events_alarms) are expected to already exist
    from migrations and init_db. This function does not create them.

    If ABEYANCE_FRAGMENT_BRIDGE_ENABLED is True, also starts the fragment
    bridge that feeds alarms and KPI anomalies into Abeyance Memory.

    Returns (consumer_task, bridge_task_or_None) for lifecycle management.
    """
    # Optionally start the Abeyance Memory fragment bridge
    bridge = None
    bridge_task = None
    bridge_enabled = getattr(settings, "abeyance_fragment_bridge_enabled", False)

    if bridge_enabled:
        try:
            from backend.app.telemetry.fragment_bridge import start_fragment_bridge

            bridge, bridge_task = await start_fragment_bridge()
            logger.info("Abeyance Memory fragment bridge attached to telemetry consumer")
        except Exception as e:
            logger.warning("Fragment bridge failed to start (continuing without): %s", e)
            bridge = None

    consumer = TelemetryConsumer(fragment_bridge=bridge)
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
    return task, bridge_task
