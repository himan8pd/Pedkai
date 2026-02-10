"""
Integration tests for TMF642 Alarm Management API.
"""
import pytest
from httpx import AsyncClient
from uuid import uuid4

@pytest.mark.asyncio
async def test_create_alarm(client: AsyncClient):
    """Test creating a new alarm via POST /alarm (Ingress)."""
    # Needs full TMF642Alarm payload as per implementation
    alarm_id = str(uuid4())
    payload = {
        "id": alarm_id,
        "alarmType": "communicationsAlarm", # CamelCase enum
        "perceivedSeverity": "critical",
        "probableCause": "cableCut",
        "specificProblem": "Test Link Failure",
        "state": "raised",
        "ackState": "unacknowledged",
        "eventTime": "2023-10-27T10:00:00Z",
        "raisedTime": "2023-10-27T10:00:00Z",
        "alarmedObject": {
            "id": "Region-A-Router-X",
            "name": "Router X"
        },
        "onap_type": "Alarm",
        "onap_base_type": "Entity",
        "onap_schema_location": "http://schema"
    }
    
    response = await client.post("/tmf-api/alarmManagement/v4/alarm", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "accepted"
    assert data["id"] == alarm_id


@pytest.mark.asyncio
async def test_get_alarm_by_id(client: AsyncClient, db_session):
    """Test retrieving an alarm by ID (after manual DB seeding)."""
    # 1. Seed DB
    from backend.app.models.decision_trace_orm import DecisionTraceORM
    from datetime import datetime
    
    alarm_id = uuid4()
    trace = DecisionTraceORM(
        id=alarm_id,
        tenant_id="default",
        trigger_type="alarm",
        trigger_description="Test Power Failure",
        decision_summary="Power Failure Detected",
        tradeoff_rationale="N/A",
        action_taken="None",
        decision_maker="System",
        created_at=datetime.utcnow(),
        decision_made_at=datetime.utcnow(),
        ack_state="unacknowledged",
        confidence_score=0.9 # CRITICAL
    )
    db_session.add(trace)
    await db_session.commit()
    
    # 2. Get
    get_res = await client.get(f"/tmf-api/alarmManagement/v4/alarm/{alarm_id}")
    assert get_res.status_code == 200
    data = get_res.json()
    assert data["id"] == str(alarm_id)
    assert data["specificProblem"] == "Power Failure Detected"
    assert data["perceivedSeverity"] == "critical" # Mapped from 0.9 validation


@pytest.mark.asyncio
async def test_patch_alarm(client: AsyncClient, db_session):
    """Test patching an alarm (acknowledge)."""
    # 1. Seed DB
    from backend.app.models.decision_trace_orm import DecisionTraceORM
    from datetime import datetime
    
    alarm_id = uuid4()
    trace = DecisionTraceORM(
        id=alarm_id,
        tenant_id="default",
        trigger_type="alarm",
        trigger_description="Test Patch",
        decision_summary="Test Patch",
        tradeoff_rationale="N/A",
        action_taken="None",
        decision_maker="System",
        created_at=datetime.utcnow(),
        decision_made_at=datetime.utcnow(),
        ack_state="unacknowledged"
    )
    db_session.add(trace)
    await db_session.commit()
    
    # 2. Patch
    patch_payload = {"ackState": "acknowledged"}
    patch_res = await client.patch(f"/tmf-api/alarmManagement/v4/alarm/{alarm_id}", json=patch_payload)
    assert patch_res.status_code == 200
    assert patch_res.json()["ackState"] == "acknowledged"
