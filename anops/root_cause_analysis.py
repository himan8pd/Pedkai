"""
Root Cause Analysis (RCA) Service for ANOps.

Leverages the Context Graph to perform impact analysis and dependency tracing.
"""

from typing import List, Dict, Any, Optional
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from decision_memory.graph_orm import NetworkEntityORM, EntityRelationshipORM
from decision_memory.graph_schema import RelationshipType, EntityType

class RootCauseAnalyzer:
    """
    Analyzes the root cause of network issues using graph-based traversal.
    """
    
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_entity_by_external_id(self, external_id: str, tenant_id: str) -> Optional[NetworkEntityORM]:
        """Utility to find an entity by its external identifier."""
        query = select(NetworkEntityORM).where(
            NetworkEntityORM.external_id == external_id,
            NetworkEntityORM.tenant_id == tenant_id
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_relationships(self, entity_id: UUID, direction: str = "both") -> List[Dict[str, Any]]:
        """
        Finds direct relationships for an entity.
        - 'upstream': what this entity depends on (incoming HOSTS, outgoing DEPENDS_ON?)
          Wait, schema: source --[rel]--> target.
          Usually: gNodeB --[HOSTS]--> Cell. So Cell upstream is gNodeB (source).
        """
        results = []
        
        # 1. Outgoing relationships (this entity is the source)
        if direction in ["both", "outgoing"]:
            query_out = select(EntityRelationshipORM, NetworkEntityORM).join(
                NetworkEntityORM, EntityRelationshipORM.target_entity_id == NetworkEntityORM.id
            ).where(EntityRelationshipORM.source_entity_id == entity_id)
            
            res_out = await self.session.execute(query_out)
            for rel, target in res_out.all():
                results.append({
                    "relationship": rel.relationship_type,
                    "direction": "outgoing",
                    "entity_id": target.id,
                    "entity_name": target.name,
                    "entity_type": target.entity_type,
                    "external_id": target.external_id
                })
                
        # 2. Incoming relationships (this entity is the target)
        if direction in ["both", "incoming"]:
            query_in = select(EntityRelationshipORM, NetworkEntityORM).join(
                NetworkEntityORM, EntityRelationshipORM.source_entity_id == NetworkEntityORM.id
            ).where(EntityRelationshipORM.target_entity_id == entity_id)
            
            res_in = await self.session.execute(query_in)
            for rel, source in res_in.all():
                results.append({
                    "relationship": rel.relationship_type,
                    "direction": "incoming",
                    "entity_id": source.id,
                    "entity_name": source.name,
                    "entity_type": source.entity_type,
                    "external_id": source.external_id
                })
                
        return results

    async def analyze_incident(self, external_id: str, tenant_id: str) -> Dict[str, Any]:
        """
        Performs a full RCA/Impact analysis for an entity.
        """
        entity = await self.get_entity_by_external_id(external_id, tenant_id)
        if not entity:
            return {"error": f"Entity {external_id} not found"}
            
        rels = await self.get_relationships(entity.id)
        
        # Categorize relationships
        upstream = []
        downstream = []
        
        for r in rels:
            # Domain logic: gNodeB hosts Cell. So gNodeB is incoming/source to Cell.
            if r["relationship"] == RelationshipType.HOSTS:
                if r["direction"] == "incoming":
                    upstream.append(r)
                else:
                    # In this case Cell hosts nothing usually, but for consistency:
                    downstream.append(r)
            
            # Cell serves Customer. Cell is source. Customer is target.
            elif r["relationship"] == RelationshipType.SERVES:
                if r["direction"] == "outgoing":
                    downstream.append(r)
                else:
                    upstream.append(r)
                    
            # Customer covered by SLA.
            elif r["relationship"] == RelationshipType.COVERED_BY:
                if r["direction"] == "outgoing":
                    downstream.append(r)
        
        # Recursive check for SLA if we found a customer
        impacted_slas = []
        for d in downstream:
            if d["entity_type"] == EntityType.ENTERPRISE_CUSTOMER:
                cust_rels = await self.get_relationships(d["entity_id"], direction="outgoing")
                for cr in cust_rels:
                    if cr["relationship"] == RelationshipType.COVERED_BY:
                        impacted_slas.append(cr)

        return {
            "entity_name": entity.name,
            "entity_type": entity.entity_type,
            "upstream_dependencies": upstream,
            "downstream_impacts": downstream,
            "critical_slas": impacted_slas
        }
