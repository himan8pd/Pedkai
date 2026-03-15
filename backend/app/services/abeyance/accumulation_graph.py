"""
Accumulation Graph — combines fragments into compound discoveries.

Implements ABEYANCE_MEMORY_LLD.md §10 (The Accumulation Graph).

Captures weak inter-fragment relationships and detects when a cluster of
weakly-connected fragments collectively constitutes strong evidence.
This solves the multi-fragment accumulation problem where no pairwise snap
score crosses the threshold, but the cluster as a whole is compelling.
"""

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.core.logging import get_logger
from backend.app.models.abeyance_orm import (
    AbeyanceFragmentORM,
    AccumulationEdgeORM,
)
from backend.app.schemas.abeyance import (
    AccumulationClusterResponse,
    AccumulationEdgeResponse,
)

logger = get_logger(__name__)

# Cluster snap threshold (LLD §10) — lower than pairwise because
# multi-fragment corroboration provides structural confidence
CLUSTER_SNAP_THRESHOLD = 0.70
CLUSTER_MIN_MEMBERS = 3


class AccumulationGraphService:
    """Manages the accumulation graph for multi-fragment cluster detection (LLD §10).

    Affinity edges are created when two fragments score above the affinity
    threshold (0.40) but below the snap threshold (0.75). Periodically or
    on edge creation, connected components are evaluated for cluster snaps.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self.session_factory = session_factory

    async def add_or_update_edge(
        self,
        tenant_id: str,
        fragment_a_id: UUID,
        fragment_b_id: UUID,
        affinity_score: float,
        failure_mode: str,
        session: Optional[AsyncSession] = None,
    ) -> AccumulationEdgeORM:
        """Create or update an affinity edge between two fragments (LLD §10).

        If an edge already exists, updates to the higher score.
        """
        # Normalise order so (a,b) and (b,a) map to the same edge
        a_id, b_id = sorted([fragment_a_id, fragment_b_id], key=str)

        async with self._get_session(session) as s:
            # Check for existing edge
            result = await s.execute(
                select(AccumulationEdgeORM).where(
                    AccumulationEdgeORM.fragment_a_id == a_id,
                    AccumulationEdgeORM.fragment_b_id == b_id,
                )
            )
            existing = result.scalars().first()

            if existing:
                if affinity_score > existing.affinity_score:
                    existing.affinity_score = affinity_score
                    existing.strongest_failure_mode = failure_mode
                    existing.last_updated = datetime.now(timezone.utc)
                return existing

            edge = AccumulationEdgeORM(
                id=uuid4(),
                tenant_id=tenant_id,
                fragment_a_id=a_id,
                fragment_b_id=b_id,
                affinity_score=affinity_score,
                strongest_failure_mode=failure_mode,
            )
            s.add(edge)
            await s.flush()

            logger.info(
                f"Accumulation edge created: {a_id} <-> {b_id}, "
                f"score={affinity_score:.3f}, mode={failure_mode}"
            )
            return edge

    async def get_edges(
        self,
        tenant_id: str,
        fragment_id: Optional[UUID] = None,
        session: Optional[AsyncSession] = None,
    ) -> list[AccumulationEdgeResponse]:
        """Query accumulation graph edges."""
        async with self._get_session(session) as s:
            query = select(AccumulationEdgeORM).where(
                AccumulationEdgeORM.tenant_id == tenant_id
            )
            if fragment_id:
                query = query.where(
                    (AccumulationEdgeORM.fragment_a_id == fragment_id)
                    | (AccumulationEdgeORM.fragment_b_id == fragment_id)
                )
            query = query.order_by(AccumulationEdgeORM.affinity_score.desc()).limit(500)

            result = await s.execute(query)
            return [
                AccumulationEdgeResponse.model_validate(e)
                for e in result.scalars().all()
            ]

    async def detect_clusters(
        self,
        tenant_id: str,
        min_members: int = CLUSTER_MIN_MEMBERS,
        session: Optional[AsyncSession] = None,
    ) -> list[AccumulationClusterResponse]:
        """Detect connected components in the accumulation graph (LLD §10).

        Uses recursive CTE to find clusters with >= min_members fragments.
        """
        async with self._get_session(session) as s:
            # Recursive CTE for connected components (LLD §10)
            sql = text("""
                WITH RECURSIVE component AS (
                    SELECT fragment_a_id AS node, fragment_a_id AS component_root
                    FROM accumulation_edge
                    WHERE tenant_id = :tid

                    UNION

                    SELECT ae.fragment_b_id, c.component_root
                    FROM accumulation_edge ae
                    JOIN component c ON ae.fragment_a_id = c.node
                    WHERE ae.tenant_id = :tid

                    UNION

                    SELECT ae.fragment_a_id, c.component_root
                    FROM accumulation_edge ae
                    JOIN component c ON ae.fragment_b_id = c.node
                    WHERE ae.tenant_id = :tid
                )
                SELECT component_root,
                       array_agg(DISTINCT node) AS members,
                       count(DISTINCT node) AS size
                FROM component
                GROUP BY component_root
                HAVING count(DISTINCT node) >= :min_members
                ORDER BY count(DISTINCT node) DESC
            """)

            result = await s.execute(sql, {"tid": tenant_id, "min_members": min_members})
            rows = result.fetchall()

            clusters = []
            seen_members = set()  # Avoid reporting the same cluster under multiple roots

            for row in rows:
                member_ids = [UUID(str(m)) for m in row.members]
                member_key = frozenset(str(m) for m in member_ids)
                if member_key in seen_members:
                    continue
                seen_members.add(member_key)

                # Score the cluster
                cluster_score, dominant_mode = await self._score_cluster(
                    tenant_id, member_ids, s
                )

                clusters.append(AccumulationClusterResponse(
                    cluster_id=str(row.component_root),
                    member_fragment_ids=member_ids,
                    member_count=row.size,
                    cluster_score=cluster_score,
                    strongest_failure_mode=dominant_mode,
                ))

            return clusters

    async def _score_cluster(
        self,
        tenant_id: str,
        member_ids: list[UUID],
        session: AsyncSession,
    ) -> tuple[float, Optional[str]]:
        """Score a cluster using Noisy-OR fusion (LLD §10).

        P(hypothesis | cluster) = 1 - ∏(1 - affinity_score_i) for all edges.
        """
        from backend.app.services.fusion.noisy_or import NoisyORFusion

        # Fetch all edges within this cluster
        str_ids = [str(m) for m in member_ids]
        result = await session.execute(
            select(AccumulationEdgeORM).where(
                AccumulationEdgeORM.tenant_id == tenant_id,
                AccumulationEdgeORM.fragment_a_id.in_(member_ids),
                AccumulationEdgeORM.fragment_b_id.in_(member_ids),
            )
        )
        edges = result.scalars().all()

        if not edges:
            return 0.0, None

        scores = [e.affinity_score for e in edges]
        fusion = NoisyORFusion()
        cluster_score = fusion.combine(scores)

        # Dominant failure mode — most common among edges
        mode_counts: dict[str, int] = {}
        for e in edges:
            mode = e.strongest_failure_mode or "DARK_EDGE"
            mode_counts[mode] = mode_counts.get(mode, 0) + 1
        dominant_mode = max(mode_counts, key=mode_counts.get) if mode_counts else None

        return cluster_score, dominant_mode

    async def evaluate_clusters(
        self,
        tenant_id: str,
        trigger_fragment_id: Optional[UUID] = None,
        session: Optional[AsyncSession] = None,
    ) -> list[AccumulationClusterResponse]:
        """Detect and evaluate clusters for snap (LLD §10).

        Called when a new affinity edge is created. If a cluster's
        aggregate score exceeds CLUSTER_SNAP_THRESHOLD (0.70), all
        members snap as a multi-fragment hypothesis.
        """
        async with self._get_session(session) as s:
            clusters = await self.detect_clusters(
                tenant_id=tenant_id,
                min_members=CLUSTER_MIN_MEMBERS,
                session=s,
            )

            snapped_clusters = []
            for cluster in clusters:
                if cluster.cluster_score >= CLUSTER_SNAP_THRESHOLD:
                    # Cluster snap — mark all members as SNAPPED
                    await self._snap_cluster(cluster, tenant_id, s)
                    snapped_clusters.append(cluster)

            if snapped_clusters:
                logger.info(
                    f"Cluster snaps: {len(snapped_clusters)} clusters snapped "
                    f"for tenant={tenant_id}"
                )

            return snapped_clusters

    async def _snap_cluster(
        self,
        cluster: AccumulationClusterResponse,
        tenant_id: str,
        session: AsyncSession,
    ) -> None:
        """Mark all fragments in a cluster as SNAPPED (LLD §10)."""
        now = datetime.now(timezone.utc)
        hypothesis_id = uuid4()  # Shared hypothesis ID for all cluster members

        for frag_id in cluster.member_fragment_ids:
            fragment = await session.get(AbeyanceFragmentORM, frag_id)
            if fragment and fragment.snap_status == "ABEYANCE":
                fragment.snap_status = "SNAPPED"
                fragment.snapped_hypothesis_id = hypothesis_id
                fragment.updated_at = now

        logger.info(
            f"Cluster snapped: {len(cluster.member_fragment_ids)} fragments, "
            f"score={cluster.cluster_score:.3f}, "
            f"mode={cluster.strongest_failure_mode}, "
            f"hypothesis={hypothesis_id}"
        )

    async def remove_expired_edges(
        self,
        tenant_id: str,
        session: Optional[AsyncSession] = None,
    ) -> int:
        """Remove edges for expired/stale fragments (LLD §11)."""
        async with self._get_session(session) as s:
            sql = text("""
                DELETE FROM accumulation_edge ae
                USING abeyance_fragment af
                WHERE ae.tenant_id = :tid
                  AND (
                      (ae.fragment_a_id = af.id AND af.snap_status IN ('EXPIRED', 'COLD'))
                      OR
                      (ae.fragment_b_id = af.id AND af.snap_status IN ('EXPIRED', 'COLD'))
                  )
            """)
            result = await s.execute(sql, {"tid": tenant_id})
            count = result.rowcount or 0
            if count:
                logger.info(f"Removed {count} expired accumulation edges for tenant={tenant_id}")
            return count

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
