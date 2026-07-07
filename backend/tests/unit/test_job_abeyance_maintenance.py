"""Unit tests for the abeyance maintenance periodic job.

Verifies that ``_run``:
    * calls ``run_full_maintenance`` once per tenant and commits each session,
    * isolates per-tenant failures so a raising first tenant does not prevent
      the second from being processed.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.app.workers.jobs import abeyance_maintenance


def _make_session_maker(sessions):
    """Return a callable that yields the given sessions as async CMs.

    Each call to the returned maker pops the next session from ``sessions`` and
    wraps it in an object usable as ``async with ... as session``.
    """
    iterator = iter(sessions)

    def maker():
        session = next(iterator)

        class _Ctx:
            async def __aenter__(self):
                return session

            async def __aexit__(self, *exc):
                return False

        return _Ctx()

    return maker


def _patch_common(monkeypatch, maintenance, tenant_sessions, tenant_ids):
    """Patch session maker, services factory, and tenant query on the module."""
    # First session is for the tenant-list query; the rest are per-tenant.
    list_session = MagicMock()
    execute_result = MagicMock()
    execute_result.all.return_value = [(tid,) for tid in tenant_ids]
    list_session.execute = AsyncMock(return_value=execute_result)

    all_sessions = [list_session, *tenant_sessions]
    maker = _make_session_maker(all_sessions)

    monkeypatch.setattr(
        "backend.app.core.database.async_session_maker", maker, raising=False
    )
    monkeypatch.setattr(
        "backend.app.services.abeyance.create_abeyance_services",
        lambda *a, **k: {"maintenance": maintenance},
    )
    # select() is called with TenantORM.id; a stubbed model keeps it importable.
    return list_session


@pytest.mark.asyncio
async def test_run_processes_every_tenant(monkeypatch):
    maintenance = MagicMock()
    maintenance.run_full_maintenance = AsyncMock(return_value={})

    tenant_ids = ["tenant_a", "tenant_b"]
    s1 = MagicMock()
    s1.commit = AsyncMock()
    s2 = MagicMock()
    s2.commit = AsyncMock()

    _patch_common(monkeypatch, maintenance, [s1, s2], tenant_ids)

    await abeyance_maintenance._run()

    assert maintenance.run_full_maintenance.await_count == 2
    called_tenants = {
        c.args[1] for c in maintenance.run_full_maintenance.await_args_list
    }
    assert called_tenants == {"tenant_a", "tenant_b"}
    assert s1.commit.await_count == 1
    assert s2.commit.await_count == 1


@pytest.mark.asyncio
async def test_run_isolates_failing_tenant(monkeypatch):
    maintenance = MagicMock()
    # First tenant raises; second must still be processed.
    maintenance.run_full_maintenance = AsyncMock(
        side_effect=[RuntimeError("boom"), {}]
    )

    tenant_ids = ["tenant_a", "tenant_b"]
    s1 = MagicMock()
    s1.commit = AsyncMock()
    s2 = MagicMock()
    s2.commit = AsyncMock()

    _patch_common(monkeypatch, maintenance, [s1, s2], tenant_ids)

    await abeyance_maintenance._run()

    assert maintenance.run_full_maintenance.await_count == 2
    # First tenant raised before commit; second committed successfully.
    assert s1.commit.await_count == 0
    assert s2.commit.await_count == 1
