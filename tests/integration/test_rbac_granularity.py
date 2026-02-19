import pytest
from httpx import AsyncClient
from backend.app.core.security import Role, create_access_token
from backend.app.main import app

@pytest.mark.asyncio
async def test_operator_cannot_approve_sitrep(client: AsyncClient):
    """Verify that a standard operator NO LONGER has approval scopes (Finding 2)."""
    # Create real token for OPERATOR
    token = create_access_token({"sub": "op-user", "role": Role.OPERATOR})
    headers = {"Authorization": f"Bearer {token}"}
    
    # Create incident
    resp = await client.post("/api/v1/incidents/", json={"tenant_id": "t1", "title": "T", "severity": "major"}, headers=headers)
    assert resp.status_code == 201
    iid = resp.json()["id"]
    
    # Advance to rca
    await client.patch(f"/api/v1/incidents/{iid}/advance", headers=headers)
    await client.patch(f"/api/v1/incidents/{iid}/advance", headers=headers)

    # Attempt approval — should return 403 Forbidden
    resp = await client.post(f"/api/v1/incidents/{iid}/approve-sitrep", json={"approved_by": "op"}, headers=headers)
    assert resp.status_code == 403
    assert "not enough permissions" in resp.json()["detail"].lower()

@pytest.mark.asyncio
async def test_shift_lead_can_approve_sitrep(client: AsyncClient):
    """Verify that SHIFT_LEAD can still approve (RBAC correctness)."""
    # Create real token for SHIFT_LEAD
    token = create_access_token({"sub": "sl-user", "role": Role.SHIFT_LEAD})
    headers = {"Authorization": f"Bearer {token}"}
    
    # Create incident
    resp = await client.post("/api/v1/incidents/", json={"tenant_id": "t1", "title": "T", "severity": "major"}, headers=headers)
    assert resp.status_code == 201
    iid = resp.json()["id"]
    
    # Advance to rca
    await client.patch(f"/api/v1/incidents/{iid}/advance", headers=headers)
    await client.patch(f"/api/v1/incidents/{iid}/advance", headers=headers)

    # Attempt approval — should return 200 OK
    resp = await client.post(f"/api/v1/incidents/{iid}/approve-sitrep", json={"approved_by": "sl"}, headers=headers)
    assert resp.status_code == 200
