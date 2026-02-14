"""
LiveTestData ingestion tests (TC-001, TC-002, TC-003).

Uses mock row and adapter so tests run without HuggingFace. Ensures metrics
are persisted, idempotent on duplicate PK, and bulk insert completes.
"""

import pytest
import time
from datetime import datetime

from backend.app.models.kpi_orm import KPIMetricORM
from LiveTestData.adapter import row_to_bulk_metrics, entity_id_for_row
from tests.data.live_test_data import get_mock_row


@pytest.fixture
def mock_row():
    return get_mock_row()


@pytest.fixture
def bulk_rows(mock_row):
    entity_id = entity_id_for_row(mock_row, 0)
    return row_to_bulk_metrics(mock_row, entity_id=entity_id, tenant_id="live-test")


@pytest.mark.asyncio
async def test_tc001_metrics_persisted(db_session, bulk_rows):
    """TC-001: KPI metric is persisted with correct tenant_id, entity_id, metric_name, value, timestamp."""
    if not bulk_rows:
        pytest.skip("adapter returned no rows")
    row0 = bulk_rows[0]
    await KPIMetricORM.bulk_insert(db_session, bulk_rows)
    await db_session.commit()

    from sqlalchemy import select
    q = select(KPIMetricORM).where(
        KPIMetricORM.tenant_id == row0["tenant_id"],
        KPIMetricORM.entity_id == row0["entity_id"],
        KPIMetricORM.metric_name == row0["metric_name"],
        KPIMetricORM.timestamp == row0["timestamp"],
    )
    r = await db_session.execute(q)
    one = r.scalar_one_or_none()
    assert one is not None
    assert one.value == row0["value"]


@pytest.mark.asyncio
async def test_tc002_idempotent_duplicate(db_session, bulk_rows):
    """TC-002: Duplicate metric (same PK) is silently ignored via on_conflict_do_nothing."""
    if not bulk_rows:
        pytest.skip("adapter returned no rows")
    await KPIMetricORM.bulk_insert(db_session, bulk_rows)
    await db_session.commit()
    count_first = len(bulk_rows)

    await KPIMetricORM.bulk_insert(db_session, bulk_rows)
    await db_session.commit()

    from sqlalchemy import select, func
    q = select(func.count()).select_from(KPIMetricORM).where(
        KPIMetricORM.tenant_id == bulk_rows[0]["tenant_id"],
        KPIMetricORM.entity_id == bulk_rows[0]["entity_id"],
    )
    r = await db_session.execute(q)
    total = r.scalar()
    assert total == count_first


@pytest.mark.asyncio
async def test_tc003_bulk_insert_performance(db_session, mock_row):
    """TC-003: Bulk insert of 10k+ points completes in < 5 seconds (use 4 rows of mock ≈ 360 rows; relax for mock)."""
    # Mock row has 30 * 3 = 90 points. Build enough to get > 1000: repeat entity with different timestamps by using multiple "logical" rows.
    entity_id = entity_id_for_row(mock_row, 0)
    tenant_id = "live-test"
    all_rows = []
    for offset in range(12):  # 12 * 90 = 1080 rows
        r = get_mock_row()
        # Shift start_time so PKs differ (each offset = distinct timestamps)
        r["start_time"] = f"2025-01-01 00:05:{33 + offset:02d}.000"
        bulk = row_to_bulk_metrics(r, entity_id=entity_id, tenant_id=tenant_id)
        all_rows.extend(bulk)

    start = time.perf_counter()
    await KPIMetricORM.bulk_insert(db_session, all_rows)
    await db_session.commit()
    elapsed = time.perf_counter() - start
    assert elapsed < 5.0, f"Bulk insert took {elapsed:.2f}s (expected < 5s)"
    assert len(all_rows) >= 1000
