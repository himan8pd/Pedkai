"""Unit tests for the outcome_calibration periodic job (INF-05)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.app.services.abeyance.snap_engine_v3 import WEIGHT_PROFILES_V3
from backend.app.workers.jobs import outcome_calibration as job_mod
from backend.app.workers.periodic_jobs import PeriodicJob


def _make_session():
    """A fake AsyncSession usable as an async context manager."""
    session = MagicMock()
    session.commit = AsyncMock()

    @asynccontextmanager
    async def _ctx():
        yield session

    return session, _ctx


def test_job_metadata():
    assert isinstance(job_mod.JOB, PeriodicJob)
    assert job_mod.JOB.name == "outcome_calibration"
    assert job_mod.JOB.interval_seconds == 86400
    assert job_mod.JOB.enabled is True


@pytest.mark.asyncio
async def test_run_calibrates_each_tenant_and_profile(monkeypatch):
    tenant_ids = ["tenant-a", "tenant-b"]

    # Mock tenant-listing session: execute() -> result with .all() rows of (id,).
    list_result = MagicMock()
    list_result.all.return_value = [(tid,) for tid in tenant_ids]
    list_session = MagicMock()
    list_session.execute = AsyncMock(return_value=list_result)

    per_tenant_session, _ = _make_session()

    sessions = iter([list_session] + [None] * (len(tenant_ids) * len(WEIGHT_PROFILES_V3)))

    def fake_session_maker():
        try:
            fixed = next(sessions)
        except StopIteration:
            fixed = None

        @asynccontextmanager
        async def _ctx():
            if fixed is not None:
                yield fixed
            else:
                yield per_tenant_session

        return _ctx()

    # calibrate returns None (insufficient) — must be treated as NORMAL, not error.
    calibrate = AsyncMock(return_value=None)
    fake_services = {"outcome_calibration": MagicMock(calibrate=calibrate)}

    # _run() uses lazy imports, so patch the source modules it imports from.
    import backend.app.core.database as db_mod
    import backend.app.services.abeyance as abeyance_mod

    monkeypatch.setattr(db_mod, "async_session_maker", fake_session_maker)
    monkeypatch.setattr(abeyance_mod, "create_abeyance_services", lambda *a, **k: fake_services)

    await job_mod._run()

    expected = 2 * len(WEIGHT_PROFILES_V3)
    assert calibrate.await_count == expected
    # commit is called once per calibrate invocation.
    assert per_tenant_session.commit.await_count == expected
