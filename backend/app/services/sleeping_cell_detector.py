from datetime import datetime, timedelta, timezone
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.database import metrics_session_maker
from backend.app.core.logging import get_logger
from backend.app.events.bus import publish_event
from backend.app.events.schemas import SleepingCellDetectedEvent
from backend.app.models.kpi_orm import KPIMetricORM

logger = get_logger(__name__)


class SleepingCellDetector:
    """Detect sleeping cells by comparing latest KPI to a 7-day baseline.

    scan(tenant_id, reference_time=None) -> list of SleepingCellDetectedEvent

    For historic datasets where data is timestamped in the past (e.g. Jan 2024),
    pass ``reference_time`` so that the detector uses data-relative windows
    instead of ``datetime.now()``.  When ``reference_time`` is *None* the
    detector defaults to wall-clock time (live mode).
    """

    def __init__(
        self, window_days: int = 7, z_threshold: float = -3.0, idle_minutes: int = 15
    ):
        self.window_days = window_days
        self.z_threshold = z_threshold
        self.idle_minutes = idle_minutes

    async def scan(
        self,
        tenant_id: str,
        reference_time: Optional[datetime] = None,
    ) -> List[SleepingCellDetectedEvent]:
        """Run a sleeping-cell scan for *tenant_id*.

        Parameters
        ----------
        tenant_id:
            Tenant to scan.
        reference_time:
            Optional anchor timestamp.  When provided the detector treats this
            as "now" so that baseline windows and idle cut-offs are relative to
            the actual data range rather than the system clock.  This is
            essential for historic / demo mode where the most recent KPI row
            may be months or years in the past.
        """
        events: List[SleepingCellDetectedEvent] = []

        now = reference_time or datetime.now(timezone.utc)
        cutoff = now - timedelta(days=self.window_days)
        idle_cutoff = now - timedelta(minutes=self.idle_minutes)

        async with metrics_session_maker() as session:  # type: AsyncSession
            # Find distinct entity_ids with their most-recent timestamp
            q = (
                select(
                    KPIMetricORM.entity_id,
                    func.max(KPIMetricORM.timestamp).label("last_ts"),
                )
                .where(
                    KPIMetricORM.tenant_id == tenant_id,
                )
                .group_by(KPIMetricORM.entity_id)
            )

            result = await session.execute(q)
            rows = result.fetchall()

            for row in rows:
                entity_id = row[0]
                last_ts = row[1]

                # Get baseline stats for metric 'traffic_volume'
                stats_q = select(
                    func.avg(KPIMetricORM.value).label("mean"),
                    func.stddev_pop(KPIMetricORM.value).label("std"),
                ).where(
                    (KPIMetricORM.tenant_id == tenant_id)
                    & (KPIMetricORM.entity_id == entity_id)
                    & (KPIMetricORM.metric_name == "traffic_volume")
                    & (KPIMetricORM.timestamp >= cutoff)
                )

                stats_res = await session.execute(stats_q)
                stats = stats_res.fetchone()
                mean = stats[0]
                std = stats[1]

                # Get latest sample for traffic_volume
                latest_q = (
                    select(KPIMetricORM)
                    .where(
                        (KPIMetricORM.tenant_id == tenant_id)
                        & (KPIMetricORM.entity_id == entity_id)
                        & (KPIMetricORM.metric_name == "traffic_volume")
                    )
                    .order_by(KPIMetricORM.timestamp.desc())
                    .limit(1)
                )

                latest_res = await session.execute(latest_q)
                latest = latest_res.scalars().first()

                if not latest:
                    # No samples at all — treat as idle
                    evt = SleepingCellDetectedEvent(
                        tenant_id=tenant_id,
                        entity_id=entity_id,
                        z_score=float("nan"),
                        baseline_mean=0.0,
                        current_value=None,
                        metric_name="traffic_volume",
                    )
                    events.append(evt)
                    await publish_event(evt)
                    continue

                # If latest sample older than idle_cutoff, flag absence of signal
                if latest.timestamp < idle_cutoff:
                    evt = SleepingCellDetectedEvent(
                        tenant_id=tenant_id,
                        entity_id=entity_id,
                        z_score=float("nan"),
                        baseline_mean=float(mean) if mean is not None else 0.0,
                        current_value=None,
                        metric_name="traffic_volume",
                    )
                    events.append(evt)
                    await publish_event(evt)
                    continue

                # If we have baseline mean/std, compute z-score
                if mean is not None and std is not None and std > 0:
                    z = (latest.value - mean) / std
                    if z < self.z_threshold:
                        evt = SleepingCellDetectedEvent(
                            tenant_id=tenant_id,
                            entity_id=entity_id,
                            z_score=z,
                            baseline_mean=float(mean),
                            current_value=float(latest.value),
                            metric_name="traffic_volume",
                        )
                        events.append(evt)
                        await publish_event(evt)
                else:
                    # Not enough baseline data; skip
                    logger.debug(
                        f"Insufficient baseline for entity {entity_id} "
                        f"(tenant={tenant_id})"
                    )

        return events
