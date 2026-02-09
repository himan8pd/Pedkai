"""
KPI Simulation Script for Pedkai.

Generates baseline KPI data and injects anomalies to test the ANOps pipeline.
"""

(1, 2, 3, 4, 18, 19, 20)
import asyncio
import numpy as np
from datetime import datetime, timedelta
import random
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.app.core.database import get_db_context
from anops.anomaly_detection import AnomalyDetector
from backend.app.models.kpi_orm import KPIMetricORM

async def simulate_kpis(entity_id: str = "CELL_LON_001", metric_name: str = "throughput_mbps"):
    """
    Simulates a stream of KPI values.
    1. Generates 24 hours of baseline data (1 measurement every 15 mins).
    2. Injects a clear anomaly.
    3. Runs the anomaly detector.
    """
    print(f"🎬 Starting KPI simulation for {entity_id} ({metric_name})...")
    
    tenant_id = "global-demo"
    baseline_value = 50.0 # Mbps
    noise_level = 5.0
    
    async with get_db_context() as session:
        detector = AnomalyDetector(session)
        
        # 1. Generate 24 hours of baseline
        print("📊 Generating 24-hour baseline...")
        now = datetime.utcnow()
        for i in range(24 * 4): # Every 15 mins
            ts = now - timedelta(minutes=15 * (96 - i))
            value = max(0, baseline_value + np.random.normal(0, noise_level))
            
            metric = KPIMetricORM(
                tenant_id=tenant_id,
                entity_id=entity_id,
                metric_name=metric_name,
                value=value,
                timestamp=ts,
                tags={"simulated": True}
            )
            session.add(metric)
        
        await session.commit()
        print(f"✅ Baseline seeded with {24*4} points.")
        
        # 2. Add some "current" normal data
        print("📡 Processing current 'normal' data...")
        for i in range(5):
            val = max(0, baseline_value + np.random.normal(0, noise_level))
            await detector.process_metric(tenant_id, entity_id, metric_name, val)
        
        await session.commit()
        
        # 3. Inject an ANOMALY
        print("\n🔥 INJECTING ANOMALY...")
        anomaly_val = baseline_value * 0.2 # 80% drop
        result = await detector.process_metric(tenant_id, entity_id, metric_name, anomaly_val)
        
        if result["is_anomaly"]:
            print(f"✅ Anomaly Detector SUCCESS: Identified {anomaly_val} as anomaly (Score: {result['score']})")
        else:
            print(f"❌ Anomaly Detector FAILED: Did not flag {anomaly_val} (Score: {result['score']})")

if __name__ == "__main__":
    asyncio.run(simulate_kpis())
