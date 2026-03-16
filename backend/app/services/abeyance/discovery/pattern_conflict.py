"""
Pattern Conflict Detection — Layer 2, Mechanism #6 (LLD v3.0 §8.2).

Detects contradictory snap decisions on overlapping entity sets
with opposite polarities.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
from uuid import UUID, uuid4
import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.abeyance_orm import (
    SnapDecisionRecordORM,
    AbeyanceFragmentORM,
    FragmentEntityRefORM,
)
from backend.app.models.abeyance_v3_orm import (
    ConflictRecordORM,
    ConflictDetectionLogORM,
)

logger = logging.getLogger(__name__)

OVERLAP_THRESHOLD = 0.3
SCAN_WINDOW_DAYS = 7
MAX_DECISIONS_PER_SCAN = 500


class PatternConflictDetector:
    """Detects contradictory snap decisions."""

    async def scan(
        self,
        session: AsyncSession,
        tenant_id: str,
        scan_type: str = "SCHEDULED",
    ) -> list[ConflictRecordORM]:
        """Scan recent snap decisions for conflicts."""
        start_time = time.monotonic()
        lookback = datetime.now(timezone.utc) - timedelta(days=SCAN_WINDOW_DAYS)

        # Get recent SNAP/NEAR_MISS decisions
        stmt = (
            select(SnapDecisionRecordORM)
            .where(
                SnapDecisionRecordORM.tenant_id == tenant_id,
                SnapDecisionRecordORM.evaluated_at >= lookback,
                SnapDecisionRecordORM.decision.in_(["SNAP", "NEAR_MISS"]),
            )
            .order_by(SnapDecisionRecordORM.evaluated_at.desc())
            .limit(MAX_DECISIONS_PER_SCAN)
        )
        result = await session.execute(stmt)
        decisions = list(result.scalars().all())

        if len(decisions) < 2:
            return []

        # Load fragment entities and polarities
        frag_entities: dict[UUID, set[str]] = {}
        frag_polarities: dict[UUID, str] = {}
        frag_ids = set()
        for d in decisions:
            frag_ids.add(d.new_fragment_id)
            frag_ids.add(d.candidate_fragment_id)

        # Batch load entities
        entity_stmt = (
            select(FragmentEntityRefORM.fragment_id, FragmentEntityRefORM.entity_identifier)
            .where(
                FragmentEntityRefORM.tenant_id == tenant_id,
                FragmentEntityRefORM.fragment_id.in_(list(frag_ids)),
            )
        )
        entity_result = await session.execute(entity_stmt)
        for row in entity_result.fetchall():
            frag_entities.setdefault(row[0], set()).add(row[1])

        # Batch load polarities
        polarity_stmt = (
            select(AbeyanceFragmentORM.id, AbeyanceFragmentORM.polarity)
            .where(
                AbeyanceFragmentORM.tenant_id == tenant_id,
                AbeyanceFragmentORM.id.in_(list(frag_ids)),
            )
        )
        pol_result = await session.execute(polarity_stmt)
        for row in pol_result.fetchall():
            if row[1]:
                frag_polarities[row[0]] = row[1]

        # Pairwise conflict detection
        conflicts = []
        for i in range(len(decisions)):
            for j in range(i + 1, len(decisions)):
                d_a = decisions[i]
                d_b = decisions[j]

                # Entity overlap
                entities_a = frag_entities.get(d_a.new_fragment_id, set()) | frag_entities.get(d_a.candidate_fragment_id, set())
                entities_b = frag_entities.get(d_b.new_fragment_id, set()) | frag_entities.get(d_b.candidate_fragment_id, set())

                union = len(entities_a | entities_b)
                if union == 0:
                    continue
                overlap = len(entities_a & entities_b) / union

                if overlap < OVERLAP_THRESHOLD:
                    continue

                # Polarity check
                pol_a = frag_polarities.get(d_a.new_fragment_id, "NEUTRAL")
                pol_b = frag_polarities.get(d_b.new_fragment_id, "NEUTRAL")

                if pol_a == pol_b or pol_a == "NEUTRAL" or pol_b == "NEUTRAL":
                    continue

                conflict = ConflictRecordORM(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    decision_id_a=d_a.id,
                    decision_id_b=d_b.id,
                    entity_overlap_ratio=round(overlap, 4),
                    polarity_a=pol_a,
                    polarity_b=pol_b,
                )
                session.add(conflict)
                conflicts.append(conflict)

        duration_ms = int((time.monotonic() - start_time) * 1000)

        log_entry = ConflictDetectionLogORM(
            id=uuid4(),
            tenant_id=tenant_id,
            scan_type=scan_type,
            decisions_scanned=len(decisions),
            conflicts_found=len(conflicts),
            duration_ms=duration_ms,
        )
        session.add(log_entry)

        await session.flush()
        logger.info(
            "Conflict scan: tenant=%s scanned=%d conflicts=%d duration=%dms",
            tenant_id, len(decisions), len(conflicts), duration_ms,
        )
        return conflicts
