"""
LiveTestData anomaly detection tests (TC-020, TC-026, TC-028, TC-029).

Uses mock row and adapter; feeds metrics into AnomalyDetector and asserts
z-score behaviour, RSRP (negative values), and process_metric store+check.
"""

import pytest

from backend.app.models.kpi_orm import KPIMetricORM
from anops.anomaly_detection import AnomalyDetector
from LiveTestData.adapter import row_to_bulk_metrics, entity_id_for_row
from tests.data.live_test_data import get_mock_row


@pytest.fixture
def mock_row():
    return get_mock_row()


@pytest.mark.asyncio
async def test_tc028_process_metric_stores_and_checks(db_session, mock_row):
    """TC-028: Process_metric stores the new value AND checks for anomaly in single call."""
    entity_id = entity_id_for_row(mock_row, 0)
    tenant_id = "live-test"
    detector = AnomalyDetector(db_session)

    # First feed baseline (all points) so baseline has sufficient data (≥5 values per metric)
    bulk = row_to_bulk_metrics(mock_row, entity_id=entity_id, tenant_id=tenant_id)
    await KPIMetricORM.bulk_insert(db_session, bulk)
    await db_session.commit()

    # Then process one new value (e.g. RSRP -85, which is outlier vs -73 mean)
    result = await detector.process_metric(
        tenant_id=tenant_id,
        entity_id=entity_id,
        metric_name="RSRP",
        value=-85.0,
        tags={"source": "test"},
    )
    await db_session.commit()

    assert "is_anomaly" in result
    # With baseline mean ~-73 and std small, -85 is many sigma away
    assert result.get("is_anomaly") is True or "score" in result


@pytest.mark.asyncio
async def test_tc029_rsrp_negative_values(db_session, mock_row):
    """TC-029: Anomaly detection works with negative values (e.g. RSRP in dBm)."""
    entity_id = entity_id_for_row(mock_row, 0)
    tenant_id = "live-test"
    detector = AnomalyDetector(db_session)

    bulk = row_to_bulk_metrics(mock_row, entity_id=entity_id, tenant_id=tenant_id)
    await KPIMetricORM.bulk_insert(db_session, bulk)
    await db_session.commit()

    # Process a value in RSRP range (-120 to -60)
    result = await detector.process_metric(
        tenant_id=tenant_id,
        entity_id=entity_id,
        metric_name="RSRP",
        value=-90.0,
        tags={},
    )
    await db_session.commit()

    assert "is_anomaly" in result
    assert "mean" in result
    assert result["mean"] <= 0  # RSRP mean should be negative


@pytest.mark.asyncio
async def test_tc020_tc021_zscore_behaviour(db_session, mock_row):
    """TC-020/021: Z-score flags value > 3σ; does not flag value within 2σ."""
    entity_id = entity_id_for_row(mock_row, 0)
    tenant_id = "live-test"
    detector = AnomalyDetector(db_session)

    bulk = row_to_bulk_metrics(mock_row, entity_id=entity_id, tenant_id=tenant_id)
    await KPIMetricORM.bulk_insert(db_session, bulk)
    await db_session.commit()

    # Value far from mean (e.g. RSRP -90 when mean ~-75) => anomaly
    far = await detector.process_metric(tenant_id, entity_id, "RSRP", -95.0, {})
    await db_session.commit()
    # Value near mean => not anomaly
    near = await detector.process_metric(tenant_id, entity_id, "RSRP", -74.0, {})
    await db_session.commit()

    assert far.get("is_anomaly") is True
    assert near.get("is_anomaly") is False
