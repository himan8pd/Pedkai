"""
Script to seed a sample network topology into the database.
Supports the Context Graph layer (Layer 2) of Pedkai.
"""

import asyncio
from uuid import uuid4
from backend.app.core.database import get_db_context
from decision_memory.graph_orm import NetworkEntityORM, EntityRelationshipORM
from decision_memory.graph_schema import EntityType, RelationshipType

async def seed_topology(tenant_id: str = "global-demo"):
    """
    Seeds a sample RAN topology:
    - 1 gNodeB
    - 3 Cells (one is CELL_LON_001)
    - 1 Enterprise Customer served by CELL_LON_001
    - 1 SLA for that customer
    """
    print(f"🌐 Seeding network topology for {tenant_id}...")
    
    async with get_db_context() as session:
        # 1. Create gNodeB
        gnodeb = NetworkEntityORM(
            tenant_id=tenant_id,
            entity_type=EntityType.GNODEB,
            name="gNB-LON-001",
            external_id="GNB_101",
            attributes={"vendor": "Nokia", "software_version": "v2.4.1"}
        )
        session.add(gnodeb)
        await session.flush() # Get the ID
        
        # 2. Create Cells
        cells = []
        for i in range(3):
            cell_id = "CELL_LON_001" if i == 0 else f"CELL_LON_00{i+1}"
            cell = NetworkEntityORM(
                tenant_id=tenant_id,
                entity_type=EntityType.CELL,
                name=f"London Tower Sector {i+1}",
                external_id=cell_id,
                attributes={"frequency": "3.5GHz", "bandwidth": "100MHz"}
            )
            session.add(cell)
            cells.append(cell)
        await session.flush()
        
        # 3. Create Hosting Relationships
        for cell in cells:
            rel = EntityRelationshipORM(
                tenant_id=tenant_id,
                source_entity_id=gnodeb.id,
                source_entity_type=EntityType.GNODEB,
                target_entity_id=cell.id,
                target_entity_type=EntityType.CELL,
                relationship_type=RelationshipType.HOSTS
            )
            session.add(rel)
            
        # 4. Create Enterprise Customer
        customer = NetworkEntityORM(
            tenant_id=tenant_id,
            entity_type=EntityType.ENTERPRISE_CUSTOMER,
            name="Acme Corp UK",
            external_id="ACME_001",
            attributes={"tier": "platinum", "industry": "Finance"}
        )
        session.add(customer)
        await session.flush()
        
        # 5. Create Serving Relationship (CELL_LON_001 serves Acme)
        rel_serve = EntityRelationshipORM(
            tenant_id=tenant_id,
            source_entity_id=cells[0].id,
            source_entity_type=EntityType.CELL,
            target_entity_id=customer.id,
            target_entity_type=EntityType.ENTERPRISE_CUSTOMER,
            relationship_type=RelationshipType.SERVES
        )
        session.add(rel_serve)
        
        # 6. Create SLA
        sla = NetworkEntityORM(
            tenant_id=tenant_id,
            entity_type=EntityType.SLA,
            name="Acme Gold SLA",
            external_id="SLA_ACME_G",
            attributes={"latency_target": "10ms", "availability": "99.99%"}
        )
        session.add(sla)
        await session.flush()
        
        # 7. Coverage relationship
        rel_sla = EntityRelationshipORM(
            tenant_id=tenant_id,
            source_entity_id=customer.id,
            source_entity_type=EntityType.ENTERPRISE_CUSTOMER,
            target_entity_id=sla.id,
            target_entity_type=EntityType.SLA,
            relationship_type=RelationshipType.COVERED_BY
        )
        session.add(rel_sla)
        
        # 8. Create Voice/SMS Core
        voice_core = NetworkEntityORM(
            tenant_id=tenant_id,
            entity_type=EntityType.VOICE_CORE,
            name="IMS-LON-001",
            external_id="IMS_001",
            attributes={"type": "VoLTE-TAS", "capacity": "1M-users"}
        )
        smsc = NetworkEntityORM(
            tenant_id=tenant_id,
            entity_type=EntityType.SMSC,
            name="SMSC-LON-001",
            external_id="SMSC_001",
            attributes={"vendor": "Ericsson", "throughput": "10k-tps"}
        )
        session.add_all([voice_core, smsc])
        
        # 9. Create Fixed/Landline Infrastructure
        broadband_gw = NetworkEntityORM(
            tenant_id=tenant_id,
            entity_type=EntityType.BROADBAND_GATEWAY,
            name="OLT-LON-001",
            external_id="OLT_001",
            attributes={"technology": "GPON", "ports": 128}
        )
        landline_exchange = NetworkEntityORM(
            tenant_id=tenant_id,
            entity_type=EntityType.LANDLINE_EXCHANGE,
            name="Exchange-LON-Main",
            external_id="EXCH_001",
            attributes={"area": "London-Central", "critical": True}
        )
        emergency_srv = NetworkEntityORM(
            tenant_id=tenant_id,
            entity_type=EntityType.EMERGENCY_SERVICE,
            name="UK-Emergency-999",
            external_id="EMER_999",
            attributes={"priority": "CRITICAL"}
        )
        session.add_all([broadband_gw, landline_exchange, emergency_srv])
        await session.flush()
        
        # 10. Relationships for new entities
        # Landline Exchange connects to Emergency Service
        rel_emer = EntityRelationshipORM(
            tenant_id=tenant_id,
            source_entity_id=landline_exchange.id,
            source_entity_type=EntityType.LANDLINE_EXCHANGE,
            target_entity_id=emergency_srv.id,
            target_entity_type=EntityType.EMERGENCY_SERVICE,
            relationship_type=RelationshipType.CONNECTS_TO
        )
        session.add(rel_emer)
        
        # Cells depend on Voice Core for VoLTE
        for cell in cells:
            rel_voice = EntityRelationshipORM(
                tenant_id=tenant_id,
                source_entity_id=cell.id,
                source_entity_type=EntityType.CELL,
                target_entity_id=voice_core.id,
                target_entity_type=EntityType.VOICE_CORE,
                relationship_type=RelationshipType.DEPENDS_ON
            )
            session.add(rel_voice)
            
        await session.commit()
        print("✅ Topology seeded successfully!")

if __name__ == "__main__":
    asyncio.run(seed_topology())
