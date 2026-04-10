import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.skipif(True, reason="Reconciliation engine creates its own DB sessions requiring PostgreSQL")

# Use the test tenant from our fixtures
TENANT_ID = "pedkai_telco2_01"

@pytest.fixture
async def seeded_divergence_data(db_session: AsyncSession):
    """
    Seed a small amount of CMDB vs Ground Truth data to test the reconciliation engine.
    Also clears existing test data.
    """
    # 1. Clean up
    await db_session.execute(text("DELETE FROM reconciliation_results WHERE tenant_id = 'test_tenant'"))
    await db_session.execute(text("DELETE FROM reconciliation_runs WHERE tenant_id = 'test_tenant'"))
    
    # Create tables that lack ORM models
    await db_session.execute(text("""
        CREATE TABLE IF NOT EXISTS gt_network_entities (
            entity_id VARCHAR PRIMARY KEY,
            tenant_id VARCHAR NOT NULL,
            name VARCHAR,
            entity_type VARCHAR,
            external_id VARCHAR,
            domain VARCHAR,
            attributes JSON
        )
    """))
    await db_session.execute(text("""
        CREATE TABLE IF NOT EXISTS gt_entity_relationships (
            relationship_id VARCHAR PRIMARY KEY,
            tenant_id VARCHAR NOT NULL,
            from_entity_id VARCHAR NOT NULL,
            from_entity_type VARCHAR,
            to_entity_id VARCHAR NOT NULL,
            to_entity_type VARCHAR,
            relationship_type VARCHAR NOT NULL,
            domain VARCHAR
        )
    """))
    await db_session.execute(text("""
        CREATE TABLE IF NOT EXISTS divergence_manifest (
            divergence_id VARCHAR PRIMARY KEY,
            tenant_id VARCHAR NOT NULL,
            divergence_type VARCHAR NOT NULL,
            entity_or_relationship VARCHAR NOT NULL,
            target_id VARCHAR NOT NULL,
            target_type VARCHAR NOT NULL,
            domain VARCHAR,
            description TEXT,
            attribute_name VARCHAR,
            ground_truth_value VARCHAR,
            cmdb_declared_value VARCHAR,
            original_external_id VARCHAR,
            mutated_external_id VARCHAR,
            dataset_version VARCHAR,
            created_at TIMESTAMP
        )
    """))

    # Clean up entities/edges for 'test_tenant'
    tables = [
        "topology_relationships", "gt_entity_relationships",
        "network_entities", "gt_network_entities", "divergence_manifest"
    ]
    for t in tables:
        await db_session.execute(text(f"DELETE FROM {t} WHERE tenant_id = 'test_tenant'"))
        
    await db_session.commit()

    # 2. Add CMDB entities
    await db_session.execute(text("""
        INSERT INTO network_entities (id, tenant_id, name, entity_type, external_id, created_at, updated_at) VALUES
        ('11111111-1111-1111-1111-111111111111', 'test_tenant', 'Matching Node', 'router', 'ext-1', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
        ('22222222-2222-2222-2222-222222222222', 'test_tenant', 'Phantom Node', 'switch', 'ext-2', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
        ('33333333-3333-3333-3333-333333333333', 'test_tenant', 'Identity Changed Node', 'server', 'ext-old', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
        ('44444444-4444-4444-4444-444444444444', 'test_tenant', 'Attribute Changed Node', 'firewall', 'ext-4', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """))

    # 3. Add Ground Truth entities
    await db_session.execute(text("""
        INSERT INTO gt_network_entities (entity_id, tenant_id, name, entity_type, external_id, domain, attributes) VALUES
        ('11111111-1111-1111-1111-111111111111', 'test_tenant', 'Matching Node', 'router', 'ext-1', 'core', '{"status":"active"}'),
        ('33333333-3333-3333-3333-333333333333', 'test_tenant', 'Identity Changed Node', 'server', 'ext-new', 'core', '{"status":"active"}'),
        ('44444444-4444-4444-4444-444444444444', 'test_tenant', 'Attribute Changed Node', 'firewall', 'ext-4', 'core', '{"status":"down"}'),
        ('55555555-5555-5555-5555-555555555555', 'test_tenant', 'Dark Node', 'switch', 'ext-5', 'core', '{"status":"active"}')
    """))

    # 4. Add CMDB Edges
    await db_session.execute(text("""
        INSERT INTO topology_relationships (id, tenant_id, from_entity_id, from_entity_type, to_entity_id, to_entity_type, relationship_type, created_at) VALUES
        ('e1111111-1111-1111-1111-111111111111', 'test_tenant', '11111111-1111-1111-1111-111111111111', 'router', '44444444-4444-4444-4444-444444444444', 'firewall', 'connected_to', CURRENT_TIMESTAMP),
        ('e2222222-2222-2222-2222-222222222222', 'test_tenant', '11111111-1111-1111-1111-111111111111', 'router', '22222222-2222-2222-2222-222222222222', 'switch', 'connected_to', CURRENT_TIMESTAMP)
    """))

    # 5. Add Ground Truth Edges
    await db_session.execute(text("""
        INSERT INTO gt_entity_relationships (relationship_id, tenant_id, from_entity_id, from_entity_type, to_entity_id, to_entity_type, relationship_type, domain) VALUES
        ('e1111111-1111-1111-1111-111111111111', 'test_tenant', '11111111-1111-1111-1111-111111111111', 'router', '44444444-4444-4444-4444-444444444444', 'firewall', 'connected_to', 'core'),
        ('e3333333-3333-3333-3333-333333333333', 'test_tenant', '11111111-1111-1111-1111-111111111111', 'router', '55555555-5555-5555-5555-555555555555', 'switch', 'connected_to', 'core')
    """))

    # 6. Add some seeded manifest labels for scoring
    await db_session.execute(text("""
        INSERT INTO divergence_manifest (divergence_id, tenant_id, divergence_type, entity_or_relationship, target_id, target_type) VALUES
        ('d1', 'test_tenant', 'dark_node', 'entity', '55555555-5555-5555-5555-555555555555', 'switch'),
        ('d2', 'test_tenant', 'phantom_node', 'entity', '22222222-2222-2222-2222-222222222222', 'switch')
    """))

    await db_session.commit()
    return "test_tenant"

@pytest.mark.asyncio
async def test_reconciliation_run(client: AsyncClient, seeded_divergence_data: str):
    """Test POST /divergence/run executes algorithm successfully."""
    tenant_id = seeded_divergence_data
    
    response = await client.post(
        "/api/v1/reports/divergence/run",
        json={"tenant_id": tenant_id}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "complete"
    assert "run_id" in data
    
    # Verify the stats it gathered
    divs = data["divergences"]
    cmdb = data["cmdb_stats"]
    gt = data["ground_truth_stats"]

    assert cmdb["entity_count"] == 4
    assert gt["entity_count"] == 4
    assert cmdb["edge_count"] == 2
    assert gt["edge_count"] == 2
    
    assert divs["phantom_nodes"] == 1
    assert divs["dark_nodes"] == 1
    assert divs["identity_mutations"] == 1
    assert divs["phantom_edges"] == 1
    assert divs["dark_edges"] == 1
    assert divs["total"] >= 5 # plus dark_attribute handled minimally

@pytest.mark.asyncio
async def test_scoring_endpoint(client: AsyncClient, seeded_divergence_data: str):
    """Test GET /divergence/score calculates F1 against the manifest."""
    tenant_id = seeded_divergence_data
    
    # Must run reconciliation first
    await client.post("/api/v1/reports/divergence/run", json={"tenant_id": tenant_id})
    
    response = await client.get(
        f"/api/v1/reports/divergence/score/{tenant_id}"
    )
    assert response.status_code == 200
    data = response.json()
    
    assert data["tenant_id"] == tenant_id
    overall = data["overall"]
    assert overall["manifest_count"] == 2
    
    # Both manifest labels should have been found (1 phantom node, 1 dark node)
    assert overall["detected_in_manifest"] == 2
    assert overall["recall"] == 1.0 # Found 2/2 from manifest
    
    types = {t["type"]: t for t in data["by_type"]}
    assert types["dark_node"]["recall"] == 1.0 # 1/1
    assert types["phantom_node"]["recall"] == 1.0 # 1/1

@pytest.mark.asyncio
async def test_topology_search(client: AsyncClient, seeded_divergence_data: str):
    """Test GET /topology/{tenant}/search finds entities for seeding."""
    tenant_id = seeded_divergence_data
    
    response = await client.get(
        f"/api/v1/topology/{tenant_id}/search?q=Phantom"
    )
    assert response.status_code == 200
    data = response.json()
    
    assert len(data["results"]) == 1
    assert data["results"][0]["name"] == "Phantom Node"
    assert data["results"][0]["id"] == "22222222-2222-2222-2222-222222222222"

@pytest.mark.asyncio
async def test_topology_neighborhood(client: AsyncClient, seeded_divergence_data: str):
    """Test GET /topology/{tenant}/neighborhood/{id} retrieves the subgraph."""
    tenant_id = seeded_divergence_data
    seed_id = "11111111-1111-1111-1111-111111111111" # Matching Node
    
    response = await client.get(
        f"/api/v1/topology/{tenant_id}/neighborhood/{seed_id}?hops=1"
    )
    assert response.status_code == 200
    data = response.json()
    
    # Node 1 is connected to Node 2 and Node 4 in CMDB
    assert data["nodes_returned"] == 3
    assert data["edges_returned"] == 2
    
    entity_ids = [e["id"] for e in data["entities"]]
    assert seed_id in entity_ids
    assert "22222222-2222-2222-2222-222222222222" in entity_ids
    assert "44444444-4444-4444-4444-444444444444" in entity_ids
