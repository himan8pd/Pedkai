import pytest
import uuid
from httpx import AsyncClient
from backend.app.models.incident_orm import IncidentORM
from backend.app.models.topology_models import EntityRelationshipORM
from backend.app.models.customer_orm import CustomerORM
from backend.app.core.security import create_access_token

@pytest.mark.asyncio
async def test_ruthless_topology_isolation(client: AsyncClient, db_session):
    """Verify Finding S-1: Main topology graph and entity queries are isolated."""
    t1_token = create_access_token({"sub": "t1", "role": "admin", "tenant_id": "tenant1"})
    t2_token = create_access_token({"sub": "t2", "role": "admin", "tenant_id": "tenant2"})
    
    # 1. Setup data for Tenant 1
    rel1 = EntityRelationshipORM(
        id=uuid.uuid4(), from_entity_id="MASTER-A", from_entity_type="Router",
        to_entity_id="SLAVE-B", to_entity_type="Interface",
        relationship_type="CONTAINS", tenant_id="tenant1"
    )
    db_session.add(rel1)
    await db_session.commit()
    
    # 2. Tenant 2 should NOT see Tenant 1's graph
    resp = await client.get("/api/v1/topology/tenant2", headers={"Authorization": f"Bearer {t2_token}"})
    assert resp.status_code == 200
    assert len(resp.json()["entities"]) == 0
    
    # 3. Tenant 2 should NOT see Tenant 1's specific entity
    resp = await client.get("/api/v1/topology/tenant2/entity/MASTER-A", headers={"Authorization": f"Bearer {t2_token}"})
    assert resp.status_code == 200
    assert resp.json()["neighbour_count"] == 0

@pytest.mark.asyncio
async def test_ruthless_incident_isolation(client: AsyncClient, db_session):
    """Verify S-1 Fix: Individual incident detail is isolated by tenant."""
    t1_token = create_access_token({"sub": "t1", "role": "operator", "tenant_id": "tenant1"})
    t2_token = create_access_token({"sub": "t2", "role": "operator", "tenant_id": "tenant2"})
    
    # 1. Create incident for t1
    new_inc = IncidentORM(
        id=str(uuid.uuid4()), title="Secret T1 Incident", severity="critical",
        status="detected", tenant_id="tenant1"
    )
    db_session.add(new_inc)
    await db_session.commit()
    
    # 2. t2 attempts to access t1's incident ID
    resp = await client.get(f"/api/v1/incidents/{new_inc.id}", headers={"Authorization": f"Bearer {t2_token}"})
    # Previously this would return 200. Now it must return 404 (Access Denied).
    assert resp.status_code == 404
    assert "access denied" in resp.json()["detail"].lower()

@pytest.mark.asyncio
async def test_ruthless_customer_impact_isolation(client: AsyncClient, db_session):
    """Verify S-1 Fix: Service impact customers are isolated by tenant."""
    t1_token = create_access_token({"sub": "t1", "role": "admin", "tenant_id": "tenant1"})
    t2_token = create_access_token({"sub": "t2", "role": "admin", "tenant_id": "tenant2"})
    
    # 1. Create customer for t1
    cust1 = CustomerORM(
        id=uuid.uuid4(), name="VIP T1", external_id="T1-100", 
        associated_site_id="SITE-X", tenant_id="tenant1"
    )
    db_session.add(cust1)
    await db_session.commit()
    
    # 2. t2 asks for impacted customers (Site-X is in T1, so T2 should find nothing)
    resp = await client.get("/api/v1/service-impact/customers", headers={"Authorization": f"Bearer {t1_token}"})
    assert resp.json()["total_customers_impacted"] == 1
    
    resp = await client.get("/api/v1/service-impact/customers", headers={"Authorization": f"Bearer {t2_token}"})
    assert resp.json()["total_customers_impacted"] == 0
