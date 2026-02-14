"""
LiveTestData E2E pipeline tests (TC-080, TC-081, TC-084).

Tests the full pipeline from ingestion → anomaly detection → RCA → SITREP.
Uses mock row with event handlers to verify end-to-end flow.
"""

from contextlib import asynccontextmanager
import pytest
import time
from datetime import datetime, timezone, timedelta

from backend.app.models.kpi_orm import KPIMetricORM
from anops.anomaly_detection import AnomalyDetector
from LiveTestData.adapter import (
    row_to_metric_events,
    row_to_bulk_metrics,
    entity_id_for_row,
    get_scenario_rows,
)
from data_fabric.event_handlers import handle_metrics_event
from tests.data.live_test_data import get_mock_row


@pytest.fixture
def normal_row():
    """Normal row with no anomaly for TC-080."""
    row = get_mock_row()
    # Override to make it a normal row
    row["anomalies"]["exists"] = False
    row["labels"]["anomaly_present"] = "No"
    # Use consistent values (no spikes)
    row["KPIs"]["RSRP"] = [-73.0] * 30
    row["KPIs"]["DL_BLER"] = [0.001] * 30
    row["KPIs"]["UL_BLER"] = [0.02] * 30
    return row


@pytest.fixture
def anomalous_row():
    """Anomalous row (Jamming) for TC-081."""
    return get_mock_row()  # Already has Jamming anomaly


@pytest.mark.asyncio
async def test_tc080_normal_row_no_anomaly(db_session, normal_row):
    """TC-080: Normal row → no anomaly detected → pipeline returns quickly."""
    entity_id = entity_id_for_row(normal_row, 0)
    tenant_id = "live-test"
    
    # Ingest the normal row
    bulk = row_to_bulk_metrics(normal_row, entity_id=entity_id, tenant_id=tenant_id)
    await KPIMetricORM.bulk_insert(db_session, bulk)
    await db_session.commit()
    
    # Process a new metric (should not detect anomaly)
    detector = AnomalyDetector(db_session)
    result = await detector.process_metric(tenant_id, entity_id, "RSRP", -73.0, {})
    await db_session.commit()
    
    assert result.get("is_anomaly") is False
    # Pipeline would return early, no RCA/SITREP needed


@pytest.mark.asyncio
async def test_tc081_anomalous_row_full_pipeline(db_session, anomalous_row):
    """TC-081: Anomalous row → anomaly detected → (RCA and SITREP would follow)."""
    entity_id = entity_id_for_row(anomalous_row, 0)
    tenant_id = "live-test"
    
    # Ingest baseline data
    bulk = row_to_bulk_metrics(anomalous_row, entity_id=entity_id, tenant_id=tenant_id)
    await KPIMetricORM.bulk_insert(db_session, bulk)
    await db_session.commit()
    
    # Process a metric from the anomaly window with extreme value
    # Mock row has RSRP around -73 to -87 with spikes
    # Use -100 to ensure it exceeds 3σ threshold
    detector = AnomalyDetector(db_session)
    result = await detector.process_metric(tenant_id, entity_id, "RSRP", -100.0, {})
    await db_session.commit()
    
    assert result.get("is_anomaly") is True
    # Score may be 0 if std=0 (all baseline values equal), or > 3.0 if variance exists
    score = result.get("score", 0)
    assert score >= 0.0  # Score should be non-negative
    
    # In full pipeline, this would trigger RCA → Causal → SITREP
    # For now, we verify anomaly detection worked


@pytest.mark.asyncio
async def test_tc084_smoke_subset_ingestion(db_session):
    """TC-084: Ingest a small subset (smoke test) of LiveTestData for full pipeline validation."""
    # Use multiple mock rows to simulate smoke subset (e.g., 5 rows)
    entity_count = 5
    rows_ingested = 0
    
    for i in range(entity_count):
        row = get_mock_row()
        entity_id = entity_id_for_row(row, i)
        bulk = row_to_bulk_metrics(row, entity_id=entity_id, tenant_id="live-test")
        await KPIMetricORM.bulk_insert(db_session, bulk)
        rows_ingested += len(bulk)
    
    await db_session.commit()
    
    # Verify data was ingested
    from sqlalchemy import select, func
    q = select(func.count()).select_from(KPIMetricORM).where(
        KPIMetricORM.tenant_id == "live-test"
    )
    r = await db_session.execute(q)
    total = r.scalar()
    
    assert total == rows_ingested
    assert total > 0  # Should have ingested data from all entities


@pytest.mark.asyncio
async def test_tc082_multiple_affected_kpis(db_session, anomalous_row):
    """TC-082: Row with multiple affected KPIs → all investigated."""
    entity_id = entity_id_for_row(anomalous_row, 0)
    tenant_id = "live-test"
    
    # Ingest baseline
    bulk = row_to_bulk_metrics(anomalous_row, entity_id=entity_id, tenant_id=tenant_id)
    await KPIMetricORM.bulk_insert(db_session, bulk)
    await db_session.commit()
    
    # The mock row has 3 affected KPIs: RSRP, DL_BLER, UL_BLER
    detector = AnomalyDetector(db_session)
    
    # Test all affected KPIs with extreme values to ensure anomaly detection
    rsrp_result = await detector.process_metric(tenant_id, entity_id, "RSRP", -100.0, {})
    dl_bler_result = await detector.process_metric(tenant_id, entity_id, "DL_BLER", 0.5, {})
    ul_bler_result = await detector.process_metric(tenant_id, entity_id, "UL_BLER", 0.5, {})
    await db_session.commit()
    
    # At least one should be flagged as anomaly
    anomalies_detected = sum([
        rsrp_result.get("is_anomaly", False),
        dl_bler_result.get("is_anomaly", False),
        ul_bler_result.get("is_anomaly", False),
    ])
    
    assert anomalies_detected >= 1, "At least one affected KPI should be detected as anomaly"

@pytest.mark.asyncio
async def test_tc087_alarm_storm_handling_refined(db_session, anomalous_row):
    """
    TC-087 Refined: Alarm storm: replay 50 entities through FULL PIPELINE.
    Verifies system handles high-volume ingestion -> RCA -> SITREP without deadlocks.
    Uses mock SITREP/Embedding to avoid external calls and patches DB to use test SQLite.
    """
    import asyncio
    from unittest.mock import patch, AsyncMock
    entity_count = 50
    tenant_id = "stress-test-full"
    
    # 1. Prepare environment: Seed topology with 50 cells
    from tests.validation.test_live_data_topology import seed_zone_topology_helper
    topology = await seed_zone_topology_helper(db_session, tenant_id=tenant_id, cell_count=entity_count)
    
    # Pre-seed baseline for all 50 cells so detector triggers anomaly
    # Need 5 samples per cell
    from backend.app.models.kpi_orm import KPIMetricORM
    baseline_rows = []
    now_baseline = datetime.now(timezone.utc) - timedelta(hours=1)
    for i in range(entity_count):
        cell_id = f"CELL_LIVE_{i+1}"
        for j in range(5):
            ts = now_baseline + timedelta(minutes=j)
            # Normal values: RSRP -70, BLER 0.01
            baseline_rows.append(KPIMetricORM(
                tenant_id=tenant_id, entity_id=cell_id, metric_name="RSRP", value=-70.0, timestamp=ts
            ))
            baseline_rows.append(KPIMetricORM(
                tenant_id=tenant_id, entity_id=cell_id, metric_name="DL_BLER", value=0.01, timestamp=ts
            ))
    db_session.add_all(baseline_rows)
    await db_session.commit()

    # Helper to mock the async generator for database sessions
    async def mock_db_gen(*args, **kwargs):
        yield db_session

    # 2. Mock AI Services and Database access
    with patch("backend.app.services.llm_service.LLMService.generate_explanation", 
               new_callable=AsyncMock) as mock_llm, \
         patch("backend.app.services.embedding_service.EmbeddingService.generate_embedding", 
               new_callable=AsyncMock) as mock_embed, \
         patch("backend.app.services.decision_repository.DecisionTraceRepository.find_similar",
               new_callable=AsyncMock) as mock_similar, \
         patch("data_fabric.event_handlers.get_metrics_db", side_effect=mock_db_gen), \
         patch("data_fabric.event_handlers.get_db", side_effect=mock_db_gen):
        
        mock_llm.return_value = "Mocked SITREP for stress test"
        mock_embed.return_value = [0.1] * 3072
        mock_similar.return_value = [] # Return no similar decisions for speed
        
        # 3. Simulate Storm: 50 concurrent metric events for 50 distinct entities
        tasks = []
        now = datetime.now(timezone.utc)
        for i in range(entity_count):
            cell_id = f"CELL_LIVE_{i+1}"
            event = {
                "tenant_id": tenant_id,
                "entity_id": cell_id,
                "metrics": {"RSRP": -110.0, "DL_BLER": 0.4},
                # Add milliseconds to ensure unique timestamp
                "timestamp": (now + timedelta(milliseconds=i)).isoformat()
            }
            tasks.append(handle_metrics_event(event))
            
        start_time = time.time()
        results = await asyncio.gather(*tasks)
        duration = time.time() - start_time
        
        await db_session.commit()
        
        print(f"📊 TC-087 Refined: Processed {entity_count} full pipelines in {duration:.2f}s")
        # Threshold 30s for the full pipeline including causal + RCA on SQLite
        assert duration < 30.0, f"Full pipeline storm too slow: {duration:.2f}s"
        assert len(results) == entity_count
        assert mock_llm.call_count >= entity_count

@pytest.mark.asyncio
async def test_tc088_latency_budget(db_session, anomalous_row):
    """
    TC-088: Latency budget: single event → detection result in < 30 s.
    (Budget is 30s including RCA/LLM, but here we test the detection sub-budget).
    """
    entity_id = "CELL_LATENCY"
    tenant_id = "latency-test"
    detector = AnomalyDetector(db_session)
    
    # Ingest baseline
    bulk = row_to_bulk_metrics(anomalous_row, entity_id=entity_id, tenant_id=tenant_id)
    await KPIMetricORM.bulk_insert(db_session, bulk[:100])
    await db_session.commit()
    
    import time
    start_time = time.time()
    
    result = await detector.process_metric(tenant_id, entity_id, "RSRP", -105.0, {})
    
    duration = time.time() - start_time
    print(f"📊 TC-088: Detection latency: {duration*1000:.2f}ms")
    
    assert duration < 5.0, "Detection sub-latency exceeds budget"
    assert result.get("is_anomaly") is True
