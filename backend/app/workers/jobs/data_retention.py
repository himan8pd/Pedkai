"""Data-retention cleanup periodic job (INF-03).

Schedules :meth:`DataRetentionService.run_retention_cleanup` to run daily,
enforcing GDPR/DPIA rolling retention windows on non-regulatory tables.

Retention is tenant-agnostic: policies are applied per-table (see
``RETENTION_POLICIES`` in ``backend.app.services.data_retention``), so the
job invokes the service once per tick.

Configuration (via environment):
    * ``DATA_RETENTION_INTERVAL_SECONDS`` — seconds between runs (default 86400).
    * ``DATA_RETENTION_ENABLED`` — ``"true"``/``"false"`` (default ``"true"``).
"""

from __future__ import annotations

import os

from backend.app.core.database import async_session_maker
from backend.app.core.logging import get_logger
from backend.app.services.data_retention import DataRetentionService
from backend.app.workers.periodic_jobs import PeriodicJob

logger = get_logger(__name__)


async def _run() -> None:
    """Run one data-retention cleanup pass and log the per-table summary."""
    service = DataRetentionService(async_session_maker)
    results = await service.run_retention_cleanup()
    logger.info("Data-retention cleanup complete: %s", results)


JOB = PeriodicJob(
    name="data_retention",
    interval_seconds=int(os.environ.get("DATA_RETENTION_INTERVAL_SECONDS", "86400")),
    enabled=os.environ.get("DATA_RETENTION_ENABLED", "true").lower() == "true",
    run=_run,
)
