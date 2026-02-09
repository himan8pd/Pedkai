"""
Producer script for advanced ANOps scenarios.

This script acts as the 'Producer' in an Event-Driven Architecture.
It generates telco metrics and submits them to the DetectorService.
"""

import asyncio
import numpy as np
from datetime import datetime, timedelta
from typing import List, Dict, Any

from anops.detector_service import service_instance

async def produce_congestion(entity_id: str = "CELL_LON_002"):
    """
    Produces congestion metric events.
    """
    print(f"📈 [Producer] Generating Congestion for {entity_id}...")
    tenant_id = "global-demo"
    
    # 1. Inject Congestion Pattern
    for i in range(5):
        prb_val = 60 + (i * 10)
        lat_val = 20 + (i * 20)
        
        service_instance.submit_event({
            "tenant_id": tenant_id,
            "entity_id": entity_id,
            "metric_name": "prb_utilization_pct",
            "value": prb_val,
            "timestamp": datetime.utcnow().isoformat()
        })
        
        service_instance.submit_event({
            "tenant_id": tenant_id,
            "entity_id": entity_id,
            "metric_name": "latency_ms",
            "value": lat_val,
            "timestamp": datetime.utcnow().isoformat()
        })
        await asyncio.sleep(0.1) # Simulate real-time stream

async def produce_sleeping_cell(entity_id: str = "CELL_LON_003"):
    """
    Produces a "Sleeping Cell" (Silent Failure) event.
    """
    print(f"😴 [Producer] Generating Sleeping Cell for {entity_id}...")
    tenant_id = "global-demo"
    
    # SILENT DROP TO ZERO
    service_instance.submit_event({
        "tenant_id": tenant_id,
        "entity_id": entity_id,
        "metric_name": "active_users_count",
        "value": 0.0,
        "timestamp": datetime.utcnow().isoformat()
    })

async def produce_voice_drops(entity_id: str = "IMS_001"):
    """Produces a VoLTE Call Drop Rate (CDR) spike."""
    print(f"📞 [Producer] Generating Voice Drop Spike for {entity_id}...")
    tenant_id = "global-demo"
    service_instance.submit_event({
        "tenant_id": tenant_id,
        "entity_id": entity_id,
        "metric_name": "volte_cdr_pct",
        "value": 15.0,
        "timestamp": datetime.utcnow().isoformat()
    })

async def run_simulation_suite():
    """Runs all producers and then lets the service process them."""
    # Start the producers
    await produce_congestion()
    await produce_sleeping_cell()
    await produce_voice_drops()
    
    print("\n✅ Producers finished submitting events.")
    # Wait a bit for the consumer to process
    await asyncio.sleep(5)
    service_instance.is_running = False

async def main():
    """Entry point to run both Service and Producers in one process for demo."""
    # Run the service loop in the background
    service_task = asyncio.create_task(service_instance.start())
    
    # Run the simulation suite
    await run_simulation_suite()
    
    # Wait for service to finish
    await service_task

if __name__ == "__main__":
    asyncio.run(main())
