"""
Bridge Detection — Layer 2, Mechanism #4 (LLD v3.0 §7.4).

Detects fragments with high betweenness centrality across domain boundaries
in the accumulation graph, indicating hidden infrastructure relationships.
"""

from __future__ import annotations

import hashlib
import logging
import random
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.abeyance_orm import (
    AbeyanceFragmentORM,
    AccumulationEdgeORM,
    FragmentEntityRefORM,
)
from backend.app.models.abeyance_v3_orm import (
    BridgeDiscoveryORM,
    BridgeDiscoveryProvenanceORM,
)

logger = logging.getLogger(__name__)

MIN_BETWEENNESS = 0.3
MIN_DOMAIN_SPAN = 2
MAX_FRAGMENTS_TO_SCAN = 2000
SAMPLED_BRIDGE_SCAN_SIZE = 2000


class BridgeDetector:
    """Identifies bridge fragments connecting distinct topology domains."""

    async def detect_bridges(
        self,
        session: AsyncSession,
        tenant_id: str,
    ) -> list[BridgeDiscoveryORM]:
        """Scan accumulation graph for bridge fragments."""
        # Load edges
        edge_stmt = (
            select(AccumulationEdgeORM)
            .where(AccumulationEdgeORM.tenant_id == tenant_id)
        )
        result = await session.execute(edge_stmt)
        edges = list(result.scalars().all())

        if not edges:
            return []

        # Build adjacency list
        adj: dict[UUID, set[UUID]] = defaultdict(set)
        for e in edges:
            adj[e.fragment_a_id].add(e.fragment_b_id)
            adj[e.fragment_b_id].add(e.fragment_a_id)

        all_nodes = set(adj.keys())
        sampled = False
        if len(all_nodes) > MAX_FRAGMENTS_TO_SCAN:
            logger.warning(
                "Bridge detection: graph too large for full scan "
                "(tenant=%s nodes=%d limit=%d), running sampled analysis",
                tenant_id, len(all_nodes), MAX_FRAGMENTS_TO_SCAN,
            )
            sampled_nodes = set(random.sample(sorted(all_nodes), SAMPLED_BRIDGE_SCAN_SIZE))
            # Rebuild adjacency restricted to sampled nodes
            sampled_adj: dict[UUID, set[UUID]] = defaultdict(set)
            for node in sampled_nodes:
                for neighbor in adj[node]:
                    if neighbor in sampled_nodes:
                        sampled_adj[node].add(neighbor)
            adj = sampled_adj
            all_nodes = sampled_nodes
            sampled = True

        # Compute approximate betweenness centrality (Brandes simplified)
        betweenness = self._brandes_betweenness(adj, all_nodes)

        # Get entity domains for each fragment
        domain_map = await self._get_fragment_domains(session, tenant_id, all_nodes)

        discoveries = []
        for node, bc in betweenness.items():
            if bc < MIN_BETWEENNESS:
                continue

            # Count distinct domains of neighbors
            neighbor_domains = set()
            for neighbor in adj[node]:
                neighbor_domains.update(domain_map.get(neighbor, set()))
            own_domains = domain_map.get(node, set())
            all_domains = neighbor_domains | own_domains
            domain_span = len(all_domains)

            if domain_span < MIN_DOMAIN_SPAN:
                continue

            # Component fingerprint for dedup
            component_ids = sorted(str(n) for n in adj[node])
            component_ids.append(str(node))
            fingerprint = hashlib.sha256("|".join(sorted(component_ids)).encode()).hexdigest()[:64]

            severity = "HIGH" if bc >= 0.6 else "MEDIUM" if bc >= 0.4 else "LOW"

            discovery = BridgeDiscoveryORM(
                id=uuid4(),
                tenant_id=tenant_id,
                fragment_id=node,
                betweenness_centrality=round(bc, 4),
                domain_span=domain_span,
                severity=severity,
                component_fingerprint=fingerprint,
            )
            session.add(discovery)

            # Provenance: record sub-component
            prov = BridgeDiscoveryProvenanceORM(
                id=uuid4(),
                bridge_discovery_id=discovery.id,
                sub_component_fragment_ids=[str(n) for n in adj[node]],
            )
            session.add(prov)
            discoveries.append(discovery)

        await session.flush()
        scan_type = "sampled" if sampled else "full"
        logger.info(
            "Bridge detection: tenant=%s found=%d scan=%s nodes=%d",
            tenant_id, len(discoveries), scan_type, len(all_nodes),
        )
        return discoveries

    @staticmethod
    def _brandes_betweenness(
        adj: dict[UUID, set[UUID]], nodes: set[UUID],
    ) -> dict[UUID, float]:
        """Brandes algorithm for betweenness centrality (unnormalized)."""
        bc: dict[UUID, float] = {n: 0.0 for n in nodes}

        for s in nodes:
            stack = []
            pred: dict[UUID, list[UUID]] = {n: [] for n in nodes}
            sigma: dict[UUID, float] = {n: 0.0 for n in nodes}
            sigma[s] = 1.0
            dist: dict[UUID, int] = {n: -1 for n in nodes}
            dist[s] = 0

            queue = [s]
            while queue:
                v = queue.pop(0)
                stack.append(v)
                for w in adj.get(v, set()):
                    if dist[w] < 0:
                        queue.append(w)
                        dist[w] = dist[v] + 1
                    if dist[w] == dist[v] + 1:
                        sigma[w] += sigma[v]
                        pred[w].append(v)

            delta: dict[UUID, float] = {n: 0.0 for n in nodes}
            while stack:
                w = stack.pop()
                for v in pred[w]:
                    delta[v] += (sigma[v] / max(sigma[w], 1e-10)) * (1.0 + delta[w])
                if w != s:
                    bc[w] += delta[w]

        # Normalize
        n = len(nodes)
        if n > 2:
            norm = 1.0 / ((n - 1) * (n - 2))
            for node in bc:
                bc[node] *= norm

        return bc

    async def _get_fragment_domains(
        self, session: AsyncSession, tenant_id: str, fragment_ids: set[UUID],
    ) -> dict[UUID, set[str]]:
        """Get entity domains for each fragment."""
        stmt = (
            select(FragmentEntityRefORM.fragment_id, FragmentEntityRefORM.entity_domain)
            .where(
                FragmentEntityRefORM.tenant_id == tenant_id,
                FragmentEntityRefORM.fragment_id.in_(list(fragment_ids)),
            )
        )
        result = await session.execute(stmt)
        domain_map: dict[UUID, set[str]] = defaultdict(set)
        for row in result.fetchall():
            if row[1]:
                domain_map[row[0]].add(row[1])
        return domain_map
