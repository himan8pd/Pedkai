import pytest
import uuid
from httpx import AsyncClient
from backend.app.core.security import create_access_token, Role

@pytest.mark.asyncio
async def test_create_alarm(client: AsyncClient):
    """Test creating a new alarm via POST /alarm (Ingress)."""
    token = create_access_token({"sub": "admin", "role": Role.ADMIN, "tenant_id": "default"})
    headers = {"Authorization": f"Bearer {token}"}
    
    alarm_id = str(uuid.uuid4())
    payload = {
        "id": alarm_id,
        "alarmType": "communicationsAlarm",
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
    
    response = await client.post("/tmf-api/alarmManagement/v4/alarm", json=payload, headers=headers)
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "persisted"
    assert data["id"] == alarm_id


@pytest.mark.asyncio
async def test_get_alarm_by_id(client: AsyncClient, db_session):
    """Test retrieving an alarm by ID."""
    from backend.app.models.decision_trace_orm import DecisionTraceORM
    from datetime import datetime, timezone
    
    token = create_access_token({"sub": "admin", "role": Role.ADMIN, "tenant_id": "default"})
    headers = {"Authorization": f"Bearer {token}"}
    
    alarm_id = uuid.uuid4()
    trace = DecisionTraceORM(
        id=alarm_id,
        tenant_id="default",
        trigger_type="alarm",
        trigger_description="Test Power Failure",
        decision_summary="Power Failure Detected",
        tradeoff_rationale="N/A",
        action_taken="None",
        decision_maker="System",
        created_at=datetime.now(timezone.utc),
        decision_made_at=datetime.now(timezone.utc),
        ack_state="unacknowledged",
        confidence_score=0.9
    )
    db_session.add(trace)
    await db_session.commit()
    
    get_res = await client.get(f"/tmf-api/alarmManagement/v4/alarm/{alarm_id}", headers=headers)
    assert get_res.status_code == 200
    data = get_res.json()
    assert data["id"] == str(alarm_id)
    assert data["specificProblem"] == "Power Failure Detected"


@pytest.mark.asyncio
async def test_patch_alarm(client: AsyncClient, db_session):
    """Test patching an alarm (acknowledge)."""
    from backend.app.models.decision_trace_orm import DecisionTraceORM
    from datetime import datetime, timezone
    
    token = create_access_token({"sub": "admin", "role": Role.ADMIN, "tenant_id": "default"})
    headers = {"Authorization": f"Bearer {token}"}
    
    alarm_id = uuid.uuid4()
    trace = DecisionTraceORM(
        id=alarm_id,
        tenant_id="default",
        trigger_type="alarm",
        trigger_description="Test Patch",
        decision_summary="Test Patch",
        tradeoff_rationale="N/A",
        action_taken="None",
        decision_maker="System",
        created_at=datetime.now(timezone.utc),
        decision_made_at=datetime.now(timezone.utc),
        ack_state="unacknowledged"
    )
    db_session.add(trace)
    await db_session.commit()
    
    patch_payload = {"ackState": "acknowledged"}
    patch_res = await client.patch(f"/tmf-api/alarmManagement/v4/alarm/{alarm_id}", json=patch_payload, headers=headers)
    assert patch_res.status_code == 200
    assert patch_res.json()["ackState"] == "acknowledged"
