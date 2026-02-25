import pytest
import uuid
from httpx import AsyncClient
from backend.app.models.topology_models import EntityRelationshipORM
from backend.app.core.security import create_access_token, Role

@pytest.mark.asyncio
async def test_topology_impact_recursive(client: AsyncClient, db_session):
    """Verify Finding 9: Recursive impact tree traversal."""
    token = create_access_token({"sub": "admin", "role": Role.ADMIN})
    headers = {"Authorization": f"Bearer {token}"}
    
    # Insert data...
    rel1 = EntityRelationshipORM(id=uuid.uuid4(), from_entity_id="A", from_entity_type="NODE", to_entity_id="B", to_entity_type="NODE", relationship_type="CONNECTED", tenant_id="t1")
    rel2 = EntityRelationshipORM(id=uuid.uuid4(), from_entity_id="B", from_entity_type="NODE", to_entity_id="C", to_entity_type="NODE", relationship_type="CONNECTED", tenant_id="t1")
    db_session.add(rel1)
    db_session.add(rel2)
    await db_session.commit()

    # Get impact for A
    resp = await client.get("/api/v1/topology/t1/impact/A?max_hops=2", headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data["downstream"]) == 2
    assert "B" in [n["entity_id"] for n in data["downstream"]]
    assert "C" in [n["entity_id"] for n in data["downstream"]]

@pytest.mark.asyncio
async def test_topology_health_staleness(client: AsyncClient, db_session):
    """Verify Finding 3: Health staleness check logic."""
    from datetime import datetime, timedelta, timezone
    from backend.app.models.topology_models import EntityRelationshipORM
    
    token = create_access_token({"sub": "admin", "role": Role.ADMIN})
    headers = {"Authorization": f"Bearer {token}"}
    
    now = datetime.now(timezone.utc)
    # Old rel
    rel_old = EntityRelationshipORM(id=uuid.uuid4(), from_entity_id="X", from_entity_type="N", to_entity_id="Y", to_entity_type="N", relationship_type="C", tenant_id="t1", created_at=now - timedelta(days=8))
    # New rel
    rel_new = EntityRelationshipORM(id=uuid.uuid4(), from_entity_id="Y", from_entity_type="N", to_entity_id="Z", to_entity_type="N", relationship_type="C", tenant_id="t1", created_at=now)
    
    db_session.add(rel_old)
    db_session.add(rel_new)
    await db_session.commit()
    
    resp = await client.get("/api/v1/topology/t1/health", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_entities"] >= 2
    assert data["stale_entities"] == 1
    assert data["status"] == "degraded"
