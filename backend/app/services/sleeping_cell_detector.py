from typing import List, Optional
from datetime import datetime, timezone, timedelta
import math

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.database import async_session_maker
from backend.app.models.kpi_sample_orm import KpiSampleORM
from backend.app.events.schemas import SleepingCellDetectedEvent
from backend.app.events.bus import publish_event
from backend.app.core.logging import get_logger

logger = get_logger(__name__)


class SleepingCellDetector:
    """Detect sleeping cells by comparing latest KPI to a 7-day baseline.

    scan(tenant_id) -> list of SleepingCellDetectedEvent
    """

    def __init__(self, window_days: int = 7, z_threshold: float = -3.0, idle_minutes: int = 15):
        self.window_days = window_days
        self.z_threshold = z_threshold
        self.idle_minutes = idle_minutes

    async def scan(self, tenant_id: str) -> List[SleepingCellDetectedEvent]:
        events: List[SleepingCellDetectedEvent] = []

        cutoff = datetime.now(timezone.utc) - timedelta(days=self.window_days)
        idle_cutoff = datetime.now(timezone.utc) - timedelta(minutes=self.idle_minutes)

        async with async_session_maker() as session:  # type: AsyncSession
            # Find distinct entity_ids that are CELL or SECTOR in the samples table
            # If entity_type is stored elsewhere, we conservatively scan all entity_ids
            q = select(
                KpiSampleORM.entity_id,
                func.max(KpiSampleORM.timestamp).label("last_ts")
            ).where(
                KpiSampleORM.tenant_id == tenant_id
            ).group_by(KpiSampleORM.entity_id)

            result = await session.execute(q)
            rows = result.fetchall()

            for row in rows:
                entity_id = row[0]
                last_ts = row[1]

                # Get baseline stats for metric 'traffic_volume'
                stats_q = select(
                    func.avg(KpiSampleORM.value).label("mean"),
                    func.stddev_pop(KpiSampleORM.value).label("std")
                ).where(
                    (KpiSampleORM.tenant_id == tenant_id) &
                    (KpiSampleORM.entity_id == entity_id) &
                    (KpiSampleORM.metric_name == "traffic_volume") &
                    (KpiSampleORM.timestamp >= cutoff)
                )

                stats_res = await session.execute(stats_q)
                stats = stats_res.fetchone()
                mean = stats[0]
                std = stats[1]

                # Get latest sample for traffic_volume
                latest_q = select(KpiSampleORM).where(
                    (KpiSampleORM.tenant_id == tenant_id) &
                    (KpiSampleORM.entity_id == entity_id) &
                    (KpiSampleORM.metric_name == "traffic_volume")
                ).order_by(KpiSampleORM.timestamp.desc()).limit(1)

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
                    logger.debug(f"Insufficient baseline for entity {entity_id} (tenant={tenant_id})")

        return events
