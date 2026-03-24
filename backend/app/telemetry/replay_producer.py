"""
Telemetry Replay Producer — Parquet → Kafka streaming.

Streams historical Parquet telemetry data into Kafka topics, simulating
real-time production traffic with configurable time acceleration.

Design principles:
- Memory-efficient: reads one row-group (1 hour) at a time
- Temporally ordered: merges across all data sources per hour
- Production-equivalent: messages are indistinguishable from live telemetry
- Infrastructure-aware: throttles to respect constrained resources

Usage:
    producer = ReplayProducer(settings)
    await producer.start()
    await producer.run()        # blocks until replay completes
    await producer.stop()
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq

# ---------------------------------------------------------------------------
# Replay Checkpoint — enables idempotent replay
# ---------------------------------------------------------------------------
_DEFAULT_CHECKPOINT_FILENAME = ".replay_checkpoint.json"


class ReplayCheckpoint:
    """
    Persists the last successfully completed row-group index to disk.

    On restart the producer resumes from the next unprocessed row group,
    preventing duplicate Kafka messages and wasted consumer/DB work.

    Checkpoint file is a single JSON object:
        {"last_completed_rg": 42, "messages_produced": 5234000, "updated_at": "..."}
    """

    def __init__(self, data_path: Path, filename: str = _DEFAULT_CHECKPOINT_FILENAME):
        self.path = data_path / filename

    def load(self) -> int | None:
        """Return last completed row-group index, or None if no checkpoint."""
        if not self.path.exists():
            return None
        try:
            data = json.loads(self.path.read_text())
            rg = data.get("last_completed_rg")
            logger.info(
                "Checkpoint loaded: last_completed_rg=%s (from %s)",
                rg,
                self.path,
            )
            return rg
        except Exception as e:
            logger.warning("Failed to read checkpoint %s: %s", self.path, e)
            return None

    def save(self, rg_index: int, messages_produced: int) -> None:
        """Persist checkpoint after a row group is fully produced and flushed."""
        data = {
            "last_completed_rg": rg_index,
            "messages_produced": messages_produced,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            self.path.write_text(json.dumps(data))
        except Exception as e:
            logger.error("Failed to write checkpoint: %s", e)

    def clear(self) -> None:
        """Remove checkpoint file (called on successful full replay completion)."""
        try:
            if self.path.exists():
                self.path.unlink()
                logger.info("Checkpoint cleared: %s", self.path)
        except Exception as e:
            logger.warning("Failed to clear checkpoint: %s", e)

from backend.app.telemetry.schemas import make_kafka_key, row_to_message
from backend.app.telemetry.topics import (
    PARQUET_TO_TOPIC,
    TOPIC_ENTITY_ID_COLUMN,
    TOPIC_TIMESTAMP_COLUMN,
)

logger = logging.getLogger(__name__)


@dataclass
class ReplayStats:
    """Tracks replay progress and throughput."""

    messages_produced: int = 0
    messages_per_topic: dict[str, int] = field(default_factory=dict)
    start_time: float = 0.0
    current_replay_timestamp: str = ""
    errors: int = 0

    @property
    def elapsed_seconds(self) -> float:
        return time.monotonic() - self.start_time if self.start_time else 0

    @property
    def throughput(self) -> float:
        elapsed = self.elapsed_seconds
        return self.messages_produced / elapsed if elapsed > 0 else 0

    def log_progress(self) -> None:
        logger.info(
            "Replay progress: %s messages (%.0f msg/s) | Current: %s | Errors: %d",
            f"{self.messages_produced:,}",
            self.throughput,
            self.current_replay_timestamp,
            self.errors,
        )


@dataclass
class ParquetSource:
    """A single Parquet file to replay."""

    path: Path
    topic: str
    entity_col: str
    timestamp_col: str
    parquet_file: pq.ParquetFile | None = None
    num_row_groups: int = 0

    def open(self) -> None:
        self.parquet_file = pq.ParquetFile(str(self.path))
        self.num_row_groups = self.parquet_file.metadata.num_row_groups

    def close(self) -> None:
        self.parquet_file = None

    def read_row_group(self, index: int) -> pd.DataFrame:
        """Read a single row group as a DataFrame."""
        if not self.parquet_file:
            raise RuntimeError(f"ParquetFile not opened: {self.path}")
        table = self.parquet_file.read_row_group(index)
        return table.to_pandas()


class ReplayProducer:
    """
    Streams historical Parquet telemetry into Kafka topics.

    Reads data one hour at a time across all sources, merges by timestamp,
    and produces to domain-specific Kafka topics with controlled pacing.
    """

    def __init__(
        self,
        kafka_bootstrap_servers: str,
        data_path: str,
        acceleration: float = 120.0,
        skip_hours: int = 24,
        batch_size: int = 500,
    ):
        self.kafka_bootstrap_servers = kafka_bootstrap_servers
        self.data_path = Path(data_path)
        self.acceleration = acceleration
        self.skip_hours = skip_hours
        self.batch_size = batch_size
        self._producer = None
        self._sources: list[ParquetSource] = []
        self._stop_event = asyncio.Event()
        self.stats = ReplayStats()
        self._checkpoint = ReplayCheckpoint(self.data_path)

    async def start(self) -> None:
        """Initialize Kafka producer and open Parquet sources."""
        from aiokafka import AIOKafkaProducer

        self._producer = AIOKafkaProducer(
            bootstrap_servers=self.kafka_bootstrap_servers,
            # Batch settings for throughput
            linger_ms=50,
            max_batch_size=1_048_576,  # 1 MB batches
            compression_type="gzip",
            # Buffer limits
            max_request_size=10_485_760,  # 10 MB
        )
        await self._producer.start()

        self._discover_sources()
        logger.info(
            "Replay producer started: %d sources, acceleration=%.0fx, skip=%dh",
            len(self._sources),
            self.acceleration,
            self.skip_hours,
        )

    def _discover_sources(self) -> None:
        """Discover and validate Parquet files in the data directory."""
        self._sources = []
        for stem, topic in PARQUET_TO_TOPIC.items():
            path = self.data_path / f"{stem}.parquet"
            if not path.exists():
                logger.warning("Parquet file not found, skipping: %s", path)
                continue

            entity_col = TOPIC_ENTITY_ID_COLUMN[topic]
            ts_col = TOPIC_TIMESTAMP_COLUMN[topic]

            source = ParquetSource(
                path=path,
                topic=topic,
                entity_col=entity_col,
                timestamp_col=ts_col,
            )
            source.open()
            self._sources.append(source)
            logger.info(
                "Source: %s -> %s (%d row groups, %s rows)",
                path.name,
                topic,
                source.num_row_groups,
                f"{source.parquet_file.metadata.num_rows:,}",
            )

    async def stop(self) -> None:
        """Signal stop and flush the Kafka producer."""
        self._stop_event.set()
        if self._producer:
            await self._producer.stop()
            self._producer = None
        for source in self._sources:
            source.close()
        self._sources = []
        logger.info("Replay producer stopped. %s", self._format_final_stats())

    async def run(self) -> None:
        """
        Main replay loop.

        Iterates hour-by-hour across all sources, merging events by
        timestamp and producing them to Kafka with controlled pacing.
        """
        if not self._sources:
            logger.error("No sources available. Call start() first.")
            return

        self.stats = ReplayStats()
        self.stats.start_time = time.monotonic()

        # Determine the row group range (all files have 720 row groups = 720 hours)
        max_row_groups = max(s.num_row_groups for s in self._sources)
        start_rg = self.skip_hours

        # Resume from checkpoint if available (idempotent replay)
        last_completed = self._checkpoint.load()
        if last_completed is not None and last_completed >= start_rg:
            start_rg = last_completed + 1
            logger.info(
                "Resuming from checkpoint: row group %d (skipping %d already-produced hours)",
                start_rg,
                start_rg - self.skip_hours,
            )

        if start_rg >= max_row_groups:
            logger.info("Replay already complete (checkpoint=%d, max=%d). Nothing to do.", last_completed, max_row_groups)
            return

        logger.info(
            "Beginning replay: row groups %d-%d (%d hours of data)",
            start_rg,
            max_row_groups - 1,
            max_row_groups - start_rg,
        )

        prev_ts: datetime | None = None

        # Pre-serialize records from sources with fewer row groups than
        # skip_hours (e.g., alarms stored in 1 row group). These are
        # indexed by hour offset so they merge into the correct replay slot.
        preloaded_by_hour: dict[int, list[tuple[str, datetime, bytes, bytes | None]]] = {}
        preloaded_source_names: set[str] = set()

        for source in self._sources:
            if source.num_row_groups >= start_rg:
                continue

            preloaded_source_names.add(source.path.name)
            logger.info(
                "Source %s has %d row groups (< skip=%d), loading fully and filtering by timestamp",
                source.path.name,
                source.num_row_groups,
                start_rg,
            )
            df_all = pd.concat(
                [source.read_row_group(i) for i in range(source.num_row_groups)],
                ignore_index=True,
            )
            ts_min = df_all[source.timestamp_col].min()
            skip_cutoff = ts_min + pd.Timedelta(hours=self.skip_hours)
            df_filtered = df_all[df_all[source.timestamp_col] >= skip_cutoff].copy()
            df_filtered = df_filtered.sort_values(source.timestamp_col)

            # Index records by hour offset from start_rg
            for _, row in df_filtered.iterrows():
                ts_val = row[source.timestamp_col]
                if pd.isna(ts_val):
                    continue
                ts = pd.Timestamp(ts_val)
                if ts.tzinfo is None:
                    ts = ts.tz_localize("UTC")
                # Compute which replay hour this record belongs to
                hour_offset = int((ts - skip_cutoff).total_seconds() // 3600)
                rg_target = start_rg + max(0, hour_offset)

                msg = row_to_message(row, source.timestamp_col)
                msg_bytes = json.dumps(msg, default=str).encode("utf-8")
                key = make_kafka_key(row, source.entity_col)

                preloaded_by_hour.setdefault(rg_target, []).append(
                    (source.topic, ts.to_pydatetime(), msg_bytes, key)
                )

            logger.info(
                "  Loaded %d rows after T+%dh cutoff, distributed across %d hours",
                len(df_filtered),
                self.skip_hours,
                len([h for h in preloaded_by_hour if preloaded_by_hour[h]]),
            )

        for rg_idx in range(start_rg, max_row_groups):
            if self._stop_event.is_set():
                logger.info("Replay stopped by signal at row group %d", rg_idx)
                break

            # Collect records from all sources for this hour
            hour_records: list[tuple[str, datetime, bytes, bytes | None]] = []

            # Inject preloaded records for this hour
            if rg_idx in preloaded_by_hour:
                hour_records.extend(preloaded_by_hour.pop(rg_idx))

            for source in self._sources:
                if source.path.name in preloaded_source_names:
                    continue  # Already handled via preloaded_by_hour
                if rg_idx >= source.num_row_groups:
                    continue

                try:
                    df = source.read_row_group(rg_idx)
                except Exception as e:
                    logger.error(
                        "Error reading row group %d from %s: %s",
                        rg_idx,
                        source.path.name,
                        e,
                    )
                    self.stats.errors += 1
                    continue

                # Sort within the hour by timestamp
                df = df.sort_values(source.timestamp_col)

                for _, row in df.iterrows():
                    ts_val = row[source.timestamp_col]
                    if pd.isna(ts_val):
                        continue

                    ts = pd.Timestamp(ts_val)
                    if ts.tzinfo is None:
                        ts = ts.tz_localize("UTC")

                    msg = row_to_message(row, source.timestamp_col)
                    msg_bytes = json.dumps(msg, default=str).encode("utf-8")
                    key = make_kafka_key(row, source.entity_col)

                    hour_records.append(
                        (source.topic, ts.to_pydatetime(), msg_bytes, key)
                    )

            if not hour_records:
                continue

            # Sort all records for this hour across sources by timestamp
            hour_records.sort(key=lambda r: r[1])

            # Produce with pacing
            batch_futures = []
            for topic, ts, msg_bytes, key in hour_records:
                if self._stop_event.is_set():
                    break

                # Apply inter-event timing delay
                if prev_ts is not None and self.acceleration > 0:
                    delta = (ts - prev_ts).total_seconds()
                    if delta > 0:
                        sleep_time = delta / self.acceleration
                        # Cap sleep to avoid hanging on large gaps
                        sleep_time = min(sleep_time, 5.0)
                        if sleep_time > 0.001:
                            await asyncio.sleep(sleep_time)

                # Produce to Kafka (non-blocking, batched internally)
                try:
                    future = await self._producer.send(
                        topic=topic,
                        value=msg_bytes,
                        key=key,
                    )
                    batch_futures.append(future)
                    self.stats.messages_produced += 1
                    self.stats.messages_per_topic[topic] = (
                        self.stats.messages_per_topic.get(topic, 0) + 1
                    )

                    # Periodically drain futures to bound memory
                    if len(batch_futures) >= self.batch_size:
                        await self._producer.flush()
                        batch_futures.clear()

                except Exception as e:
                    logger.error("Produce error: %s", e)
                    self.stats.errors += 1

                prev_ts = ts

            # End of hour — flush and log progress
            if batch_futures:
                await self._producer.flush()
                batch_futures.clear()

            self.stats.current_replay_timestamp = str(ts) if hour_records else ""
            self.stats.log_progress()

            # Checkpoint: this row group is fully produced and flushed
            self._checkpoint.save(rg_idx, self.stats.messages_produced)

        # Final flush
        if self._producer:
            await self._producer.flush()

        # If replay completed fully (not stopped early), clear the checkpoint
        # so next run starts fresh if the data changes.
        if not self._stop_event.is_set():
            self._checkpoint.clear()
            logger.info("Replay complete (checkpoint cleared). %s", self._format_final_stats())
        else:
            logger.info("Replay stopped early (checkpoint preserved). %s", self._format_final_stats())

    def _format_final_stats(self) -> str:
        s = self.stats
        lines = [
            f"Total: {s.messages_produced:,} messages in {s.elapsed_seconds:.1f}s",
            f"Throughput: {s.throughput:.0f} msg/s",
            f"Errors: {s.errors}",
        ]
        for topic, count in sorted(s.messages_per_topic.items()):
            lines.append(f"  {topic}: {count:,}")
        return " | ".join(lines[:3]) + "\n" + "\n".join(lines[3:])
