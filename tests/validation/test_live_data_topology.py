"""
Layer 2 Topology Validation (TC-010-019).
Verifies the Context Graph using real-world zone labels from LiveTestData.
"""

import pytest
from uuid import uuid4
from sqlalchemy import select
from decision_memory.graph_orm import NetworkEntityORM, EntityRelationshipORM
from decision_memory.graph_schema import EntityType, RelationshipType

async def seed_zone_topology_helper(db_session, tenant_id="topology-test", cell_count=2):
    """
    Helper to seed a topology based on Zone A.
    Site -> Zone A -> Cell_Live_1, ..., Cell_Live_N
    """
    # 1. Create Site
    site = NetworkEntityORM(
        tenant_id=tenant_id,
        entity_type=EntityType.SITE,
        name="London-Central-Site",
        external_id="SITE_LON_A",
        attributes={"importance": "high"}
    )
    db_session.add(site)
    await db_session.flush()
    
    # 2. Create Zone A (part of Site)
    zone_a = NetworkEntityORM(
        tenant_id=tenant_id,
        entity_type=EntityType.SERVICE, # Using service for zone/area
        name="Zone A",
        external_id="ZONE_A",
        attributes={"region": "South"}
    )
    db_session.add(zone_a)
    await db_session.flush()
    
    # Site hosts Zone A
    rel_site_zone = EntityRelationshipORM(
        tenant_id=tenant_id,
        source_entity_id=site.id,
        source_entity_type=EntityType.SITE,
        target_entity_id=zone_a.id,
        target_entity_type=EntityType.SERVICE,
        relationship_type=RelationshipType.HOSTS
    )
    db_session.add(rel_site_zone)
    
    # 3. Create N Cells in Zone A
    cells = []
    for i in range(1, cell_count + 1):
        cell_id = f"CELL_LIVE_{i}"
        cell = NetworkEntityORM(
            tenant_id=tenant_id,
            entity_type=EntityType.CELL,
            name=f"Live Cell {i}",
            external_id=cell_id,
            attributes={"tech": "5G"}
        )
        db_session.add(cell)
        cells.append(cell)
        await db_session.flush()
        
        # Zone A hosts Cell
        rel_zone_cell = EntityRelationshipORM(
            tenant_id=tenant_id,
            source_entity_id=zone_a.id,
            source_entity_type=EntityType.SERVICE,
            target_entity_id=cell.id,
            target_entity_type=EntityType.CELL,
            relationship_type=RelationshipType.HOSTS
        )
        db_session.add(rel_zone_cell)
        
    await db_session.commit()
    return {
        "tenant_id": tenant_id,
        "site": site,
        "zone": zone_a,
        "cells": cells
    }


@pytest.fixture
async def seeded_zone_topology(db_session):
    return await seed_zone_topology_helper(db_session)

@pytest.mark.asyncio
async def test_tc010_entity_retrieval(db_session, seeded_zone_topology):
    """TC-010: Verify we can retrieve entities by external_id and tenant_id."""
    tenant_id = seeded_zone_topology["tenant_id"]
    cell_id = "CELL_LIVE_1"
    
    q = select(NetworkEntityORM).where(
        NetworkEntityORM.tenant_id == tenant_id,
        NetworkEntityORM.external_id == cell_id
    )
    result = await db_session.execute(q)
    entity = result.scalar_one_or_none()
    
    assert entity is not None
    assert entity.name == "Live Cell 1"
    assert entity.entity_type == EntityType.CELL

@pytest.mark.asyncio
async def test_tc015_graph_traversal(db_session, seeded_zone_topology):
    """TC-015: Verify graph traversal (Cell -> Zone -> Site)."""
    tenant_id = seeded_zone_topology["tenant_id"]
    cell_id = seeded_zone_topology["cells"][0].id
    
    # Find Zone hosting this Cell
    q = select(NetworkEntityORM).join(
        EntityRelationshipORM, 
        EntityRelationshipORM.source_entity_id == NetworkEntityORM.id
    ).where(
        EntityRelationshipORM.target_entity_id == cell_id,
        EntityRelationshipORM.relationship_type == RelationshipType.HOSTS
    )
    result = await db_session.execute(q)
    zone = result.scalar_one_or_none()
    
    assert zone is not None
    assert zone.name == "Zone A"
    
    # Find Site hosting this Zone
    q2 = select(NetworkEntityORM).join(
        EntityRelationshipORM,
        EntityRelationshipORM.source_entity_id == NetworkEntityORM.id
    ).where(
        EntityRelationshipORM.target_entity_id == zone.id,
        EntityRelationshipORM.relationship_type == RelationshipType.HOSTS
    )
    result2 = await db_session.execute(q2)
    site = result2.scalar_one_or_none()
    
    assert site is not None
    assert site.name == "London-Central-Site"

@pytest.mark.asyncio
async def test_tc016_multi_tenant_topology_isolation(db_session, seeded_zone_topology):
    """TC-016: Verify multi-tenant topology isolation."""
    # Seed same external_id for a different tenant
    other_tenant = "other-client"
    cell_id = "CELL_LIVE_1"
    
    other_cell = NetworkEntityORM(
        tenant_id=other_tenant,
        entity_type=EntityType.CELL,
        name="Other Client Cell",
        external_id=cell_id
    )
    db_session.add(other_cell)
    await db_session.commit()
    
    # Query for the original tenant
    q = select(NetworkEntityORM).where(
        NetworkEntityORM.tenant_id == seeded_zone_topology["tenant_id"],
        NetworkEntityORM.external_id == cell_id
    )
    result = await db_session.execute(q)
    entity = result.scalar_one_or_none()
    
    assert entity.name == "Live Cell 1"
    assert entity.tenant_id == seeded_zone_topology["tenant_id"]
