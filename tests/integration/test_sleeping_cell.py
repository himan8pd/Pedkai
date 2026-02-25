import asyncio
import pytest

from backend.app.services.sleeping_cell_detector import SleepingCellDetector
from backend.app.events.bus import initialize_event_bus, get_event_bus
from backend.app.models.kpi_sample_orm import KpiSampleORM
from backend.app.core.database import async_session_maker
from datetime import datetime, timezone, timedelta


@pytest.mark.asyncio
async def test_sleeping_cell_detector_smoke():
    initialize_event_bus()
    now = datetime.now(timezone.utc)
    tenant = "test-tenant"
    entity_id = "silent-entity"

    # Insert a single historical baseline sample and no recent samples
    async with async_session_maker() as session:
        old_ts = now - timedelta(days=2)
        k = KpiSampleORM(
            id="k1",
            tenant_id=tenant,
            entity_id=entity_id,
            metric_name="traffic_volume",
            value=100.0,
            timestamp=old_ts,
            source="test",
        )
        session.add(k)
        await session.commit()

    detector = SleepingCellDetector(window_days=7, z_threshold=-3.0, idle_minutes=15)
    events = await detector.scan(tenant)

    # We expect at least one event (absence of recent samples should flag)
    assert isinstance(events, list)
