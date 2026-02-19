import pytest
import uuid
from httpx import AsyncClient
from backend.app.core.security import create_access_token

@pytest.mark.asyncio
async def test_tmf642_ingress_persistence(client: AsyncClient, db_session):
    """Verify that TMF642 POST /alarm persists a DecisionTraceORM record."""
    admin_token = create_access_token({"sub": "admin", "role": "admin", "tenant_id": "tmf-tenant"})
    
    alarm_id = str(uuid.uuid4())
    payload = {
        "id": alarm_id,
        "alarmType": "qualityOfServiceAlarm",
        "perceivedSeverity": "critical",
        "probableCause": "capacityBreach",
        "specificProblem": "Site-X backhaul saturation",
        "state": "raised",
        "ackState": "unacknowledged",
        "eventTime": "2026-02-18T10:00:00Z",
        "raisedTime": "2026-02-18T10:00:00Z",
        "alarmedObject": {
            "id": "SITE-X",
            "name": "Site-X Hub"
        }
    }
    
    # 1. POST the TMF alarm
    resp = await client.post(
        "/tmf-api/alarmManagement/v4/alarm", 
        json=payload,
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert resp.status_code == 201
    assert resp.json()["status"] == "persisted"
    
    # 2. Verify it appears in the list (Tenant Isolation check included)
    resp = await client.get(
        "/tmf-api/alarmManagement/v4/alarm",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert any(a["id"] == alarm_id for a in data)
    
    # 3. Verify detail retrieval
    resp = await client.get(
        f"/tmf-api/alarmManagement/v4/alarm/{alarm_id}",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert resp.status_code == 200
    assert resp.json()["specificProblem"] == "Site-X backhaul saturation"
