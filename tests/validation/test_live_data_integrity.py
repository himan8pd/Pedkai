"""
LiveTestData integrity tests (TC-006, TC-027a).
Addresses security and robustness audit gaps.
"""

import pytest
from backend.app.models.kpi_orm import KPIMetricORM
from anops.anomaly_detection import AnomalyDetector
from LiveTestData.adapter import row_to_bulk_metrics, entity_id_for_row
from tests.data.live_test_data import get_mock_row

@pytest.mark.asyncio
async def test_tc006_null_nan_handling(db_session):
    """
    TC-006: NULL/NaN values are handled gracefully.
    Checks that adapter/ingestion don't crash and detector ignores invalid values.
    """
    row = get_mock_row()
    # Inject NaN and None
    row["KPIs"]["RSRP"][0] = float('nan')
    row["KPIs"]["RSRP"][1] = None
    
    entity_id = "CELL_NULL_TEST"
    tenant_id = "integrity-test"
    
    # Adapter should handle or omit
    bulk = row_to_bulk_metrics(row, entity_id=entity_id, tenant_id=tenant_id)
    
    # Check if NaN/None made it through (adapter current impl converts to float which might be NaN)
    # Most DBs don't like NaN in numeric columns unless handled
    await KPIMetricORM.bulk_insert(db_session, bulk)
    await db_session.commit()
    
    detector = AnomalyDetector(db_session)
    # Should not crash on process_metric if baseline has valid points
    result = await detector.process_metric(tenant_id, entity_id, "RSRP", -80.0, {})
    assert "is_anomaly" in result

@pytest.mark.asyncio
async def test_tc027a_multi_tenant_isolation(db_session):
    """
    TC-027a: Multi-tenant baseline isolation.
    Tenant A's data must NOT affect Tenant B's anomaly detection baseline.
    """
    from datetime import datetime, timezone, timedelta
    
    entity_id = "CELL_SHARED" # Same entity ID in different tenants
    now = datetime.now(timezone.utc)
    
    # Tenant A has high values (baseline ~100)
    metrics_a = [
        KPIMetricORM(tenant_id="tenant-a", entity_id=entity_id, metric_name="RSRP", value=100.0, timestamp=now - timedelta(minutes=i))
        for i in range(10)
    ]
    db_session.add_all(metrics_a)
    
    # Tenant B has low values (baseline ~10)
    metrics_b = [
        KPIMetricORM(tenant_id="tenant-b", entity_id=entity_id, metric_name="RSRP", value=10.0, timestamp=now - timedelta(minutes=i))
        for i in range(10)
    ]
    db_session.add_all(metrics_b)
    await db_session.commit()
    
    detector = AnomalyDetector(db_session)
    
    # Check Tenant B with value 15 (should be "normal-ish" for 10, but anomaly if mixed with 100)
    # Baseline for B should be mean=10, std=0.
    result_b = await detector.process_metric("tenant-b", entity_id, "RSRP", 15.0, {})
    
    # If isolation works, mean=10.0. If mixed, mean=(100+10)/2 = 55.0.
    assert result_b.get("mean") == 10.0
    assert result_b.get("is_anomaly") is True # 15 vs 10 with std=0 is anomaly
    
    # Check Tenant A with value 95 (normal for 100, anomaly if mixed with 10)
    result_a = await detector.process_metric("tenant-a", entity_id, "RSRP", 95.0, {})
    assert result_a.get("mean") == 100.0
    assert result_a.get("is_anomaly") is True # 95 vs 100 with std=0 is anomaly
