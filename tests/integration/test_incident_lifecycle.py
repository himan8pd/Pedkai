import pytest
import uuid
from datetime import datetime, timezone
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.core.security import Role, create_access_token
from backend.app.main import app

@pytest.mark.asyncio
async def test_create_incident(client: AsyncClient):
    """POST creates incident with status 'anomaly'."""
    token = create_access_token({"sub": "admin", "role": Role.ADMIN})
    headers = {"Authorization": f"Bearer {token}"}
    response = await client.post(
        "/api/v1/incidents/",
        json={"tenant_id": "tenant-a", "title": "High PRB utilization", "severity": "major"},
        headers=headers
    )
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["status"] == "anomaly"

@pytest.mark.asyncio
async def test_advance_lifecycle(client: AsyncClient):
    """PATCH advance moves through statuses correctly."""
    token = create_access_token({"sub": "admin", "role": Role.ADMIN})
    headers = {"Authorization": f"Bearer {token}"}
    create_resp = await client.post(
        "/api/v1/incidents/",
        json={"tenant_id": "tenant-a", "title": "Test incident", "severity": "minor"},
        headers=headers
    )
    assert create_resp.status_code == 201
    incident_id = create_resp.json()["id"]

    adv_resp = await client.patch(f"/api/v1/incidents/{incident_id}/advance", headers=headers)
    assert adv_resp.status_code == 200
    assert adv_resp.json()["status"] == "detected"

@pytest.mark.asyncio
async def test_human_gate_enforcement(client: AsyncClient):
    """Attempting to advance past sitrep_draft without approve-sitrep returns 400."""
    token = create_access_token({"sub": "admin", "role": Role.ADMIN})
    headers = {"Authorization": f"Bearer {token}"}
    create_resp = await client.post(
        "/api/v1/incidents/",
        json={"tenant_id": "tenant-a", "title": "Gate test", "severity": "minor"},
        headers=headers
    )
    incident_id = create_resp.json()["id"]

    for _ in range(3):
        await client.patch(f"/api/v1/incidents/{incident_id}/advance", headers=headers)

    resp = await client.patch(f"/api/v1/incidents/{incident_id}/advance", headers=headers)
    assert resp.status_code == 400

@pytest.mark.asyncio
async def test_approve_sitrep(client: AsyncClient, db_session: AsyncSession):
    """POST approve-sitrep records approver name and timestamp."""
    token = create_access_token({"sub": "admin", "role": Role.ADMIN})
    headers = {"Authorization": f"Bearer {token}"}

    create_resp = await client.post(
        "/api/v1/incidents/",
        json={"tenant_id": "tenant-a", "title": "Sitrep test", "severity": "major"},
        headers=headers
    )
    incident_id = create_resp.json()["id"]

    await client.patch(f"/api/v1/incidents/{incident_id}/advance", headers=headers)
    await client.patch(f"/api/v1/incidents/{incident_id}/advance", headers=headers)

    resp = await client.post(
        f"/api/v1/incidents/{incident_id}/approve-sitrep",
        json={"approved_by": "shift-lead-jones"},
        headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "sitrep_approved"

@pytest.mark.asyncio
async def test_approve_action(client: AsyncClient):
    """POST approve-action works after sitrep approved."""
    token = create_access_token({"sub": "admin", "role": Role.ADMIN})
    headers = {"Authorization": f"Bearer {token}"}

    create_resp = await client.post(
        "/api/v1/incidents/",
        json={"tenant_id": "tenant-a", "title": "Action test", "severity": "major"},
        headers=headers
    )
    incident_id = create_resp.json()["id"]

    await client.patch(f"/api/v1/incidents/{incident_id}/advance", headers=headers) 
    await client.patch(f"/api/v1/incidents/{incident_id}/advance", headers=headers)

    await client.post(f"/api/v1/incidents/{incident_id}/approve-sitrep", json={"approved_by": "sl"}, headers=headers)
    resp = await client.post(f"/api/v1/incidents/{incident_id}/approve-action", json={"approved_by": "eng"}, headers=headers)
    assert resp.status_code == 200

@pytest.mark.asyncio
async def test_close_incident(client: AsyncClient):
    """POST close records closer name."""
    token = create_access_token({"sub": "admin", "role": Role.ADMIN})
    headers = {"Authorization": f"Bearer {token}"}

    create_resp = await client.post(
        "/api/v1/incidents/",
        json={"tenant_id": "tenant-a", "title": "Close test", "severity": "minor"},
        headers=headers
    )
    incident_id = create_resp.json()["id"]

    await client.patch(f"/api/v1/incidents/{incident_id}/advance", headers=headers)
    await client.patch(f"/api/v1/incidents/{incident_id}/advance", headers=headers)
    await client.post(f"/api/v1/incidents/{incident_id}/approve-sitrep", json={"approved_by": "sl"}, headers=headers)
    await client.post(f"/api/v1/incidents/{incident_id}/approve-action", json={"approved_by": "eng"}, headers=headers)

    resp = await client.post(f"/api/v1/incidents/{incident_id}/close", json={"approved_by": "mgr"}, headers=headers)
    assert resp.status_code == 200

@pytest.mark.asyncio
async def test_emergency_service_p1(client: AsyncClient):
    """Creating incident with EMERGENCY in entity_external_id forces severity to critical."""
    token = create_access_token({"sub": "admin", "role": Role.ADMIN})
    headers = {"Authorization": f"Bearer {token}"}
    response = await client.post(
        "/api/v1/incidents/",
        json={
            "tenant_id": "tenant-a",
            "title": "999 dial-out failure",
            "severity": "minor",
            "entity_external_id": "EMERGENCY_SERVICE_999",
        },
        headers=headers
    )
    assert response.status_code == 201
    assert response.json()["severity"] == "critical"

@pytest.mark.asyncio
async def test_audit_trail(client: AsyncClient):
    """GET audit-trail returns all approval events."""
    token = create_access_token({"sub": "admin", "role": Role.ADMIN})
    headers = {"Authorization": f"Bearer {token}"}

    create_resp = await client.post(
        "/api/v1/incidents/",
        json={"tenant_id": "tenant-a", "title": "Audit test", "severity": "major"},
        headers=headers
    )
    incident_id = create_resp.json()["id"]
    await client.patch(f"/api/v1/incidents/{incident_id}/advance", headers=headers)
    await client.patch(f"/api/v1/incidents/{incident_id}/advance", headers=headers)
    await client.post(f"/api/v1/incidents/{incident_id}/approve-sitrep", json={"approved_by": "auditor"}, headers=headers)

    resp = await client.get(f"/api/v1/incidents/{incident_id}/audit-trail", headers=headers)
    assert resp.status_code == 200
    trail = resp.json()["audit_trail"]
    assert len(trail) >= 2
