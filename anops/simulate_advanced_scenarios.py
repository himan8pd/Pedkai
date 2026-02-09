"""
Producer script for advanced ANOps scenarios.

This script acts as the 'Producer' in an Event-Driven Architecture.
It generates telco metrics and submits them to the Kafka 'pedkai.metrics' topic.
"""

import asyncio
import numpy as np
from datetime import datetime
from typing import List, Dict, Any

from data_fabric.kafka_producer import get_kafka_producer
from data_fabric.kafka_consumer import Topics

async def produce_congestion(producer, entity_id: str = "CELL_LON_002"):
    """
    Produces congestion metric events via Kafka.
    """
    print(f"📈 [Producer] Generating Congestion for {entity_id}...")
    tenant_id = "global-demo"
    
    # 1. Inject Congestion Pattern
    for i in range(5):
        prb_val = 60 + (i * 10)
        lat_val = 20 + (i * 20)
        
        await producer.publish(Topics.METRICS, {
            "tenant_id": tenant_id,
            "entity_id": entity_id,
            "metrics": {
                "prb_utilization_pct": prb_val,
                "latency_ms": lat_val
            },
            "timestamp": datetime.utcnow().isoformat()
        })
        await asyncio.sleep(0.1) 

async def produce_sleeping_cell(producer, entity_id: str = "CELL_LON_003"):
    """
    Produces a "Sleeping Cell" event via Kafka.
    """
    print(f"😴 [Producer] Generating Sleeping Cell for {entity_id}...")
    tenant_id = "global-demo"
    
    await producer.publish(Topics.METRICS, {
        "tenant_id": tenant_id,
        "entity_id": entity_id,
        "metrics": {
            "active_users_count": 0.0
        },
        "timestamp": datetime.utcnow().isoformat()
    })

async def produce_voice_drops(producer, entity_id: str = "IMS_001"):
    """Produces a VoLTE Call Drop Rate (CDR) spike via Kafka."""
    print(f"📞 [Producer] Generating Voice Drop Spike for {entity_id}...")
    tenant_id = "global-demo"
    
    await producer.publish(Topics.METRICS, {
        "tenant_id": tenant_id,
        "entity_id": entity_id,
        "metrics": {
            "volte_cdr_pct": 15.0
        },
        "timestamp": datetime.utcnow().isoformat()
    })

async def run_simulation_suite(producer):
    """Runs all producers."""
    await produce_congestion(producer)
    await produce_sleeping_cell(producer)
    await produce_voice_drops(producer)
    
    print("\n✅ Producers finished submitting events to Kafka.")

async def main():
    """Entry point for Kafka Producer Simulation."""
    producer = await get_kafka_producer()
    await producer.start()
    
    try:
        await run_simulation_suite(producer)
    finally:
        await producer.stop()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
