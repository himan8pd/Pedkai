import pytest
import uuid
from httpx import AsyncClient
from backend.app.models.incident_orm import IncidentORM
from backend.app.models.topology_models import EntityRelationshipORM
from backend.app.core.security import create_access_token

@pytest.mark.asyncio
async def test_multi_tenant_isolation(client: AsyncClient, db_session):
    """Verify Finding 4: Tenants cannot see each other's data."""
    t1_token = create_access_token({"sub": "t1-user", "role": "admin", "tenant_id": "t1"})
    t2_token = create_access_token({"sub": "t2-user", "role": "admin", "tenant_id": "t2"})
    
    # Create data for t1
    resp = await client.post(
        "/api/v1/incidents/", 
        json={"tenant_id": "t1", "title": "T1", "severity": "major"},
        headers={"Authorization": f"Bearer {t1_token}"}
    )
    assert resp.status_code == 201
    
    # Query via t2 token — should see 0 incidents
    resp = await client.get(
        "/api/v1/incidents/",
        headers={"Authorization": f"Bearer {t2_token}"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 0

@pytest.mark.asyncio
async def test_multi_tenant_isolation_topology(client: AsyncClient, db_session):
    """Verify Finding 10: Multi-tenant filtering at DB level."""
    t1_token = create_access_token({"sub": "admin", "role": "admin", "tenant_id": "t1"})
    t2_token = create_access_token({"sub": "admin", "role": "admin", "tenant_id": "t2"})
    
    # Insert for t1
    rel1 = EntityRelationshipORM(id=uuid.uuid4(), from_entity_id="A", from_entity_type="NODE", to_entity_id="B", to_entity_type="NODE", relationship_type="C", tenant_id="t1")
    db_session.add(rel1)
    await db_session.commit()
    
    # t1 should see it
    resp = await client.get("/api/v1/topology/t1/health", headers={"Authorization": f"Bearer {t1_token}"})
    assert resp.json()["total_entities"] >= 2
    
    # t2 should NOT see it
    resp = await client.get("/api/v1/topology/t2/health", headers={"Authorization": f"Bearer {t2_token}"})
    assert resp.json()["total_entities"] == 0
