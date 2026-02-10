"""
Mock Nokia NetAct Simulator

Generates Nokia-style JSON alarms.
"""

import asyncio
import json
import uuid
from datetime import datetime

from data_fabric.kafka_producer import publish_event, Topics


async def simulate_nokia_firehose(count: int = 5):
    """
    Ingestion Path 1: High-Volume Kafka Firehose.
    """
    print(f"📡 Starting Nokia Kafka Firehose ({count} alarms)...")
    
    for i in range(count):
        alarm_id = f"NOK-ALM-{uuid.uuid4().hex[:6]}"
        notification_type = "processingErrorAlarm"
        
        alarm_payload = {
            "alarmId": alarm_id,
            "sourceIndicator": f"ManagedElement=1,BTS=2000,Cell={i}",
            "notificationType": notification_type,
            "severity": "MAJOR",
            "probableCause": "thresholdCrossed",
            "alarmText": f"High memory utilization on Cell {i}",
            "eventTime": datetime.utcnow().isoformat(),
            "correlationId": f"NOK-CORR-{uuid.uuid4().hex[:4].upper()}"
        }
        
        # Publish JSON to Kafka
        # await publish_event(Topics.ALARMS, alarm_payload)
        print(f"📤 Published Nokia alarm {alarm_id} to Kafka")
        await asyncio.sleep(0.7)


if __name__ == "__main__":
    asyncio.run(simulate_nokia_firehose())
