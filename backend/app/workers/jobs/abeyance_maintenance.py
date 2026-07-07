"""Periodic abeyance maintenance job.

Runs :meth:`MaintenanceService.run_full_maintenance` for every tenant on a
fixed interval (default 6h). Each tenant is processed in its own session with
per-tenant error isolation so one tenant's failure does not stop the others.

Discovered automatically by ``backend.app.workers.periodic_jobs`` via the
module-level ``JOB`` attribute.

Config (read from the environment):
    * ``ABEYANCE_MAINTENANCE_INTERVAL_SECONDS`` — tick interval (default 21600).
    * ``ABEYANCE_MAINTENANCE_ENABLED`` — ``"true"``/``"false"`` (default true).
"""

from __future__ import annotations

import logging
import os

from sqlalchemy import select

from backend.app.workers.periodic_jobs import PeriodicJob

logger = logging.getLogger(__name__)


async def _run() -> None:
    """Run full maintenance for every tenant, one session per tenant."""
    # Imported lazily so a broken import elsewhere can't crash discovery, and
    # so tests can monkeypatch these symbols on this module.
    from backend.app.core.database import async_session_maker
    from backend.app.models.tenant_orm import TenantORM
    from backend.app.services.abeyance import create_abeyance_services

    services = create_abeyance_services()
    maintenance = services["maintenance"]

    # Fetch the tenant list in its own short-lived session.
    async with async_session_maker() as session:
        result = await session.execute(select(TenantORM.id))
        tenant_ids = [row[0] for row in result.all()]

    succeeded = 0
    failed = 0
    for tenant_id in tenant_ids:
        try:
            async with async_session_maker() as session:
                await maintenance.run_full_maintenance(session, tenant_id)
                await session.commit()
            succeeded += 1
        except Exception:
            failed += 1
            logger.error(
                "Abeyance maintenance failed for tenant %r", tenant_id, exc_info=True
            )

    logger.info(
        "Abeyance maintenance complete: %d/%d tenants ok, %d failed",
        succeeded,
        len(tenant_ids),
        failed,
    )


JOB = PeriodicJob(
    name="abeyance_maintenance",
    interval_seconds=int(os.environ.get("ABEYANCE_MAINTENANCE_INTERVAL_SECONDS", "21600")),
    enabled=os.environ.get("ABEYANCE_MAINTENANCE_ENABLED", "true").lower() == "true",
    run=_run,
)
