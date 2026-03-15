"""
Maintenance — bounded background jobs for Abeyance Memory.

Phase 5 implementation:
- Bounded batch sizes per job
- Scheduled intervals with resource caps
- Orphan cleanup and consistency checks
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from uuid import UUID

from sqlalchemy import select, delete, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.abeyance_orm import (
    AbeyanceFragmentORM,
    AccumulationEdgeORM,
    FragmentEntityRefORM,
    FragmentHistoryORM,
)
from backend.app.services.abeyance.decay_engine import DecayEngine
from backend.app.services.abeyance.accumulation_graph import AccumulationGraph
from backend.app.services.abeyance.events import ProvenanceLogger, FragmentStateChange

logger = logging.getLogger(__name__)

# Batch size limits (Phase 5)
MAX_DECAY_BATCH = 10_000
MAX_ARCHIVE_BATCH = 5_000
MAX_PRUNE_BATCH = 10_000
STALE_EDGE_THRESHOLD = 0.2


class MaintenanceService:
    """Bounded background maintenance jobs for the abeyance subsystem."""

    def __init__(
        self,
        decay_engine: DecayEngine,
        accumulation_graph: AccumulationGraph,
        provenance: ProvenanceLogger,
    ):
        self._decay = decay_engine
        self._accum = accumulation_graph
        self._provenance = provenance

    async def run_decay_pass(
        self, session: AsyncSession, tenant_id: str
    ) -> dict:
        """Execute bounded decay pass. Max MAX_DECAY_BATCH fragments."""
        updated, expired = await self._decay.run_decay_pass(
            session, tenant_id, batch_size=MAX_DECAY_BATCH,
        )
        return {"updated": updated, "expired": expired}

    async def prune_stale_edges(
        self, session: AsyncSession, tenant_id: str
    ) -> int:
        """Remove accumulation edges where both fragments have low decay scores."""
        # Find edges where both fragments are below threshold
        edge_stmt = (
            select(AccumulationEdgeORM)
            .where(AccumulationEdgeORM.tenant_id == tenant_id)
            .limit(MAX_PRUNE_BATCH)
        )
        result = await session.execute(edge_stmt)
        edges = list(result.scalars().all())

        removed = 0
        for edge in edges:
            # Check both fragments
            frag_a_stmt = (
                select(AbeyanceFragmentORM.current_decay_score, AbeyanceFragmentORM.snap_status)
                .where(
                    AbeyanceFragmentORM.id == edge.fragment_a_id,
                    AbeyanceFragmentORM.tenant_id == tenant_id,
                )
            )
            frag_b_stmt = (
                select(AbeyanceFragmentORM.current_decay_score, AbeyanceFragmentORM.snap_status)
                .where(
                    AbeyanceFragmentORM.id == edge.fragment_b_id,
                    AbeyanceFragmentORM.tenant_id == tenant_id,
                )
            )

            a_result = await session.execute(frag_a_stmt)
            b_result = await session.execute(frag_b_stmt)
            a_row = a_result.fetchone()
            b_row = b_result.fetchone()

            should_remove = False
            if not a_row or not b_row:
                should_remove = True  # Orphaned edge
            elif a_row[1] in ("EXPIRED", "COLD") or b_row[1] in ("EXPIRED", "COLD"):
                should_remove = True
            elif a_row[0] < STALE_EDGE_THRESHOLD and b_row[0] < STALE_EDGE_THRESHOLD:
                should_remove = True

            if should_remove:
                await session.delete(edge)
                removed += 1

        await session.flush()
        logger.info("Pruned %d stale edges for tenant %s", removed, tenant_id)
        return removed

    async def expire_stale_fragments(
        self, session: AsyncSession, tenant_id: str
    ) -> int:
        """Transition STALE fragments to EXPIRED. Max MAX_PRUNE_BATCH."""
        stmt = (
            select(AbeyanceFragmentORM)
            .where(
                AbeyanceFragmentORM.tenant_id == tenant_id,
                AbeyanceFragmentORM.snap_status == "STALE",
            )
            .limit(MAX_PRUNE_BATCH)
        )
        result = await session.execute(stmt)
        fragments = list(result.scalars().all())

        expired = 0
        for frag in fragments:
            frag.snap_status = "EXPIRED"
            frag.updated_at = datetime.now(timezone.utc)

            await self._provenance.log_state_change(
                session,
                FragmentStateChange(
                    fragment_id=frag.id,
                    tenant_id=tenant_id,
                    event_type="EXPIRED",
                    old_state={"status": "STALE"},
                    new_state={"status": "EXPIRED"},
                ),
            )

            # Remove accumulation edges
            await self._accum.remove_fragment_edges(session, tenant_id, frag.id)
            expired += 1

        await session.flush()
        logger.info("Expired %d stale fragments for tenant %s", expired, tenant_id)
        return expired

    async def cleanup_orphaned_entity_refs(
        self, session: AsyncSession, tenant_id: str
    ) -> int:
        """Remove entity refs pointing to non-existent fragments."""
        # Find orphaned refs
        orphan_stmt = (
            select(FragmentEntityRefORM.id)
            .where(
                FragmentEntityRefORM.tenant_id == tenant_id,
                ~FragmentEntityRefORM.fragment_id.in_(
                    select(AbeyanceFragmentORM.id)
                    .where(AbeyanceFragmentORM.tenant_id == tenant_id)
                ),
            )
            .limit(MAX_PRUNE_BATCH)
        )
        result = await session.execute(orphan_stmt)
        orphan_ids = [row[0] for row in result.fetchall()]

        if orphan_ids:
            await session.execute(
                delete(FragmentEntityRefORM)
                .where(FragmentEntityRefORM.id.in_(orphan_ids))
            )
            await session.flush()

        logger.info("Cleaned up %d orphaned entity refs for tenant %s", len(orphan_ids), tenant_id)
        return len(orphan_ids)

    async def run_full_maintenance(
        self, session: AsyncSession, tenant_id: str
    ) -> dict:
        """Execute all maintenance tasks in sequence."""
        results = {}
        results["decay"] = await self.run_decay_pass(session, tenant_id)
        results["stale_edges_pruned"] = await self.prune_stale_edges(session, tenant_id)
        results["fragments_expired"] = await self.expire_stale_fragments(session, tenant_id)
        results["orphans_cleaned"] = await self.cleanup_orphaned_entity_refs(session, tenant_id)
        return results
