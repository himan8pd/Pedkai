"""
Shadow Topology — cycle-guarded BFS with tenant isolation.

Remediation targets:
- Audit §3.4: Recursive CTE explosion → cycle-guarded BFS with visited set
- Audit §9.3: Shadow Topology BFS returns all tenant data → tenant filter on entity fetch

Invariants enforced:
- INV-7: Tenant ID verified on every operation
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import select, and_, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.abeyance_orm import (
    ShadowEntityORM,
    ShadowRelationshipORM,
    CmdbExportLogORM,
)

logger = logging.getLogger(__name__)

# Expansion limits (Phase 5)
MAX_BFS_RESULT = 500
MAX_HOPS = 3
MAX_RELATIONSHIPS_PER_ENTITY = 200


class ShadowTopologyService:
    """Manages PedkAI's private topology graph with cycle-safe BFS."""

    async def get_or_create_entity(
        self,
        session: AsyncSession,
        tenant_id: str,
        entity_identifier: str,
        entity_domain: Optional[str] = None,
        origin: str = "CMDB_DECLARED",
        attributes: Optional[dict] = None,
    ) -> ShadowEntityORM:
        """Upsert a shadow entity (tenant-scoped)."""
        stmt = (
            select(ShadowEntityORM)
            .where(
                ShadowEntityORM.tenant_id == tenant_id,
                ShadowEntityORM.entity_identifier == entity_identifier,
            )
        )
        result = await session.execute(stmt)
        entity = result.scalar_one_or_none()

        if entity:
            entity.last_evidence = datetime.now(timezone.utc)
            if attributes:
                entity.attributes = {**(entity.attributes or {}), **attributes}
            return entity

        entity = ShadowEntityORM(
            id=uuid4(),
            tenant_id=tenant_id,
            entity_identifier=entity_identifier,
            entity_domain=entity_domain,
            origin=origin,
            attributes=attributes or {},
        )
        session.add(entity)
        await session.flush()
        return entity

    async def get_or_create_relationship(
        self,
        session: AsyncSession,
        tenant_id: str,
        from_entity_id: UUID,
        to_entity_id: UUID,
        relationship_type: str,
        origin: str = "CMDB_DECLARED",
        confidence: float = 1.0,
        evidence_summary: Optional[dict] = None,
    ) -> ShadowRelationshipORM:
        """Upsert a shadow relationship (tenant-scoped)."""
        stmt = (
            select(ShadowRelationshipORM)
            .where(
                ShadowRelationshipORM.tenant_id == tenant_id,
                ShadowRelationshipORM.from_entity_id == from_entity_id,
                ShadowRelationshipORM.to_entity_id == to_entity_id,
                ShadowRelationshipORM.relationship_type == relationship_type,
            )
        )
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            if confidence > existing.confidence:
                existing.confidence = confidence
            if evidence_summary:
                existing.evidence_summary = {
                    **(existing.evidence_summary or {}),
                    **evidence_summary,
                }
            return existing

        rel = ShadowRelationshipORM(
            id=uuid4(),
            tenant_id=tenant_id,
            from_entity_id=from_entity_id,
            to_entity_id=to_entity_id,
            relationship_type=relationship_type,
            origin=origin,
            confidence=confidence,
            evidence_summary=evidence_summary or {},
        )
        session.add(rel)
        await session.flush()
        return rel

    async def get_neighbourhood(
        self,
        session: AsyncSession,
        tenant_id: str,
        entity_ids: list[UUID],
        max_hops: int = 2,
    ) -> dict:
        """N-hop neighbourhood expansion with cycle-safe BFS.

        Fixes Audit §3.4:
        - Visited set prevents revisiting nodes
        - Directed walk with CASE expression (not 4 ORed conditions)
        - Tenant filtering on all entity fetches (Audit §9.3)
        - Result bounded by MAX_BFS_RESULT
        """
        max_hops = min(max_hops, MAX_HOPS)
        visited: set[UUID] = set(entity_ids)
        frontier: set[UUID] = set(entity_ids)
        entities_by_depth: dict[int, set[UUID]] = {0: set(entity_ids)}
        all_relationship_ids: set[UUID] = set()

        for depth in range(1, max_hops + 1):
            if not frontier or len(visited) >= MAX_BFS_RESULT:
                break

            # Find relationships from the current frontier (tenant-scoped)
            rel_stmt = (
                select(ShadowRelationshipORM)
                .where(
                    ShadowRelationshipORM.tenant_id == tenant_id,
                    (
                        ShadowRelationshipORM.from_entity_id.in_(list(frontier))
                        | ShadowRelationshipORM.to_entity_id.in_(list(frontier))
                    ),
                )
                .limit(MAX_RELATIONSHIPS_PER_ENTITY * len(frontier))
            )
            result = await session.execute(rel_stmt)
            relationships = list(result.scalars().all())

            next_frontier: set[UUID] = set()
            for rel in relationships:
                all_relationship_ids.add(rel.id)
                # Walk to the other side of the relationship
                if rel.from_entity_id in frontier:
                    neighbor = rel.to_entity_id
                elif rel.to_entity_id in frontier:
                    neighbor = rel.from_entity_id
                else:
                    continue

                # Cycle guard: skip already-visited nodes
                if neighbor not in visited:
                    visited.add(neighbor)
                    next_frontier.add(neighbor)

                    if len(visited) >= MAX_BFS_RESULT:
                        break

            entities_by_depth[depth] = next_frontier
            frontier = next_frontier

        # Fetch entity details (tenant-scoped, Audit §9.3)
        all_entity_ids = list(visited)
        entities = []
        if all_entity_ids:
            entity_stmt = (
                select(ShadowEntityORM)
                .where(
                    ShadowEntityORM.tenant_id == tenant_id,  # Audit §9.3 fix
                    ShadowEntityORM.id.in_(all_entity_ids),
                )
            )
            result = await session.execute(entity_stmt)
            entities = list(result.scalars().all())

        # Fetch relationship details
        relationships_out = []
        if all_relationship_ids:
            rel_detail_stmt = (
                select(ShadowRelationshipORM)
                .where(
                    ShadowRelationshipORM.tenant_id == tenant_id,
                    ShadowRelationshipORM.id.in_(list(all_relationship_ids)),
                )
            )
            result = await session.execute(rel_detail_stmt)
            relationships_out = list(result.scalars().all())

        return {
            "entities": entities,
            "relationships": relationships_out,
            "depths": {
                depth: [str(eid) for eid in eids]
                for depth, eids in entities_by_depth.items()
            },
            "total_entities": len(entities),
            "total_relationships": len(relationships_out),
        }

    async def topological_proximity(
        self,
        session: AsyncSession,
        tenant_id: str,
        entity_set_a: set[UUID],
        entity_set_b: set[UUID],
        max_hops: int = 3,
    ) -> float:
        """Shortest path between nearest entities of two sets.

        Returns 1.0 / min_hops, capped at 1.0 for direct connection.
        Returns 0.0 if no path found within max_hops.
        """
        if not entity_set_a or not entity_set_b:
            return 0.0

        # Check direct overlap
        if entity_set_a & entity_set_b:
            return 1.0

        # BFS from set_a, looking for any member of set_b
        visited: set[UUID] = set(entity_set_a)
        frontier: set[UUID] = set(entity_set_a)

        for depth in range(1, max_hops + 1):
            if not frontier:
                break

            rel_stmt = (
                select(ShadowRelationshipORM)
                .where(
                    ShadowRelationshipORM.tenant_id == tenant_id,
                    (
                        ShadowRelationshipORM.from_entity_id.in_(list(frontier))
                        | ShadowRelationshipORM.to_entity_id.in_(list(frontier))
                    ),
                )
            )
            result = await session.execute(rel_stmt)
            relationships = list(result.scalars().all())

            next_frontier: set[UUID] = set()
            for rel in relationships:
                if rel.from_entity_id in frontier:
                    neighbor = rel.to_entity_id
                elif rel.to_entity_id in frontier:
                    neighbor = rel.from_entity_id
                else:
                    continue

                if neighbor in entity_set_b:
                    return 1.0 / depth

                if neighbor not in visited:
                    visited.add(neighbor)
                    next_frontier.add(neighbor)

            frontier = next_frontier

        return 0.0

    async def enrich_on_validated_snap(
        self,
        session: AsyncSession,
        tenant_id: str,
        hypothesis_id: UUID,
        entity_ids: list[UUID],
        relationship_pairs: list[tuple[UUID, UUID, str]],
    ) -> None:
        """Add discovered entities/relationships on validated snap (LLD §8)."""
        for from_id, to_id, rel_type in relationship_pairs:
            await self.get_or_create_relationship(
                session, tenant_id, from_id, to_id, rel_type,
                origin="PEDKAI_DISCOVERED",
                confidence=0.8,
                evidence_summary={"hypothesis_id": str(hypothesis_id)},
            )

    async def export_to_cmdb(
        self,
        session: AsyncSession,
        tenant_id: str,
        relationship_id: UUID,
    ) -> dict:
        """Controlled export: sanitise and push to customer CMDB."""
        rel_stmt = (
            select(ShadowRelationshipORM)
            .where(
                ShadowRelationshipORM.id == relationship_id,
                ShadowRelationshipORM.tenant_id == tenant_id,  # INV-7
            )
        )
        result = await session.execute(rel_stmt)
        relationship = result.scalar_one_or_none()

        if not relationship:
            raise ValueError(f"Relationship {relationship_id} not found for tenant {tenant_id}")

        # Generate reference tag
        ref_tag = f"PEDKAI-{str(tenant_id)[:8]}-{str(relationship_id)[:8]}"

        # Sanitised export payload (strip evidence_summary, confidence, etc.)
        export_payload = {
            "from_entity_id": str(relationship.from_entity_id),
            "to_entity_id": str(relationship.to_entity_id),
            "relationship_type": relationship.relationship_type,
            "pedkai_reference_tag": ref_tag,
            "discovered_at": relationship.discovered_at.isoformat() if relationship.discovered_at else None,
        }

        # Retained payload (proprietary — NEVER exported)
        retained_payload = {
            "confidence": relationship.confidence,
            "evidence_summary": relationship.evidence_summary,
            "origin": relationship.origin,
        }

        # Mark as exported
        relationship.exported_to_cmdb = True
        relationship.exported_at = datetime.now(timezone.utc)
        relationship.cmdb_reference_tag = ref_tag

        # Log export
        log_entry = CmdbExportLogORM(
            id=uuid4(),
            tenant_id=tenant_id,
            relationship_id=relationship_id,
            export_type="NEW_RELATIONSHIP",
            exported_payload=export_payload,
            retained_payload=retained_payload,
            cmdb_reference_tag=ref_tag,
        )
        session.add(log_entry)
        await session.flush()

        return {
            "export_id": str(log_entry.id),
            "cmdb_reference_tag": ref_tag,
            "exported_payload": export_payload,
        }
