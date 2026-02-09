"""
Detector Service for Pedkai.

This service acts as a 'Consumer' in an Event-Driven Architecture.
It listens for metric events (simulated via an internal queue for now)
and executes anomaly detection logic.
"""

import asyncio
import json
import logging
from typing import Dict, Any, Optional
from datetime import datetime

from backend.app.core.database import get_db_context
from anops.anomaly_detection import AnomalyDetector
from backend.app.models.decision_trace_orm import DecisionTraceORM
from backend.app.services.embedding_service import get_embedding_service

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("DetectorService")

class DetectorService:
    def __init__(self, batch_size: int = 50, batch_timeout_s: float = 2.0):
        self.queue = asyncio.Queue()
        self.is_running = False
        self.batch_size = batch_size
        self.batch_timeout_s = batch_timeout_s

    async def start(self):
        """Starts the main consumption loop with batching."""
        logger.info(f"🚀 Starting Pedkai Detector Service (Batch Size: {self.batch_size})...")
        self.is_running = True
        
        while self.is_running:
            batch = []
            try:
                # Try to get first item
                event = await self.queue.get()
                batch.append(event)
                
                # Fill batch with timeout
                start_time = asyncio.get_event_loop().time()
                while len(batch) < self.batch_size:
                    wait_time = self.batch_timeout_s - (asyncio.get_event_loop().time() - start_time)
                    if wait_time <= 0:
                        break
                    try:
                        event = await asyncio.wait_for(self.queue.get(), timeout=wait_time)
                        batch.append(event)
                    except asyncio.TimeoutError:
                        break
                
                await self.process_batch(batch)
                
                # Mark all as done
                for _ in range(len(batch)):
                    self.queue.task_done()
                    
            except Exception as e:
                logger.error(f"❌ Error in consumption loop: {e}")
                await asyncio.sleep(1)

    async def process_batch(self, batch: list):
        """Processes a batch of metric events."""
        logger.info(f"📥 Processing batch of {len(batch)} events...")
        
        from backend.app.models.kpi_orm import KPIMetricORM
        import uuid
        
        async with get_db_context() as session:
            # 1. Bulk Insert Metrics
            metrics_data = []
            for event in batch:
                ts_str = event.get("timestamp")
                if isinstance(ts_str, str):
                    ts = datetime.fromisoformat(ts_str)
                else:
                    ts = datetime.utcnow()
                    
                metrics_data.append({
                    "id": uuid.uuid4(),
                    "tenant_id": event.get("tenant_id", "global-demo"),
                    "entity_id": event.get("entity_id"),
                    "metric_name": event.get("metric_name"),
                    "value": event.get("value"),
                    "timestamp": ts,
                    "tags": event.get("tags", {})
                })
            
            await KPIMetricORM.bulk_insert(session, metrics_data)
            
            # 2. Sequential Analysis (Anomaly Detection)
            detector = AnomalyDetector(session)
            for event in batch:
                res = await detector.process_metric(
                    event.get("tenant_id", "global-demo"), 
                    event.get("entity_id"), 
                    event.get("metric_name"), 
                    event.get("value")
                )
                
                if res.get("is_anomaly"):
                    await self.trigger_decision_intelligence(session, event, res)
            
            await session.commit()

    async def trigger_decision_intelligence(self, session, event, anomaly_res):
        """Mocked Decision Intelligence trigger when anomaly is found."""
        logger.warning(f"🚨 ANOMALY detected for {event['entity_id']}. Triggering intelligence...")
        
        # In a real system, this would call an RCA engine or LLM
        # For now, we seed a DecisionTrace as "Observation"
        
        embedding_service = get_embedding_service()
        trigger_desc = f"Anomaly detected on {event['entity_id']} for metric {event['metric_name']}. Value: {event['value']}, Baseline Mean: {anomaly_res['mean']}"
        
        trace = DecisionTraceORM(
            tenant_id=event.get("tenant_id", "global-demo"),
            trigger_type="anomaly_event",
            trigger_description=trigger_desc,
            decision_summary=f"Automated monitoring observation for performance deviation on {event['entity_id']}",
            tradeoff_rationale="Asynchronous detection triggered. Awaiting further correlation or human confirmation.",
            action_taken="observation_logged",
            decision_maker="system:detector-service-v1",
            confidence_score=anomaly_res.get("score", 0.0) / 10.0, # Normalizing z-score
            domain="anops",
            context={"anomaly_details": anomaly_res, "metric_event": event}
        )
        
        # Generate embedding for future recall
        text = embedding_service.create_decision_text(
            trigger_description=trigger_desc,
            decision_summary=trace.decision_summary,
            tradeoff_rationale=trace.tradeoff_rationale,
            action_taken=trace.action_taken
        )
        embedding = await embedding_service.generate_embedding(text)
        if embedding:
            trace.embedding = embedding

        session.add(trace)
        logger.info(f"📝 Logged Observation/DecisionTrace for {event['entity_id']}")

    def submit_event(self, event: Dict[str, Any]):
        """Helper for producers to push data to this service."""
        self.queue.put_nowait(event)

# Singleton instance for simple local use cases
service_instance = DetectorService()

if __name__ == "__main__":
    asyncio.run(service_instance.start())
