"""Unit tests for the background abeyance discovery job (INF-04)."""

import importlib
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.app.workers.periodic_jobs import PeriodicJob


def _reload_module(monkeypatch, **env):
    """Reload the job module with a controlled environment.

    ``JOB`` is built at import time from ``os.environ``, so the module must
    be reloaded after mutating the env to observe the effect.
    """
    for key in ("ABEYANCE_DISCOVERY_ENABLED", "ABEYANCE_DISCOVERY_INTERVAL_SECONDS"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    import backend.app.workers.jobs.abeyance_discovery as mod

    return importlib.reload(mod)


def test_job_metadata_defaults(monkeypatch):
    """With env unset, JOB is disabled with the default 6h interval."""
    mod = _reload_module(monkeypatch)

    assert isinstance(mod.JOB, PeriodicJob)
    assert mod.JOB.name == "abeyance_discovery"
    assert mod.JOB.interval_seconds == 21600
    assert mod.JOB.enabled is False


def test_job_enabled_via_env(monkeypatch):
    """Setting the enabled env var to 'true' flips JOB.enabled on."""
    mod = _reload_module(monkeypatch, ABEYANCE_DISCOVERY_ENABLED="true")
    assert mod.JOB.enabled is True


def test_interval_override_via_env(monkeypatch):
    """Interval env var overrides the default."""
    mod = _reload_module(monkeypatch, ABEYANCE_DISCOVERY_INTERVAL_SECONDS="60")
    assert mod.JOB.interval_seconds == 60


@pytest.mark.asyncio
async def test_run_invokes_loop_once_per_tenant(monkeypatch):
    """run_background_jobs is called exactly once per tenant."""
    mod = _reload_module(monkeypatch, ABEYANCE_DISCOVERY_ENABLED="true")

    tenant_ids = ["tenant-a", "tenant-b", "tenant-c"]

    # Mock discovery loop.
    discovery_loop = MagicMock()
    discovery_loop.run_background_jobs = AsyncMock(return_value={})
    monkeypatch.setattr(
        "backend.app.services.abeyance.create_abeyance_services",
        lambda *a, **k: {"discovery_loop": discovery_loop},
    )

    # Mock session maker: list session yields tenant ids; per-tenant sessions
    # support commit(). A single fake session serves both roles.
    session = MagicMock()
    session.commit = AsyncMock()
    scalars = MagicMock()
    scalars.all.return_value = tenant_ids
    execute_result = MagicMock()
    execute_result.scalars.return_value = scalars
    session.execute = AsyncMock(return_value=execute_result)

    @asynccontextmanager
    async def fake_session_maker():
        yield session

    monkeypatch.setattr(
        "backend.app.core.database.async_session_maker", fake_session_maker
    )

    await mod.JOB.run()

    assert discovery_loop.run_background_jobs.await_count == len(tenant_ids)
    called_tenants = {
        call.kwargs["tenant_id"]
        for call in discovery_loop.run_background_jobs.await_args_list
    }
    assert called_tenants == set(tenant_ids)
    # One commit per tenant.
    assert session.commit.await_count == len(tenant_ids)


@pytest.mark.asyncio
async def test_run_isolates_failing_tenant(monkeypatch):
    """A failing tenant does not abort processing of the others."""
    mod = _reload_module(monkeypatch, ABEYANCE_DISCOVERY_ENABLED="true")

    tenant_ids = ["good-1", "bad", "good-2"]

    async def _run_bg(session, tenant_id):
        if tenant_id == "bad":
            raise RuntimeError("boom")
        return {}

    discovery_loop = MagicMock()
    discovery_loop.run_background_jobs = AsyncMock(side_effect=_run_bg)
    monkeypatch.setattr(
        "backend.app.services.abeyance.create_abeyance_services",
        lambda *a, **k: {"discovery_loop": discovery_loop},
    )

    session = MagicMock()
    session.commit = AsyncMock()
    scalars = MagicMock()
    scalars.all.return_value = tenant_ids
    execute_result = MagicMock()
    execute_result.scalars.return_value = scalars
    session.execute = AsyncMock(return_value=execute_result)

    @asynccontextmanager
    async def fake_session_maker():
        yield session

    monkeypatch.setattr(
        "backend.app.core.database.async_session_maker", fake_session_maker
    )

    # Should not raise despite the failing tenant.
    await mod.JOB.run()

    assert discovery_loop.run_background_jobs.await_count == len(tenant_ids)
    # Commit only for the two successful tenants.
    assert session.commit.await_count == 2
