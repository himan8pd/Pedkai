"""Simple asyncio scheduler for periodic tasks (used by P2.4 SleepingCellDetector)."""
import asyncio
import logging
from typing import Callable

logger = logging.getLogger(__name__)


async def _periodic_task(interval_seconds: int, coro: Callable, *args, **kwargs):
    while True:
        try:
            await coro(*args, **kwargs)
        except Exception as e:
            logger.error(f"Scheduled task error: {e}", exc_info=True)
        await asyncio.sleep(interval_seconds)


def start_scheduler(interval_seconds: int, coro: Callable, *args, **kwargs):
    """Start periodic coro as background task and return the task."""
    task = asyncio.create_task(_periodic_task(interval_seconds, coro, *args, **kwargs))
    return task
