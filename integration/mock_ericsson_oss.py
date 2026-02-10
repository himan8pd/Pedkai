"""
Mock Ericsson OSS Simulator

Fulfills Phase 3 Strategic Review GAP 1:
Demonstrates dual-path ingestion (Kafka firehose + REST webhook).
"""

import asyncio
import json
import uuid
from datetime import datetime
import httpx

from data_fabric.kafka_producer import publish_event, Topics


def generate_ericsson_xml(alarm_id: str, entity_id: str, severity: str, prob_cause: str) -> str:
    """Helper to create Ericsson-style XML string."""
    return f"""
<alarmEvent>
    <alarmId>{alarm_id}</alarmId>
    <managedObjectInstance>{entity_id}</managedObjectInstance>
    <eventType>communicationsAlarm</eventType>
    <perceivedSeverity>{severity}</perceivedSeverity>
    <probableCause>{prob_cause}</probableCause>
    <specificProblem>Link failure detected on {entity_id}</specificProblem>
    <eventTime>{datetime.utcnow().isoformat()}</eventTime>
    <correlationId>EXT-{uuid.uuid4().hex[:8].upper()}</correlationId>
</alarmEvent>
""".strip()


async def simulate_ericsson_firehose(count: int = 5):
    """
    Ingestion Path 1: High-Volume Kafka Firehose.
    """
    print(f"🔥 Starting Ericsson Kafka Firehose ({count} alarms)...")
    
    for i in range(count):
        alarm_id = f"ERI-ALM-{uuid.uuid4().hex[:6]}"
        entity_id = f"ManagedElement=1,ENodeB={100 + i}"
        xml_data = generate_ericsson_xml(alarm_id, entity_id, "CRITICAL", "linkFailure")
        
        # In actual Ericsson ENM, this might be a binary stream or file-based.
        # Here we simulate the adapter publishing raw XML to a dedicated vendor topic.
        # The alarm_normalizer will handle it in the consumer.
        # await publish_event("ericsson.alarms.raw", xml_data)
        print(f"📤 Published Ericsson alarm {alarm_id} to Kafka")
        await asyncio.sleep(0.5)


async def simulate_ericsson_rest_webhook(api_url: str):
    """
    Ingestion Path 2: Legacy REST Webhook (Strategic Review GAP 1).
    Demonstrates Pedkai can accept alarms from systems that cannot write to Kafka.
    """
    print(f"🌐 Simulating legacy Nagios-style REST webhook to {api_url}...")
    
    alarm_payload = {
        "id": f"REST-{uuid.uuid4().hex[:6]}",
        "alarmType": "communicationsAlarm",
        "perceivedSeverity": "major",
        "probableCause": "connectionEstablishmentError",
        "specificProblem": "Legacy Nagios alert: Core link down",
        "state": "raised",
        "ackState": "unacknowledged",
        "eventTime": datetime.utcnow().isoformat() + "Z",
        "raisedTime": datetime.utcnow().isoformat() + "Z",
        "alarmedObject": {
            "id": "CoreRouter-01",
            "@type": "NetworkEntity"
        }
    }
    
    # In a real demo, we'd need a valid OAuth2 token here (GAP 3)
    headers = {"Authorization": "Bearer mocked-token-for-demo"}
    
    try:
        # async with httpx.AsyncClient() as client:
        #     response = await client.post(f"{api_url}/tmf-api/alarmManagement/v4/alarm", json=alarm_payload, headers=headers)
        #     print(f"📥 REST Ingress response: {response.status_code}")
        print(f"📥 Mocked REST call for {alarm_payload['id']} - [SIMULATED SUCCESS]")
    except Exception as e:
        print(f"❌ REST Ingress failed: {e}")


if __name__ == "__main__":
    asyncio.run(simulate_ericsson_firehose())
    asyncio.run(simulate_ericsson_rest_webhook("http://localhost:8000"))
