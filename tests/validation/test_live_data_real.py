"""
Real data integration tests for Pedkai.
Validates adapter and ingestion using the actual 32k-row telecom dataset.
"""

import pytest
import time
from backend.app.models.kpi_orm import KPIMetricORM
from LiveTestData.loader import load_dataset_rows
from LiveTestData.adapter import row_to_bulk_metrics, entity_id_for_row

@pytest.mark.asyncio
async def test_real_dataset_integration_ingestion(db_session):
    """
    Validation with real HuggingFace data instead of mock rows.
    Ensures adapter and ingestion work with the actual dataset structure.
    """
    # Load 2 real rows
    rows = load_dataset_rows(limit=2)
    assert len(rows) == 2
    
    total_metrics = 0
    for i, row in enumerate(rows):
        entity_id = entity_id_for_row(row, i)
        bulk = row_to_bulk_metrics(row, entity_id=entity_id, tenant_id="real-data-test")
        await KPIMetricORM.bulk_insert(db_session, bulk)
        total_metrics += len(bulk)
        
    await db_session.commit()
    
    # Verify count
    from sqlalchemy import select, func
    q = select(func.count()).select_from(KPIMetricORM).where(
        KPIMetricORM.tenant_id == "real-data-test"
    )
    r = await db_session.execute(q)
    total = r.scalar()
    
    assert total == total_metrics
    assert total > 0

@pytest.mark.asyncio
async def test_tc003_bulk_insert_performance_scaled(db_session):
    """
    TC-003: Scaled bulk insert performance validation.
    Plan requires 10k+ points in < 5 seconds.
    5 rows * 2540 points/row = 12,700 points.
    """
    rows = load_dataset_rows(limit=5)
    all_metrics = []
    
    for i, row in enumerate(rows):
        entity_id = entity_id_for_row(row, i)
        bulk = row_to_bulk_metrics(row, entity_id=entity_id, tenant_id="perf-test")
        all_metrics.extend(bulk)
        
    start_time = time.time()
    await KPIMetricORM.bulk_insert(db_session, all_metrics)
    await db_session.commit()
    duration = time.time() - start_time
    
    print(f"📊 TC-003: Inserted {len(all_metrics)} points in {duration:.2f}s")
    
    assert len(all_metrics) >= 10000
    assert duration < 5.0, f"Bulk insert too slow: {duration:.2f}s for {len(all_metrics)} points"

@pytest.mark.asyncio
async def test_data_quality_report_real(db_session):
    """
    Verifies data quality report functionality on real data (as requested by audit).
    """
    from LiveTestData.adapter import data_quality_report
    rows = load_dataset_rows(limit=10)
    
    report = data_quality_report(rows)
    
    assert "per_kpi" in report
    assert "rows_checked" in report
    assert len(report["per_kpi"]) > 0
    # Audit reported this was UNUSED - now validated.

@pytest.mark.asyncio
async def test_tc026_false_positive_rate_real_data(db_session):
    """
    TC-026: Normal row FPR < 5% on real data.
    Finds normal rows in real dataset and verifies anomaly detector doesn't flag them.
    """
    from LiveTestData.loader import load_dataset_rows
    from LiveTestData.adapter import get_scenario_rows
    
    # Load rows where we know normal rows exist [1235+]
    # Slice 1000 to 1500 gives a good mix
    all_rows = load_dataset_rows(limit=1500)[1000:1500]
    normal_scenarios = get_scenario_rows(all_rows, anomaly_present=False)
    if len(normal_scenarios) < 10:
        pytest.skip(f"Not enough normal rows in dataset slice (found {len(normal_scenarios)})")
        
    tenant_id = "fpr-test"
    from anops.anomaly_detection import AnomalyDetector
    detector = AnomalyDetector(db_session)
    
    flagged_count = 0
    total_processed = 0
    
    for i, (idx, row) in enumerate(normal_scenarios[:20]):
        entity_id = f"CELL_NORMAL_{i}"
        # Ingest baseline
        bulk = row_to_bulk_metrics(row, entity_id=entity_id, tenant_id=tenant_id)
        await KPIMetricORM.bulk_insert(db_session, bulk)
        
        # Test a value from the same row (should be normal)
        # Use first metric (RSRP) and a value from the sequence
        metric_name = "RSRP"
        test_val = row["KPIs"][metric_name][0]
        
        result = await detector.process_metric(tenant_id, entity_id, metric_name, test_val, {})
        if result.get("is_anomaly"):
            flagged_count += 1
        total_processed += 1
        
    await db_session.commit()
    
    fpr = flagged_count / total_processed
    print(f"📊 TC-026: FPR = {fpr*100:.2f}% ({flagged_count}/{total_processed})")
    assert fpr < 0.05, f"False Positive Rate too high: {fpr*100:.2f}%"

@pytest.mark.asyncio
async def test_tc020_ground_truth_anomaly_validation(db_session):
    """
    TC-020: Verifies detector flags known anomalies from dataset labels.
    """
    from LiveTestData.loader import load_dataset_rows
    from LiveTestData.adapter import get_scenario_rows
    from anops.anomaly_detection import AnomalyDetector
    
    # Use mixed slice
    all_rows = load_dataset_rows(limit=1500)[1000:1500]
    anom_scenarios = get_scenario_rows(all_rows, anomaly_present=True)
    normal_scenarios = get_scenario_rows(all_rows, anomaly_present=False)
    
    if not anom_scenarios or not normal_scenarios:
        pytest.skip("Missing anomalous or normal rows in slice")
        
    tenant_id = "ground-truth-test"
    detector = AnomalyDetector(db_session)
    detected_count = 0
    
    # Use one normal row to build the baseline for an entity
    _, normal_row = normal_scenarios[0]
    
    for i, (idx, anom_row) in enumerate(anom_scenarios[:10]):
        entity_id = f"CELL_GROUND_{i}"
        
        # Ingest baseline from Normal row
        bulk_norm = row_to_bulk_metrics(normal_row, entity_id=entity_id, tenant_id=tenant_id)
        await KPIMetricORM.bulk_insert(db_session, bulk_norm)
        
        # Test an affected KPI from Anomalous row
        affected_kpis = anom_row["anomalies"].get("affected_kpis", [])
        if not affected_kpis: continue
        metric_name = affected_kpis[0]
        
        # Use a point that is labeled as anomaly (start=0 for Jamming usually)
        # Using index 50 to ensure baseline is stable
        test_val = anom_row["KPIs"][metric_name][50] 
        
        result = await detector.process_metric(tenant_id, entity_id, metric_name, test_val, {})
        if result.get("is_anomaly"):
            detected_count += 1
            
    await db_session.commit()
    
    # We expect at least one detection from the sample
    assert detected_count > 0, "Failed to detect any ground truth anomalies from dataset"
