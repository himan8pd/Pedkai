"""
Incident Reconstruction — rebuilds incident timelines from fragment history.

Implements the incident reconstruction capability described in the Abeyance
Memory subsystem specification.

Reconstructs a complete timeline for an incident by gathering related
fragments, snap events, accumulation clusters, and enriched entity context
into a coherent narrative.
"""

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.core.logging import get_logger
from backend.app.models.abeyance_orm import (
    AbeyanceFragmentORM,
    AccumulationEdgeORM,
    FragmentEntityRefORM,
)
from backend.app.schemas.abeyance import (
    AbeyanceFragmentSummary,
    AccumulationClusterResponse,
    IncidentReconstructionResponse,
    SnapHistoryEntry,
)

logger = get_logger(__name__)


class IncidentReconstructionService:
    """Rebuilds incident timelines using fragment history.

    Provides the GET /api/v1/incidents/reconstruct/{incident_id} capability
    by assembling time-ordered fragments, cluster context, snap events,
    and enriched entity context.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self.session_factory = session_factory

    async def reconstruct(
        self,
        tenant_id: str,
        incident_id: str,
        session: Optional[AsyncSession] = None,
    ) -> IncidentReconstructionResponse:
        """Reconstruct an incident timeline from Abeyance Memory fragments.

        Steps:
        1. Load incident to identify affected entities
        2. Find related fragments via entity overlap
        3. Time-order fragments
        4. Include cluster context
        5. Include snap history
        6. Build reconstructed timeline
        """
        async with self._get_session(session) as s:
            # Step 1: Load incident to get entity references
            incident_entities = await self._get_incident_entities(
                tenant_id, incident_id, s
            )

            # Step 2: Find related fragments via entity overlap
            fragments = await self._find_related_fragments(
                tenant_id, incident_entities, s
            )

            # Step 3: Time-order
            fragments.sort(
                key=lambda f: f.event_timestamp or f.created_at or datetime.min.replace(tzinfo=timezone.utc)
            )

            # Step 4: Get snap history for matched fragments
            snaps = self._extract_snap_history(fragments)

            # Step 5: Find clusters involving these fragments
            fragment_ids = [f.id for f in fragments]
            clusters = await self._find_clusters(tenant_id, fragment_ids, s)

            # Step 6: Build reconstructed timeline
            timeline = self._build_timeline(fragments, snaps, clusters)

            fragment_summaries = [
                AbeyanceFragmentSummary.model_validate(f)
                for f in fragments
            ]

            logger.info(
                f"Incident reconstructed: incident={incident_id}, "
                f"fragments={len(fragments)}, snaps={len(snaps)}, "
                f"clusters={len(clusters)}"
            )

            return IncidentReconstructionResponse(
                incident_id=incident_id,
                tenant_id=tenant_id,
                fragments=fragment_summaries,
                snaps=snaps,
                clusters=clusters,
                reconstructed_timeline=timeline,
            )

    async def _get_incident_entities(
        self,
        tenant_id: str,
        incident_id: str,
        session: AsyncSession,
    ) -> list[str]:
        """Extract entity identifiers associated with an incident."""
        try:
            from backend.app.models.incident_orm import IncidentORM
            result = await session.execute(
                select(IncidentORM).where(
                    IncidentORM.id == incident_id,
                    IncidentORM.tenant_id == tenant_id,
                )
            )
            incident = result.scalars().first()
            if incident:
                entities = []
                if hasattr(incident, "entity_id") and incident.entity_id:
                    entities.append(str(incident.entity_id))
                if hasattr(incident, "entity_external_id") and incident.entity_external_id:
                    entities.append(str(incident.entity_external_id))
                return entities
        except Exception as e:
            logger.warning(f"Could not load incident {incident_id}: {e}")

        return []

    async def _find_related_fragments(
        self,
        tenant_id: str,
        entity_identifiers: list[str],
        session: AsyncSession,
    ) -> list[AbeyanceFragmentORM]:
        """Find fragments related to the given entities."""
        if not entity_identifiers:
            # Fallback: return recent fragments for the tenant
            result = await session.execute(
                select(AbeyanceFragmentORM)
                .where(AbeyanceFragmentORM.tenant_id == tenant_id)
                .order_by(AbeyanceFragmentORM.created_at.desc())
                .limit(50)
            )
            return list(result.scalars().all())

        # Find fragments via entity ref junction table
        result = await session.execute(
            select(AbeyanceFragmentORM)
            .join(
                FragmentEntityRefORM,
                AbeyanceFragmentORM.id == FragmentEntityRefORM.fragment_id,
            )
            .where(
                AbeyanceFragmentORM.tenant_id == tenant_id,
                FragmentEntityRefORM.entity_identifier.in_(entity_identifiers),
            )
            .distinct()
            .limit(200)
        )
        return list(result.scalars().all())

    def _extract_snap_history(
        self, fragments: list[AbeyanceFragmentORM]
    ) -> list[SnapHistoryEntry]:
        """Extract snap events from fragments."""
        snaps = []
        for f in fragments:
            if f.snap_status == "SNAPPED" and f.snapped_hypothesis_id:
                snaps.append(SnapHistoryEntry(
                    fragment_id=f.id,
                    snapped_to=f.snapped_hypothesis_id,
                    snap_score=0.0,  # Score not stored on fragment
                    failure_mode=self._primary_failure_mode(f),
                    snapped_at=f.updated_at,
                ))
        return snaps

    async def _find_clusters(
        self,
        tenant_id: str,
        fragment_ids: list[UUID],
        session: AsyncSession,
    ) -> list[AccumulationClusterResponse]:
        """Find accumulation clusters involving the given fragments."""
        if not fragment_ids:
            return []

        # Find edges involving these fragments
        result = await session.execute(
            select(AccumulationEdgeORM).where(
                AccumulationEdgeORM.tenant_id == tenant_id,
                (
                    AccumulationEdgeORM.fragment_a_id.in_(fragment_ids)
                    | AccumulationEdgeORM.fragment_b_id.in_(fragment_ids)
                ),
            )
        )
        edges = result.scalars().all()

        if not edges:
            return []

        # Simple connected component detection from edges
        adj: dict[UUID, set[UUID]] = {}
        for e in edges:
            adj.setdefault(e.fragment_a_id, set()).add(e.fragment_b_id)
            adj.setdefault(e.fragment_b_id, set()).add(e.fragment_a_id)

        visited: set[UUID] = set()
        clusters = []

        for node in adj:
            if node in visited:
                continue
            # BFS
            component = set()
            queue = [node]
            while queue:
                current = queue.pop(0)
                if current in visited:
                    continue
                visited.add(current)
                component.add(current)
                for neighbor in adj.get(current, set()):
                    if neighbor not in visited:
                        queue.append(neighbor)

            if len(component) >= 2:
                # Compute score from edges within cluster
                cluster_edges = [
                    e for e in edges
                    if e.fragment_a_id in component and e.fragment_b_id in component
                ]
                from backend.app.services.fusion.noisy_or import NoisyORFusion
                fusion = NoisyORFusion()
                score = fusion.combine([e.affinity_score for e in cluster_edges]) if cluster_edges else 0.0

                clusters.append(AccumulationClusterResponse(
                    cluster_id=str(min(component, key=str)),
                    member_fragment_ids=list(component),
                    member_count=len(component),
                    cluster_score=score,
                    strongest_failure_mode=cluster_edges[0].strongest_failure_mode if cluster_edges else None,
                ))

        return clusters

    def _build_timeline(
        self,
        fragments: list[AbeyanceFragmentORM],
        snaps: list[SnapHistoryEntry],
        clusters: list[AccumulationClusterResponse],
    ) -> list[dict]:
        """Build a reconstructed timeline combining fragments, snaps, and clusters."""
        timeline = []

        for f in fragments:
            entry = {
                "type": "fragment",
                "timestamp": (f.event_timestamp or f.created_at or datetime.now(timezone.utc)).isoformat(),
                "fragment_id": str(f.id),
                "source_type": f.source_type,
                "snap_status": f.snap_status,
                "decay_score": f.current_decay_score,
                "summary": (f.raw_content or "")[:200],
            }

            # Add failure mode info
            tags = f.failure_mode_tags or []
            if tags and isinstance(tags, list) and len(tags) > 0:
                tag = tags[0]
                if isinstance(tag, dict):
                    entry["failure_mode"] = tag.get("divergence_type", "")
                    entry["failure_confidence"] = tag.get("confidence", 0.0)

            timeline.append(entry)

        # Add snap events to timeline
        for snap in snaps:
            if snap.snapped_at:
                timeline.append({
                    "type": "snap",
                    "timestamp": snap.snapped_at.isoformat(),
                    "fragment_id": str(snap.fragment_id),
                    "snapped_to": str(snap.snapped_to),
                    "failure_mode": snap.failure_mode,
                })

        # Add cluster events
        for cluster in clusters:
            timeline.append({
                "type": "cluster",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "cluster_id": cluster.cluster_id,
                "member_count": cluster.member_count,
                "cluster_score": cluster.cluster_score,
                "failure_mode": cluster.strongest_failure_mode,
            })

        # Sort by timestamp
        timeline.sort(key=lambda e: e.get("timestamp", ""))

        return timeline

    def _primary_failure_mode(self, fragment: AbeyanceFragmentORM) -> Optional[str]:
        """Get the primary (highest confidence) failure mode from a fragment."""
        tags = fragment.failure_mode_tags or []
        if not tags or not isinstance(tags, list):
            return None
        best = max(tags, key=lambda t: t.get("confidence", 0) if isinstance(t, dict) else 0)
        return best.get("divergence_type") if isinstance(best, dict) else None

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
