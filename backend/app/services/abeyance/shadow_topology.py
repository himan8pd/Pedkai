"""
Shadow Topology Service — PedkAI's private topology graph.

Implements ABEYANCE_MEMORY_LLD.md §8 (The Shadow Topology — Protecting the Moat).

The Shadow Topology maintains an internal graph that is strictly private and
never directly exposed to external systems. It enriches future fragment
matching while protecting PedkAI's competitive moat through controlled CMDB
export with reference tagging.
"""

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.core.logging import get_logger
from backend.app.models.abeyance_orm import (
    CmdbExportLogORM,
    ShadowEntityORM,
    ShadowRelationshipORM,
)
from backend.app.schemas.abeyance import (
    CmdbExportResponse,
    ShadowEntityResponse,
    ShadowNeighbourhoodResponse,
    ShadowRelationshipResponse,
)

logger = get_logger(__name__)


class ShadowTopologyService:
    """Manages PedkAI's private topology graph (LLD §8).

    The Shadow Topology contains both CMDB-declared and PedkAI-discovered
    entities and relationships. Evidence chains, scoring calibration, and
    accumulation metadata are retained internally and never exported.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self.session_factory = session_factory

    async def get_or_create_entity(
        self,
        tenant_id: str,
        entity_identifier: str,
        entity_domain: Optional[str] = None,
        origin: str = "CMDB_DECLARED",
        attributes: Optional[dict] = None,
        session: Optional[AsyncSession] = None,
    ) -> ShadowEntityORM:
        """Upsert a shadow entity. Implements LLD §8 SHADOW_ENTITY.

        If the entity already exists for this tenant, returns existing.
        Otherwise creates a new record.
        """
        async with self._get_session(session) as s:
            result = await s.execute(
                select(ShadowEntityORM).where(
                    ShadowEntityORM.tenant_id == tenant_id,
                    ShadowEntityORM.entity_identifier == entity_identifier,
                )
            )
            entity = result.scalars().first()

            if entity:
                entity.last_evidence = datetime.now(timezone.utc)
                if attributes:
                    existing = entity.attributes or {}
                    existing.update(attributes)
                    entity.attributes = existing
                return entity

            entity = ShadowEntityORM(
                id=uuid4(),
                tenant_id=tenant_id,
                entity_identifier=entity_identifier,
                entity_domain=entity_domain,
                origin=origin,
                attributes=attributes or {},
                cmdb_attributes=attributes or {},
            )
            s.add(entity)
            await s.flush()
            logger.info(
                f"Shadow entity created: {entity_identifier} "
                f"(tenant={tenant_id}, origin={origin})"
            )
            return entity

    async def add_relationship(
        self,
        tenant_id: str,
        from_entity_id: UUID,
        to_entity_id: UUID,
        relationship_type: str,
        confidence: float = 1.0,
        origin: str = "CMDB_DECLARED",
        evidence_summary: Optional[dict] = None,
        discovery_hypothesis_id: Optional[UUID] = None,
        session: Optional[AsyncSession] = None,
    ) -> ShadowRelationshipORM:
        """Add a relationship to the Shadow Topology (LLD §8 SHADOW_RELATIONSHIP)."""
        async with self._get_session(session) as s:
            rel = ShadowRelationshipORM(
                id=uuid4(),
                tenant_id=tenant_id,
                from_entity_id=from_entity_id,
                to_entity_id=to_entity_id,
                relationship_type=relationship_type,
                origin=origin,
                confidence=confidence,
                evidence_summary=evidence_summary or {},
                discovery_hypothesis_id=discovery_hypothesis_id,
            )
            s.add(rel)
            await s.flush()
            return rel

    async def get_neighbourhood(
        self,
        tenant_id: str,
        entity_identifier: str,
        hops: int = 2,
        session: Optional[AsyncSession] = None,
    ) -> ShadowNeighbourhoodResponse:
        """Expand entity through Shadow Topology relationships up to N hops.

        Implements LLD §8 — 2-hop neighbourhood expansion used by the
        Enrichment Chain (§6 Step 1) to bridge cross-domain vocabulary.
        Uses recursive CTE to walk relationships.
        """
        async with self._get_session(session) as s:
            # First find the center entity
            center_result = await s.execute(
                select(ShadowEntityORM).where(
                    ShadowEntityORM.tenant_id == tenant_id,
                    ShadowEntityORM.entity_identifier == entity_identifier,
                )
            )
            center = center_result.scalars().first()
            if not center:
                return ShadowNeighbourhoodResponse(
                    center_entity=entity_identifier,
                    max_hops=hops,
                )

            # Recursive CTE for N-hop expansion
            cte_sql = text("""
                WITH RECURSIVE neighbourhood AS (
                    SELECT sr.id, sr.from_entity_id, sr.to_entity_id,
                           sr.relationship_type, sr.origin, sr.confidence,
                           sr.exported_to_cmdb, sr.cmdb_reference_tag,
                           1 as depth
                    FROM shadow_relationship sr
                    WHERE sr.tenant_id = :tid
                      AND (sr.from_entity_id = :eid OR sr.to_entity_id = :eid)

                    UNION ALL

                    SELECT sr.id, sr.from_entity_id, sr.to_entity_id,
                           sr.relationship_type, sr.origin, sr.confidence,
                           sr.exported_to_cmdb, sr.cmdb_reference_tag,
                           n.depth + 1
                    FROM shadow_relationship sr
                    JOIN neighbourhood n ON (
                        sr.from_entity_id = n.to_entity_id
                        OR sr.to_entity_id = n.from_entity_id
                        OR sr.from_entity_id = n.from_entity_id
                        OR sr.to_entity_id = n.to_entity_id
                    )
                    WHERE sr.tenant_id = :tid
                      AND n.depth < :max_hops
                      AND sr.id != n.id
                )
                SELECT DISTINCT id, from_entity_id, to_entity_id,
                       relationship_type, origin, confidence,
                       exported_to_cmdb, cmdb_reference_tag
                FROM neighbourhood
            """)

            result = await s.execute(
                cte_sql,
                {"tid": tenant_id, "eid": str(center.id), "max_hops": hops},
            )
            rows = result.fetchall()

            # Collect all entity IDs from relationships
            entity_ids = {center.id}
            relationships = []
            for row in rows:
                entity_ids.add(row.from_entity_id)
                entity_ids.add(row.to_entity_id)
                relationships.append(ShadowRelationshipResponse(
                    id=row.id,
                    from_entity_id=row.from_entity_id,
                    to_entity_id=row.to_entity_id,
                    relationship_type=row.relationship_type,
                    origin=row.origin,
                    confidence=row.confidence,
                    exported_to_cmdb=row.exported_to_cmdb,
                    cmdb_reference_tag=row.cmdb_reference_tag,
                ))

            # Fetch all entities
            if entity_ids:
                ent_result = await s.execute(
                    select(ShadowEntityORM).where(
                        ShadowEntityORM.id.in_(list(entity_ids))
                    )
                )
                entities = [
                    ShadowEntityResponse.model_validate(e)
                    for e in ent_result.scalars().all()
                ]
            else:
                entities = []

            return ShadowNeighbourhoodResponse(
                center_entity=entity_identifier,
                entities=entities,
                relationships=relationships,
                max_hops=hops,
            )

    async def topological_proximity(
        self,
        tenant_id: str,
        entity_set_a: set[str],
        entity_set_b: set[str],
        session: Optional[AsyncSession] = None,
    ) -> float:
        """Shortest path between nearest entities of two sets.

        Implements LLD §9 Evidence Scoring component.
        Returns 1.0 / min_hops (capped at 1.0 for direct connection).
        Returns 0.0 if disconnected.
        """
        if not entity_set_a or not entity_set_b:
            return 0.0

        # Direct entity overlap = distance 0 = proximity 1.0
        if entity_set_a & entity_set_b:
            return 1.0

        async with self._get_session(session) as s:
            # BFS from entity_set_a, check intersection with entity_set_b
            sql = text("""
                WITH RECURSIVE bfs AS (
                    SELECT se.entity_identifier, 0 as hops
                    FROM shadow_entity se
                    WHERE se.tenant_id = :tid
                      AND se.entity_identifier = ANY(:start_ids)

                    UNION ALL

                    SELECT CASE
                        WHEN sr.from_entity_id = se2.id THEN se3.entity_identifier
                        ELSE se2.entity_identifier
                    END, b.hops + 1
                    FROM bfs b
                    JOIN shadow_entity se2 ON se2.entity_identifier = b.entity_identifier
                        AND se2.tenant_id = :tid
                    JOIN shadow_relationship sr ON (
                        sr.from_entity_id = se2.id OR sr.to_entity_id = se2.id
                    )
                    JOIN shadow_entity se3 ON (
                        se3.id = CASE
                            WHEN sr.from_entity_id = se2.id THEN sr.to_entity_id
                            ELSE sr.from_entity_id
                        END
                    )
                    WHERE sr.tenant_id = :tid AND b.hops < 5
                )
                SELECT MIN(hops) as min_hops
                FROM bfs
                WHERE entity_identifier = ANY(:target_ids)
            """)

            result = await s.execute(
                sql,
                {
                    "tid": tenant_id,
                    "start_ids": list(entity_set_a),
                    "target_ids": list(entity_set_b),
                },
            )
            row = result.fetchone()
            if row and row.min_hops is not None:
                return 1.0 / max(row.min_hops, 1)

        return 0.0

    async def enrich_on_validated_snap(
        self,
        tenant_id: str,
        hypothesis_id: UUID,
        entity_identifiers: list[str],
        relationships: Optional[list[dict]] = None,
        session: Optional[AsyncSession] = None,
    ) -> None:
        """Add discovered entities/relationships to Shadow Topology on validated snap.

        Implements LLD §8 — the flywheel trigger. Called when a hypothesis
        reaches ACCEPTED status. Creates records with origin=PEDKAI_DISCOVERED.
        Does NOT export to CMDB — that's a separate controlled action.
        """
        async with self._get_session(session) as s:
            entity_id_map = {}
            for ident in entity_identifiers:
                entity = await self.get_or_create_entity(
                    tenant_id=tenant_id,
                    entity_identifier=ident,
                    origin="PEDKAI_DISCOVERED",
                    session=s,
                )
                # Update origin if it was previously CMDB_DECLARED
                if entity.origin == "CMDB_DECLARED":
                    entity.origin = "PEDKAI_CORRECTED"
                entity.discovery_hypothesis_id = hypothesis_id
                entity_id_map[ident] = entity.id

            for rel in (relationships or []):
                from_id = entity_id_map.get(rel.get("from_entity"))
                to_id = entity_id_map.get(rel.get("to_entity"))
                if from_id and to_id:
                    await self.add_relationship(
                        tenant_id=tenant_id,
                        from_entity_id=from_id,
                        to_entity_id=to_id,
                        relationship_type=rel.get("type", "discovered_link"),
                        origin="PEDKAI_DISCOVERED",
                        confidence=rel.get("confidence", 0.8),
                        evidence_summary=rel.get("evidence", {}),
                        discovery_hypothesis_id=hypothesis_id,
                        session=s,
                    )

            logger.info(
                f"Shadow Topology enriched: hypothesis={hypothesis_id}, "
                f"entities={len(entity_identifiers)}, "
                f"relationships={len(relationships or [])}"
            )

    async def export_to_cmdb(
        self,
        tenant_id: str,
        relationship_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> CmdbExportResponse:
        """Controlled export to customer CMDB with sanitisation and reference tagging.

        Implements LLD §8 — strips evidence_summary, confidence, fragment refs.
        Generates CMDB reference tag for value attribution (LLD §13).
        """
        async with self._get_session(session) as s:
            result = await s.execute(
                select(ShadowRelationshipORM).where(
                    ShadowRelationshipORM.id == relationship_id,
                    ShadowRelationshipORM.tenant_id == tenant_id,
                )
            )
            rel = result.scalars().first()
            if not rel:
                raise ValueError(f"Relationship {relationship_id} not found")

            # Generate reference tag (LLD §8)
            ref_tag = f"PEDKAI-{str(tenant_id)[:8]}-{str(relationship_id)[:8]}"

            # Sanitised export payload — NO evidence chains, scoring, fragment refs
            exported_payload = {
                "from_entity_id": str(rel.from_entity_id),
                "to_entity_id": str(rel.to_entity_id),
                "relationship_type": rel.relationship_type,
                "pedkai_reference_tag": ref_tag,
                "discovered_at": rel.discovered_at.isoformat() if rel.discovered_at else None,
            }

            # Retained payload — NEVER EXPORTED
            retained_payload = {
                "evidence_summary": rel.evidence_summary,
                "confidence": rel.confidence,
                "discovery_hypothesis_id": str(rel.discovery_hypothesis_id) if rel.discovery_hypothesis_id else None,
            }

            now = datetime.now(timezone.utc)

            # Update relationship
            rel.exported_to_cmdb = True
            rel.exported_at = now
            rel.cmdb_reference_tag = ref_tag

            # Log export
            log_entry = CmdbExportLogORM(
                id=uuid4(),
                tenant_id=tenant_id,
                relationship_id=relationship_id,
                export_type="NEW_RELATIONSHIP",
                exported_at=now,
                exported_payload=exported_payload,
                retained_payload=retained_payload,
                cmdb_reference_tag=ref_tag,
            )
            s.add(log_entry)
            await s.flush()

            logger.info(
                f"CMDB export: relationship={relationship_id}, tag={ref_tag}"
            )
            return CmdbExportResponse(
                export_id=log_entry.id,
                cmdb_reference_tag=ref_tag,
                exported_at=now,
            )

    async def seed_from_topology(
        self,
        tenant_id: str,
        session: Optional[AsyncSession] = None,
    ) -> dict:
        """Bulk import from existing topology tables into Shadow Topology.

        Populates the Shadow Topology from the network_entities and
        topology_relationships tables as the Day 1 baseline (LLD §8).
        """
        from backend.app.models.topology_models import EntityRelationshipORM

        async with self._get_session(session) as s:
            # Import relationships (which implicitly define entities)
            result = await s.execute(
                select(EntityRelationshipORM).where(
                    EntityRelationshipORM.tenant_id == tenant_id
                )
            )
            rels = result.scalars().all()

            entity_map = {}
            rel_count = 0

            for rel in rels:
                # Ensure both entities exist in shadow topology
                for eid, etype in [
                    (rel.from_entity_id, rel.from_entity_type),
                    (rel.to_entity_id, rel.to_entity_type),
                ]:
                    if eid not in entity_map:
                        entity = await self.get_or_create_entity(
                            tenant_id=tenant_id,
                            entity_identifier=eid,
                            entity_domain=etype,
                            origin="CMDB_DECLARED",
                            session=s,
                        )
                        entity_map[eid] = entity.id

                # Add relationship
                await self.add_relationship(
                    tenant_id=tenant_id,
                    from_entity_id=entity_map[rel.from_entity_id],
                    to_entity_id=entity_map[rel.to_entity_id],
                    relationship_type=rel.relationship_type,
                    origin="CMDB_DECLARED",
                    session=s,
                )
                rel_count += 1

            logger.info(
                f"Shadow Topology seeded: tenant={tenant_id}, "
                f"entities={len(entity_map)}, relationships={rel_count}"
            )
            return {"entities": len(entity_map), "relationships": rel_count}

    def _get_session(self, session: Optional[AsyncSession] = None):
        """Support both external session (reuse) and internal session creation."""
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _ctx():
            if session:
                yield session
            else:
                async with self.session_factory() as new_session:
                    try:
                        yield new_session
                        await new_session.commit()
                    except Exception:
                        await new_session.rollback()
                        raise
                    finally:
                        await new_session.close()

        return _ctx()


# Singleton factory
_shadow_topology: Optional[ShadowTopologyService] = None


def get_shadow_topology(
    session_factory: Optional[async_sessionmaker] = None,
) -> ShadowTopologyService:
    """Get the Shadow Topology service singleton."""
    global _shadow_topology
    if _shadow_topology is None:
        if session_factory is None:
            from backend.app.core.database import async_session_maker
            session_factory = async_session_maker
        _shadow_topology = ShadowTopologyService(session_factory)
    return _shadow_topology
