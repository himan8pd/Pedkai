"""
Incident Reconstruction — rebuilds incident timelines from fragment history.

Uses the provenance logs (fragment_history, snap_decision_record, cluster_snapshot)
to assemble a complete causal narrative for operator forensics.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.abeyance_orm import (
    AbeyanceFragmentORM,
    FragmentEntityRefORM,
    FragmentHistoryORM,
    SnapDecisionRecordORM,
    ClusterSnapshotORM,
)

logger = logging.getLogger(__name__)


class IncidentReconstructionService:
    """Reconstructs incident timelines from abeyance provenance data."""

    async def reconstruct(
        self,
        session: AsyncSession,
        tenant_id: str,
        hypothesis_id: Optional[UUID] = None,
        entity_identifier: Optional[str] = None,
        time_start: Optional[datetime] = None,
        time_end: Optional[datetime] = None,
    ) -> dict:
        """Assemble a time-ordered reconstruction of fragments and snaps.

        Can filter by hypothesis_id (for snap-based reconstruction),
        entity_identifier (for entity-based reconstruction), or time range.
        """
        # Find relevant fragments
        frag_stmt = select(AbeyanceFragmentORM).where(
            AbeyanceFragmentORM.tenant_id == tenant_id,
        )

        if hypothesis_id:
            frag_stmt = frag_stmt.where(
                AbeyanceFragmentORM.snapped_hypothesis_id == hypothesis_id,
            )

        if time_start:
            frag_stmt = frag_stmt.where(
                AbeyanceFragmentORM.event_timestamp >= time_start,
            )
        if time_end:
            frag_stmt = frag_stmt.where(
                AbeyanceFragmentORM.event_timestamp <= time_end,
            )

        frag_stmt = frag_stmt.order_by(AbeyanceFragmentORM.event_timestamp.asc()).limit(100)
        result = await session.execute(frag_stmt)
        fragments = list(result.scalars().all())

        # If filtering by entity, narrow to fragments referencing that entity
        if entity_identifier and not hypothesis_id:
            ref_stmt = (
                select(FragmentEntityRefORM.fragment_id)
                .where(
                    FragmentEntityRefORM.tenant_id == tenant_id,
                    FragmentEntityRefORM.entity_identifier == entity_identifier,
                )
            )
            ref_result = await session.execute(ref_stmt)
            entity_frag_ids = {row[0] for row in ref_result.fetchall()}
            fragments = [f for f in fragments if f.id in entity_frag_ids]

        if not fragments:
            return {"timeline": [], "fragments": [], "snaps": [], "clusters": []}

        fragment_ids = [f.id for f in fragments]

        # Get snap decisions involving these fragments
        snap_stmt = (
            select(SnapDecisionRecordORM)
            .where(
                SnapDecisionRecordORM.tenant_id == tenant_id,
                (
                    SnapDecisionRecordORM.new_fragment_id.in_(fragment_ids)
                    | SnapDecisionRecordORM.candidate_fragment_id.in_(fragment_ids)
                ),
            )
            .order_by(SnapDecisionRecordORM.evaluated_at.asc())
            .limit(200)
        )
        snap_result = await session.execute(snap_stmt)
        snap_decisions = list(snap_result.scalars().all())

        # Get fragment history
        history_stmt = (
            select(FragmentHistoryORM)
            .where(
                FragmentHistoryORM.tenant_id == tenant_id,
                FragmentHistoryORM.fragment_id.in_(fragment_ids),
            )
            .order_by(FragmentHistoryORM.event_timestamp.asc())
            .limit(500)
        )
        history_result = await session.execute(history_stmt)
        history_records = list(history_result.scalars().all())

        # Build timeline
        timeline = []

        for frag in fragments:
            timeline.append({
                "timestamp": frag.event_timestamp.isoformat() if frag.event_timestamp else None,
                "type": "FRAGMENT_INGESTED",
                "fragment_id": str(frag.id),
                "source_type": frag.source_type,
                "summary": (frag.raw_content or "")[:200],
                "entities": [e.get("identifier", "") for e in (frag.extracted_entities or [])[:5]],
                "status": frag.snap_status,
            })

        for snap in snap_decisions:
            if snap.decision in ("SNAP", "NEAR_MISS"):
                timeline.append({
                    "timestamp": snap.evaluated_at.isoformat() if snap.evaluated_at else None,
                    "type": f"SNAP_{snap.decision}",
                    "fragment_a": str(snap.new_fragment_id),
                    "fragment_b": str(snap.candidate_fragment_id),
                    "score": snap.final_score,
                    "failure_mode": snap.failure_mode_profile,
                    "threshold": snap.threshold_applied,
                })

        for hist in history_records:
            if hist.event_type in ("DECAY_UPDATE", "EXPIRED", "COLD_ARCHIVED"):
                timeline.append({
                    "timestamp": hist.event_timestamp.isoformat() if hist.event_timestamp else None,
                    "type": hist.event_type,
                    "fragment_id": str(hist.fragment_id),
                    "detail": hist.event_detail,
                })

        # Sort timeline by timestamp
        timeline.sort(key=lambda x: x.get("timestamp") or "")

        return {
            "tenant_id": tenant_id,
            "hypothesis_id": str(hypothesis_id) if hypothesis_id else None,
            "entity_identifier": entity_identifier,
            "fragment_count": len(fragments),
            "snap_decision_count": len(snap_decisions),
            "timeline": timeline,
        }
