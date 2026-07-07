"""Background abeyance discovery periodic job (default OFF).

Schedules :meth:`DiscoveryLoop.run_background_jobs` once per tenant on a
fixed interval. Deliberately opt-in — the ``ABEYANCE_DISCOVERY_ENABLED``
env var defaults to ``"false"`` so this job is discovered but not
scheduled unless explicitly turned on.

Config (read via ``os.environ``):
    * ``ABEYANCE_DISCOVERY_INTERVAL_SECONDS`` — tick interval, default 21600 (6h).
    * ``ABEYANCE_DISCOVERY_ENABLED`` — ``"true"`` to schedule; default ``"false"``.

Per-tenant isolation: each tenant runs in its own short-lived session with
its own try/except and commit, so one failing tenant never aborts the rest.
"""

from __future__ import annotations

import logging
import os

from backend.app.workers.periodic_jobs import PeriodicJob

logger = logging.getLogger(__name__)


async def _run() -> None:
    """Run background discovery jobs for every tenant, one at a time."""
    from sqlalchemy import select

    from backend.app.core.database import async_session_maker
    from backend.app.models.tenant_orm import TenantORM
    from backend.app.services.abeyance import create_abeyance_services

    services = create_abeyance_services()
    discovery_loop = services["discovery_loop"]

    # Short-lived list session — enumerate tenants, then release.
    async with async_session_maker() as list_session:
        tenant_ids = (await list_session.execute(select(TenantORM.id))).scalars().all()

    ok = 0
    failed = 0
    for tenant_id in tenant_ids:
        try:
            async with async_session_maker() as session:
                await discovery_loop.run_background_jobs(
                    session=session, tenant_id=tenant_id
                )
                await session.commit()
            ok += 1
        except Exception:
            failed += 1
            logger.error(
                "abeyance_discovery failed for tenant %r", tenant_id, exc_info=True
            )

    logger.info(
        "abeyance_discovery run complete: %d tenants ok, %d failed (of %d)",
        ok,
        failed,
        len(tenant_ids),
    )


JOB = PeriodicJob(
    name="abeyance_discovery",
    interval_seconds=int(os.environ.get("ABEYANCE_DISCOVERY_INTERVAL_SECONDS", "21600")),
    enabled=os.environ.get("ABEYANCE_DISCOVERY_ENABLED", "false").lower() == "true",
    run=_run,
)
