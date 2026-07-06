"""Generic periodic job runner with package auto-discovery.

Discovers job modules under ``backend.app.workers.jobs`` at startup. Each
module may expose a module-level ``JOB`` attribute of type
:class:`PeriodicJob`; the runner schedules every enabled job on its own
asyncio task, invoking ``job.run()`` every ``interval_seconds``.

Design goals:
    * File-additive — new jobs are added by dropping a module in the
      ``jobs`` package, no wiring changes required.
    * Fail-safe — a broken job module is logged and skipped; it never
      crashes startup. A raising ``run()`` is logged and retried on the
      next tick.
    * Kill switch — ``PEDKAI_PERIODIC_JOBS_ENABLED=false`` disables the
      whole runner (start becomes a no-op).
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import os
import pkgutil
from dataclasses import dataclass
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)


@dataclass
class PeriodicJob:
    """A single periodic job definition.

    Attributes:
        name: Human-readable job name (used in logs).
        interval_seconds: Delay between successive ``run()`` invocations.
        enabled: If False, the job is discovered but not scheduled.
        run: Async callable invoked on each tick.
    """

    name: str
    interval_seconds: int
    enabled: bool
    run: Callable[[], Awaitable[None]]


def discover_jobs() -> list[PeriodicJob]:
    """Discover ``PeriodicJob`` definitions from the jobs package.

    Iterates modules under ``backend.app.workers.jobs``, imports each, and
    collects its module-level ``JOB`` attribute. Any import failure (or a
    module without a valid ``JOB``) is logged and skipped so a broken
    module can never crash startup.
    """
    from backend.app.workers import jobs as jobs_pkg

    discovered: list[PeriodicJob] = []
    for module_info in pkgutil.iter_modules(jobs_pkg.__path__):
        module_name = f"{jobs_pkg.__name__}.{module_info.name}"
        try:
            module = importlib.import_module(module_name)
        except Exception:
            logger.error("Failed to import periodic job module %s", module_name, exc_info=True)
            continue

        job = getattr(module, "JOB", None)
        if job is None:
            continue
        if not isinstance(job, PeriodicJob):
            logger.error(
                "Module %s defines JOB but it is not a PeriodicJob (got %r); skipping",
                module_name,
                type(job),
            )
            continue
        discovered.append(job)

    return discovered


async def _run_job_loop(job: PeriodicJob) -> None:
    """Run a single job forever, sleeping ``interval_seconds`` between ticks."""
    while True:
        try:
            await job.run()
        except Exception:
            logger.error("Periodic job %r raised", job.name, exc_info=True)
        await asyncio.sleep(job.interval_seconds)


async def start_periodic_jobs() -> list[asyncio.Task]:
    """Discover and start all enabled periodic jobs.

    Returns the list of created asyncio tasks (empty if the global kill
    switch is off or no enabled jobs are discovered).
    """
    if os.environ.get("PEDKAI_PERIODIC_JOBS_ENABLED", "true").lower() != "true":
        logger.info("Periodic jobs disabled via PEDKAI_PERIODIC_JOBS_ENABLED")
        return []

    tasks: list[asyncio.Task] = []
    for job in discover_jobs():
        if not job.enabled:
            logger.info("Periodic job %r discovered but disabled; skipping", job.name)
            continue
        task = asyncio.create_task(_run_job_loop(job), name=f"periodic-job-{job.name}")
        tasks.append(task)
        logger.info(
            "Periodic job %r started (interval=%ss)", job.name, job.interval_seconds
        )

    return tasks


async def stop_periodic_jobs(tasks: list[asyncio.Task]) -> None:
    """Cancel and await all periodic job tasks."""
    for task in tasks:
        if not task.done():
            task.cancel()
    for task in tasks:
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
