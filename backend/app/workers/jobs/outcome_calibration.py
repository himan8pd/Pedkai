"""Outcome-calibration periodic job (Feedback Loop A activation).

Periodically invokes :meth:`OutcomeCalibrationService.calibrate` for every
failure-mode weight profile, per tenant. Calibration returns ``None`` when
there are insufficient feedback samples — this is a NORMAL steady state, not
an error, and is logged as ``insufficient_samples``.

Mirrors the per-tenant structure of ``abeyance_maintenance``: lazy imports in
``_run``, a short-lived session to list tenant ids, then a fresh session per
tenant guarded by try/except so one tenant's failure never blocks the rest.
"""

from __future__ import annotations

import logging
import os

from backend.app.workers.periodic_jobs import PeriodicJob

logger = logging.getLogger(__name__)


async def _run() -> None:
    """Calibrate every failure-mode profile for every tenant."""
    from sqlalchemy import select

    from backend.app.core.database import async_session_maker
    from backend.app.models.tenant_orm import TenantORM
    from backend.app.services.abeyance import create_abeyance_services
    from backend.app.services.abeyance.snap_engine_v3 import WEIGHT_PROFILES_V3

    services = create_abeyance_services()
    calibration = services["outcome_calibration"]
    profiles = list(WEIGHT_PROFILES_V3.keys())

    # Short-lived session just to enumerate tenants.
    async with async_session_maker() as session:
        result = await session.execute(select(TenantORM.id))
        tenant_ids = [row[0] for row in result.all()]

    for tenant_id in tenant_ids:
        for profile in profiles:
            try:
                async with async_session_maker() as session:
                    outcome = await calibration.calibrate(session, tenant_id, profile)
                    await session.commit()
                status = "calibrated" if outcome is not None else "insufficient_samples"
                logger.info(
                    "outcome_calibration tenant=%s %s -> %s",
                    tenant_id,
                    profile,
                    status,
                )
            except Exception:
                logger.error(
                    "outcome_calibration failed for tenant=%s profile=%s",
                    tenant_id,
                    profile,
                    exc_info=True,
                )


JOB = PeriodicJob(
    name="outcome_calibration",
    interval_seconds=int(os.environ.get("OUTCOME_CALIBRATION_INTERVAL_SECONDS", "86400")),
    enabled=os.environ.get("OUTCOME_CALIBRATION_ENABLED", "true").lower() == "true",
    run=_run,
)
