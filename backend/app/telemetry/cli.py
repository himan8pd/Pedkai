"""
CLI entry point for the Telemetry Replay Service.

Usage:
    # Run with default settings (from .env / environment variables)
    python -m backend.app.telemetry.cli

    # Override acceleration and data path
    python -m backend.app.telemetry.cli --acceleration 240 --data-path /path/to/data

    # Dry run (no Kafka, just validate and count)
    python -m backend.app.telemetry.cli --dry-run

    # Docker
    docker compose run --rm replay
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Pedkai Telemetry Replay — stream historical Parquet data into Kafka",
    )
    parser.add_argument(
        "--data-path",
        type=str,
        default=None,
        help="Path to Parquet data directory (default: from TELEMETRY_DATA_PATH env)",
    )
    parser.add_argument(
        "--acceleration",
        type=float,
        default=None,
        help="Time acceleration factor (default: from REPLAY_ACCELERATION env, or 120)",
    )
    parser.add_argument(
        "--skip-hours",
        type=int,
        default=None,
        help="Hours of data to skip from start (default: from REPLAY_SKIP_HOURS env, or 24)",
    )
    parser.add_argument(
        "--kafka",
        type=str,
        default=None,
        help="Kafka bootstrap servers (default: from KAFKA_BOOTSTRAP_SERVERS env)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="Kafka producer batch size (default: from REPLAY_BATCH_SIZE env, or 500)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate sources and count records without producing to Kafka",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Clear replay checkpoint and start from the beginning",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log level (default: INFO)",
    )
    return parser.parse_args()


async def _run_dry(data_path: str, skip_hours: int) -> None:
    """Dry run: validate Parquet sources and report stats."""
    import pyarrow.parquet as pq

    from backend.app.telemetry.topics import PARQUET_TO_TOPIC

    print(f"\nDry run — scanning: {data_path}")
    print(f"Skip hours: {skip_hours}\n")

    total_rows = 0
    replay_rows = 0
    data_dir = Path(data_path)

    for stem, topic in sorted(PARQUET_TO_TOPIC.items()):
        path = data_dir / f"{stem}.parquet"
        if not path.exists():
            print(f"  MISSING: {path.name}")
            continue

        pf = pq.ParquetFile(str(path))
        num_rg = pf.metadata.num_row_groups
        total = pf.metadata.num_rows

        if num_rg >= skip_hours:
            # Standard case: skip row groups
            replay = 0
            for rg_idx in range(skip_hours, num_rg):
                replay += pf.metadata.row_group(rg_idx).num_rows
            rg_range = f"rg: {skip_hours}-{num_rg - 1}"
        else:
            # Few row groups (e.g., alarms): filter by timestamp
            from backend.app.telemetry.topics import TOPIC_TIMESTAMP_COLUMN
            ts_col = TOPIC_TIMESTAMP_COLUMN[topic]
            df = pf.read().to_pandas()
            ts_min = df[ts_col].min()
            import pandas as pd
            cutoff = ts_min + pd.Timedelta(hours=skip_hours)
            replay = int((df[ts_col] >= cutoff).sum())
            rg_range = f"ts-filtered (1 rg)"

        total_rows += total
        replay_rows += replay
        print(
            f"  {path.name:45s} -> {topic:35s} "
            f"| {total:>12,} rows | replay: {replay:>12,} "
            f"| {rg_range}"
        )

    print(f"\n  Total rows:  {total_rows:>14,}")
    print(f"  Replay rows: {replay_rows:>14,}")
    print(f"  Skipped:     {total_rows - replay_rows:>14,}")


async def _run_replay(
    kafka: str,
    data_path: str,
    acceleration: float,
    skip_hours: int,
    batch_size: int,
) -> None:
    """Run the replay producer."""
    from backend.app.telemetry.replay_producer import ReplayProducer

    producer = ReplayProducer(
        kafka_bootstrap_servers=kafka,
        data_path=data_path,
        acceleration=acceleration,
        skip_hours=skip_hours,
        batch_size=batch_size,
    )

    # Graceful shutdown on SIGINT/SIGTERM
    loop = asyncio.get_running_loop()

    def _signal_handler():
        print("\nShutdown signal received, stopping replay...")
        asyncio.ensure_future(producer.stop())

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    await producer.start()
    await producer.run()
    await producer.stop()


def main() -> None:
    """CLI entry point."""
    args = _parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Load settings with env var fallbacks
    from backend.app.core.config import get_settings

    settings = get_settings()

    data_path = args.data_path or settings.telemetry_data_path
    acceleration = args.acceleration if args.acceleration is not None else settings.replay_acceleration
    skip_hours = args.skip_hours if args.skip_hours is not None else settings.replay_skip_hours
    kafka = args.kafka or settings.kafka_bootstrap_servers
    batch_size = args.batch_size if args.batch_size is not None else settings.replay_batch_size

    print("=" * 70)
    print("  Pedkai Telemetry Replay Service")
    print("=" * 70)
    print(f"  Data path:     {data_path}")
    print(f"  Kafka:         {kafka}")
    print(f"  Acceleration:  {acceleration}x")
    print(f"  Skip hours:    {skip_hours}")
    print(f"  Batch size:    {batch_size}")
    print(f"  Mode:          {'DRY RUN' if args.dry_run else 'LIVE'}")
    print(f"  Reset:         {'YES' if args.reset else 'no (resume from checkpoint)'}")
    print("=" * 70)

    # Handle --reset: clear checkpoint before starting
    if args.reset:
        from backend.app.telemetry.replay_producer import ReplayCheckpoint
        cp = ReplayCheckpoint(Path(data_path))
        cp.clear()
        print("  Checkpoint cleared — replay will start from the beginning.")

    if args.dry_run:
        asyncio.run(_run_dry(data_path, skip_hours))
    else:
        asyncio.run(_run_replay(kafka, data_path, acceleration, skip_hours, batch_size))


if __name__ == "__main__":
    main()
