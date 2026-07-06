"""Unit tests for the periodic job runner (INF-01)."""

import asyncio

import pytest

from backend.app.workers import periodic_jobs
from backend.app.workers.periodic_jobs import (
    PeriodicJob,
    start_periodic_jobs,
    stop_periodic_jobs,
)


@pytest.mark.asyncio
async def test_periodic_job_runs_at_interval(monkeypatch):
    """A registered fake job executes repeatedly at its interval."""
    counter = {"n": 0}

    async def _run():
        counter["n"] += 1

    fake_job = PeriodicJob(
        name="fake", interval_seconds=0.1, enabled=True, run=_run
    )
    monkeypatch.setattr(periodic_jobs, "discover_jobs", lambda: [fake_job])

    tasks = await start_periodic_jobs()
    try:
        assert len(tasks) == 1
        await asyncio.sleep(0.35)
        assert counter["n"] >= 2
    finally:
        await stop_periodic_jobs(tasks)

    # Tasks are cleanly cancelled/finished after stop.
    assert all(t.done() for t in tasks)


@pytest.mark.asyncio
async def test_no_jobs_is_clean_noop(monkeypatch):
    """Zero discovered jobs yields no tasks."""
    monkeypatch.setattr(periodic_jobs, "discover_jobs", lambda: [])
    tasks = await start_periodic_jobs()
    assert tasks == []
    await stop_periodic_jobs(tasks)


@pytest.mark.asyncio
async def test_disabled_job_not_scheduled(monkeypatch):
    """A discovered-but-disabled job is not scheduled."""

    async def _run():
        raise AssertionError("disabled job should not run")

    disabled = PeriodicJob(
        name="off", interval_seconds=0.1, enabled=False, run=_run
    )
    monkeypatch.setattr(periodic_jobs, "discover_jobs", lambda: [disabled])
    tasks = await start_periodic_jobs()
    assert tasks == []
    await stop_periodic_jobs(tasks)


@pytest.mark.asyncio
async def test_kill_switch_disables_runner(monkeypatch):
    """PEDKAI_PERIODIC_JOBS_ENABLED=false makes start a no-op."""
    monkeypatch.setenv("PEDKAI_PERIODIC_JOBS_ENABLED", "false")

    async def _run():
        raise AssertionError("kill switch should prevent scheduling")

    job = PeriodicJob(name="x", interval_seconds=0.1, enabled=True, run=_run)
    monkeypatch.setattr(periodic_jobs, "discover_jobs", lambda: [job])
    tasks = await start_periodic_jobs()
    assert tasks == []
    await stop_periodic_jobs(tasks)
