"""
Simulation script for advanced ANOps scenarios:
1. Congestion Management (PRB Utilization vs Latency)
2. Sleeping Cell Detection (Silent Failure)
"""

import asyncio
import numpy as np
from datetime import datetime, timedelta
from typing import List, Dict, Any

from backend.app.core.database import get_db_context
from backend.app.models.kpi_orm import KPIMetricORM
from anops.anomaly_detection import AnomalyDetector

async def simulate_congestion(entity_id: str = "CELL_LON_002"):
    """
    Simulates a congestion event:
    - PRB Utilization climbs to 98%
    - Latency correlates and spikes
    """
    print(f"📈 Simulating Congestion for {entity_id}...")
    tenant_id = "global-demo"
    now = datetime.utcnow()
    
    async with get_db_context() as session:
        detector = AnomalyDetector(session)
        
        # 1. 24h Baseline (Normal Load)
        print("  - Seeding 24h baseline...")
        for i in range(24 * 4):
            ts = now - timedelta(minutes=15 * (100 - i))
            prb = max(10, 40 + np.random.normal(0, 5))
            latency = max(5, 15 + np.random.normal(0, 2))
            
            session.add(KPIMetricORM(tenant_id=tenant_id, entity_id=entity_id, metric_name="prb_utilization_pct", value=prb, timestamp=ts))
            session.add(KPIMetricORM(tenant_id=tenant_id, entity_id=entity_id, metric_name="latency_ms", value=latency, timestamp=ts))
        
        await session.commit()
        
        # 2. Inject Congestion
        print("  - Injecting congestion spike...")
        for i in range(5):
            # PRB climbs: 60, 75, 85, 95, 99
            prb_val = 60 + (i * 10)
            lat_val = 20 + (i * 20) # Latency spikes more aggressively
            
            await detector.process_metric(tenant_id, entity_id, "prb_utilization_pct", prb_val)
            res = await detector.process_metric(tenant_id, entity_id, "latency_ms", lat_val)
            
            if res["is_anomaly"]:
                print(f"    [!] Detected latency anomaly: {lat_val}ms at {prb_val}% PRB (Score: {res['score']})")

async def simulate_sleeping_cell(entity_id: str = "CELL_LON_003"):
    """
    Simulates a "Sleeping Cell" (Silent Failure):
    - Users drop to 0 suddenly while site is 'UP'
    """
    print(f"😴 Simulating Sleeping Cell for {entity_id}...")
    tenant_id = "global-demo"
    now = datetime.utcnow()
    
    async with get_db_context() as session:
        detector = AnomalyDetector(session)
        
        # 1. Baseline
        for i in range(24 * 4):
            ts = now - timedelta(minutes=15 * (100 - i))
            users = max(50, 150 + np.random.normal(0, 15))
            session.add(KPIMetricORM(tenant_id=tenant_id, entity_id=entity_id, metric_name="active_users_count", value=users, timestamp=ts))
            
        await session.commit()
        
        # 2. SILENT DROP TO ZERO
        print("  - Injecting silent failure (active_users -> 0)...")
        res = await detector.process_metric(tenant_id, entity_id, "active_users_count", 0.0)
        
        if res["is_anomaly"]:
            print(f"    [!] Detected Sleeping Cell: Users dropped to 0 (Score: {res['score']})")
        else:
            print(f"    [?] Failed to detect drop to zero. Score: {res['score']}")

async def simulate_voice_drops(entity_id: str = "IMS_001"):
    """Simulates a VoLTE Call Drop Rate (CDR) spike."""
    print(f"📞 Simulating Voice Drop Spike for {entity_id}...")
    tenant_id = "global-demo"
    now = datetime.utcnow()
    async with get_db_context() as session:
        detector = AnomalyDetector(session)
        for i in range(24 * 4): # Baseline
            ts = now - timedelta(minutes=15 * (100 - i))
            cdr = max(0.1, 0.5 + np.random.normal(0, 0.1))
            session.add(KPIMetricORM(tenant_id=tenant_id, entity_id=entity_id, metric_name="volte_cdr_pct", value=cdr, timestamp=ts))
        await session.commit()
        print("  - Injecting VoLTE drop spike (0.5% -> 15%)...")
        res = await detector.process_metric(tenant_id, entity_id, "volte_cdr_pct", 15.0)
        if res["is_anomaly"]:
            print(f"    [!] Detected Voice Reliability Issue: CDR at 15% (Score: {res['score']})")

async def simulate_smsc_latency(entity_id: str = "SMSC_001"):
    """Simulates SMS delivery latency spike."""
    print(f"💬 Simulating SMSC Latency Spike for {entity_id}...")
    tenant_id = "global-demo"
    now = datetime.utcnow()
    async with get_db_context() as session:
        detector = AnomalyDetector(session)
        for i in range(24 * 4):
            ts = now - timedelta(minutes=15 * (100 - i))
            latency = max(0.5, 2.0 + np.random.normal(0, 0.5))
            session.add(KPIMetricORM(tenant_id=tenant_id, entity_id=entity_id, metric_name="sms_latency_sec", value=latency, timestamp=ts))
        await session.commit()
        print("  - Injecting SMS latency spike (2s -> 65s)...")
        res = await detector.process_metric(tenant_id, entity_id, "sms_latency_sec", 65.0)
        if res["is_anomaly"]:
            print(f"    [!] Detected SMS Delivery Issue: Latency at 65s (Score: {res['score']})")

async def simulate_emergency_blockage(entity_id: str = "EXCH_001"):
    """Simulates blockage of emergency dial-outs at the exchange."""
    print(f"🚨 Simulating Emergency Dial-out Blockage for {entity_id}...")
    tenant_id = "global-demo"
    now = datetime.utcnow()
    async with get_db_context() as session:
        detector = AnomalyDetector(session)
        for i in range(24 * 4):
            ts = now - timedelta(minutes=15 * (100 - i))
            failure_rate = max(0.0, 0.01 + np.random.normal(0, 0.005))
            session.add(KPIMetricORM(tenant_id=tenant_id, entity_id=entity_id, metric_name="emergency_failure_rate_pct", value=failure_rate, timestamp=ts))
        await session.commit()
        print("  - Injecting Emergency failure spike (0.01% -> 25%)...")
        res = await detector.process_metric(tenant_id, entity_id, "emergency_failure_rate_pct", 25.0)
        if res["is_anomaly"]:
            print(f"    [!] CRITICAL: Emergency Dial-out Blockage Detected (Score: {res['score']})")

async def main():
    await simulate_congestion()
    await simulate_sleeping_cell()
    await simulate_voice_drops()
    await simulate_smsc_latency()
    await simulate_emergency_blockage()
    print("\n✅ All multi-service simulations complete.")

if __name__ == "__main__":
    asyncio.run(main())
