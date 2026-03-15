"""
Accumulation Graph — Log-Mean-Exp scoring replacing Noisy-OR.

Remediation targets:
- Audit §4.1: Noisy-OR overconfident → replaced with LME + correlation discount
- Audit §5.3: Recursive CTE no cycle guard → Python-side union-find
- Audit §7.3: Cluster formation unobservable → ClusterSnapshot persisted
- Audit §9.2: No tenant check on edge queries → tenant_id on all queries

Invariants enforced:
- INV-4: Cluster membership is monotonic convergent
- INV-8: Cluster scores in [0.0, 1.0]
- INV-9: MAX_EDGES_PER_FRAGMENT bounds graph growth
- INV-10: Cluster evaluation persisted to ClusterSnapshot
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import select, delete, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.abeyance_orm import (
    AccumulationEdgeORM,
    AbeyanceFragmentORM,
)
from backend.app.services.abeyance.events import (
    ClusterEvaluation,
    ProvenanceLogger,
    RedisNotifier,
)

logger = logging.getLogger(__name__)

# Bounds (INV-9)
MAX_EDGES_PER_FRAGMENT = 20
MAX_CLUSTER_SIZE = 50
MIN_CLUSTER_SIZE = 3

# LME parameters (Phase 4, §4.3)
LME_TEMPERATURE = 0.3
CLUSTER_SNAP_THRESHOLD = 0.70


def _log_mean_exp(scores: list[float], temperature: float = LME_TEMPERATURE) -> float:
    """Log-Mean-Exp scoring (replaces Noisy-OR, Audit §4.1).

    Properties:
    - tau -> 0: converges to max(scores)
    - tau -> inf: converges to mean(scores)
    - At tau=0.3: strong edges dominate, weak edges contribute, no independence assumption
    - Output bounded by [min(scores), max(scores)] ⊂ [0, 1] when inputs in [0, 1]
    """
    if not scores:
        return 0.0

    # Numerically stable computation
    max_s = max(scores)
    if max_s <= 0:
        return 0.0

    inv_tau = 1.0 / temperature
    # Shift for numerical stability: log(mean(exp((s - max_s) / tau)))
    shifted = [math.exp((s - max_s) * inv_tau) for s in scores]
    mean_shifted = sum(shifted) / len(shifted)

    if mean_shifted <= 0:
        return 0.0

    result = max_s + temperature * math.log(mean_shifted)
    return max(0.0, min(1.0, result))


def _correlation_discount(num_nodes: int, num_edges: int) -> float:
    """Discount factor based on cluster density (Phase 4, §4.3).

    Dense clusters (every node connects to every other) → higher correlation
    → larger discount.  Sparse chains → lower correlation → less discount.

    Returns value in [0.5, 1.0].
    """
    if num_nodes < 2:
        return 1.0
    max_edges = num_nodes * (num_nodes - 1) / 2
    if max_edges == 0:
        return 1.0
    density = num_edges / max_edges
    return max(0.5, 1.0 - 0.5 * density)


class AccumulationGraph:
    """Manages affinity edges and detects clusters for multi-fragment snaps.

    Uses union-find for connected component detection (no recursive CTE,
    fixing Audit §5.3).  Cluster scoring uses Log-Mean-Exp instead of
    Noisy-OR (fixing Audit §4.1).
    """

    def __init__(
        self,
        provenance: ProvenanceLogger,
        notifier: Optional[RedisNotifier] = None,
    ):
        self._provenance = provenance
        self._notifier = notifier or RedisNotifier()

    async def add_or_update_edge(
        self,
        session: AsyncSession,
        tenant_id: str,
        fragment_a_id: UUID,
        fragment_b_id: UUID,
        affinity_score: float,
        failure_mode: str,
    ) -> Optional[UUID]:
        """Create or update an affinity edge between two fragments.

        Enforces MAX_EDGES_PER_FRAGMENT (INV-9): if the limit is reached,
        evicts the weakest edge before adding the new one.
        Score clamped to [0.0, 1.0] (INV-8).
        """
        affinity_score = max(0.0, min(1.0, affinity_score))

        # Canonical ordering to prevent duplicate edges
        a_id, b_id = sorted([fragment_a_id, fragment_b_id], key=str)

        # Check for existing edge (tenant-scoped, Audit §9.2)
        existing_stmt = (
            select(AccumulationEdgeORM)
            .where(
                AccumulationEdgeORM.tenant_id == tenant_id,
                AccumulationEdgeORM.fragment_a_id == a_id,
                AccumulationEdgeORM.fragment_b_id == b_id,
            )
        )
        result = await session.execute(existing_stmt)
        existing = result.scalar_one_or_none()

        if existing:
            # Update only if new score is higher (monotonic convergence, INV-4)
            if affinity_score > existing.affinity_score:
                existing.affinity_score = affinity_score
                existing.strongest_failure_mode = failure_mode
                existing.last_updated = datetime.now(timezone.utc)
            await session.flush()
            return existing.id

        # Enforce edge count limit (INV-9)
        await self._enforce_edge_limit(session, tenant_id, fragment_a_id)
        await self._enforce_edge_limit(session, tenant_id, fragment_b_id)

        edge_id = uuid4()
        edge = AccumulationEdgeORM(
            id=edge_id,
            tenant_id=tenant_id,
            fragment_a_id=a_id,
            fragment_b_id=b_id,
            affinity_score=affinity_score,
            strongest_failure_mode=failure_mode,
        )
        session.add(edge)
        await session.flush()
        return edge_id

    async def _enforce_edge_limit(
        self, session: AsyncSession, tenant_id: str, fragment_id: UUID,
    ) -> None:
        """Evict weakest edge if fragment exceeds MAX_EDGES_PER_FRAGMENT."""
        count_stmt = (
            select(func.count())
            .select_from(AccumulationEdgeORM)
            .where(
                AccumulationEdgeORM.tenant_id == tenant_id,
                (
                    (AccumulationEdgeORM.fragment_a_id == fragment_id)
                    | (AccumulationEdgeORM.fragment_b_id == fragment_id)
                ),
            )
        )
        count_result = await session.execute(count_stmt)
        count = count_result.scalar() or 0

        if count >= MAX_EDGES_PER_FRAGMENT:
            # Find and remove the weakest edge
            weakest_stmt = (
                select(AccumulationEdgeORM.id)
                .where(
                    AccumulationEdgeORM.tenant_id == tenant_id,
                    (
                        (AccumulationEdgeORM.fragment_a_id == fragment_id)
                        | (AccumulationEdgeORM.fragment_b_id == fragment_id)
                    ),
                )
                .order_by(AccumulationEdgeORM.affinity_score.asc())
                .limit(1)
            )
            weakest_result = await session.execute(weakest_stmt)
            weakest_id = weakest_result.scalar_one_or_none()
            if weakest_id:
                await session.execute(
                    delete(AccumulationEdgeORM)
                    .where(AccumulationEdgeORM.id == weakest_id)
                )

    async def detect_and_evaluate_clusters(
        self,
        session: AsyncSession,
        tenant_id: str,
        trigger_fragment_id: Optional[UUID] = None,
    ) -> list[dict]:
        """Detect connected components and evaluate for cluster snaps.

        Uses Python-side union-find (not recursive CTE, fixing Audit §5.3).
        Evaluates with LME scoring (not Noisy-OR, fixing Audit §4.1).
        Persists evaluation to ClusterSnapshot (fixing Audit §7.3).
        """
        # Load all edges for this tenant
        edge_stmt = (
            select(AccumulationEdgeORM)
            .where(AccumulationEdgeORM.tenant_id == tenant_id)
        )
        result = await session.execute(edge_stmt)
        edges = list(result.scalars().all())

        if not edges:
            return []

        # Union-Find for connected components
        parent: dict[UUID, UUID] = {}

        def find(x: UUID) -> UUID:
            while parent.get(x, x) != x:
                parent[x] = parent.get(parent[x], parent[x])
                x = parent[x]
            return x

        def union(x: UUID, y: UUID) -> None:
            rx, ry = find(x), find(y)
            if rx != ry:
                parent[rx] = ry

        # Build union-find from edges
        for edge in edges:
            parent.setdefault(edge.fragment_a_id, edge.fragment_a_id)
            parent.setdefault(edge.fragment_b_id, edge.fragment_b_id)
            union(edge.fragment_a_id, edge.fragment_b_id)

        # Group fragments by component root
        components: dict[UUID, set[UUID]] = {}
        for node_id in parent:
            root = find(node_id)
            components.setdefault(root, set()).add(node_id)

        # Evaluate clusters that meet minimum size
        snap_results = []
        for root, members in components.items():
            if len(members) < MIN_CLUSTER_SIZE:
                continue
            if len(members) > MAX_CLUSTER_SIZE:
                # Cap cluster size (INV-9) — take highest-affinity subgraph
                members = await self._prune_cluster(session, tenant_id, members, edges)

            # If trigger fragment is specified, only evaluate clusters containing it
            if trigger_fragment_id and trigger_fragment_id not in members:
                continue

            # Collect edge scores within this cluster
            member_set = set(members)
            cluster_edges = []
            cluster_scores = []
            for edge in edges:
                if edge.fragment_a_id in member_set and edge.fragment_b_id in member_set:
                    cluster_edges.append({
                        "a": str(edge.fragment_a_id),
                        "b": str(edge.fragment_b_id),
                        "score": edge.affinity_score,
                    })
                    cluster_scores.append(edge.affinity_score)

            if not cluster_scores:
                continue

            # LME scoring (replaces Noisy-OR)
            cluster_score = _log_mean_exp(cluster_scores)
            discount = _correlation_discount(len(member_set), len(cluster_edges))
            adjusted_score = max(0.0, min(1.0, cluster_score * discount))

            decision = "SNAP" if adjusted_score >= CLUSTER_SNAP_THRESHOLD else "NO_SNAP"

            # Persist evaluation (INV-10, Audit §7.3)
            evaluation = ClusterEvaluation(
                tenant_id=tenant_id,
                member_fragment_ids=list(member_set),
                edges=cluster_edges,
                cluster_score=cluster_score,
                correlation_discount=discount,
                adjusted_score=adjusted_score,
                threshold=CLUSTER_SNAP_THRESHOLD,
                decision=decision,
            )
            snapshot_id = await self._provenance.log_cluster_evaluation(session, evaluation)

            if decision == "SNAP":
                await self._notifier.notify_cluster_snap(
                    tenant_id, snapshot_id, len(member_set), adjusted_score,
                )

            snap_results.append({
                "snapshot_id": str(snapshot_id),
                "members": [str(m) for m in member_set],
                "member_count": len(member_set),
                "cluster_score": round(cluster_score, 4),
                "correlation_discount": round(discount, 4),
                "adjusted_score": round(adjusted_score, 4),
                "decision": decision,
            })

        await session.flush()
        return snap_results

    async def _prune_cluster(
        self,
        session: AsyncSession,
        tenant_id: str,
        members: set[UUID],
        all_edges: list[AccumulationEdgeORM],
    ) -> set[UUID]:
        """Prune oversized cluster to MAX_CLUSTER_SIZE by keeping strongest edges."""
        # Collect edges within cluster, sorted by score descending
        member_set = set(members)
        cluster_edges = [
            e for e in all_edges
            if e.fragment_a_id in member_set and e.fragment_b_id in member_set
        ]
        cluster_edges.sort(key=lambda e: e.affinity_score, reverse=True)

        # Rebuild cluster from strongest edges until size limit
        pruned: set[UUID] = set()
        for edge in cluster_edges:
            pruned.add(edge.fragment_a_id)
            pruned.add(edge.fragment_b_id)
            if len(pruned) >= MAX_CLUSTER_SIZE:
                break

        return pruned

    async def remove_fragment_edges(
        self,
        session: AsyncSession,
        tenant_id: str,
        fragment_id: UUID,
    ) -> int:
        """Remove all edges involving a fragment (used on expiration)."""
        stmt = (
            delete(AccumulationEdgeORM)
            .where(
                AccumulationEdgeORM.tenant_id == tenant_id,
                (
                    (AccumulationEdgeORM.fragment_a_id == fragment_id)
                    | (AccumulationEdgeORM.fragment_b_id == fragment_id)
                ),
            )
        )
        result = await session.execute(stmt)
        await session.flush()
        return result.rowcount or 0
