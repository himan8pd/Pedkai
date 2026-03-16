"""
Causal Direction Testing — Layer 3, Mechanism #10 (LLD v3.0 §9.3).

Temporal ordering analysis to infer directional causality between entities.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.abeyance_v3_orm import (
    EntitySequenceLogORM,
    CausalCandidateORM,
    CausalEvidencePairORM,
    CausalAnalysisRunORM,
)

logger = logging.getLogger(__name__)

MIN_PAIRS_FOR_CANDIDATE = 5
DIRECTIONAL_FRACTION_THRESHOLD = 0.70
CONFIDENCE_THRESHOLD = 0.60


class CausalDirectionTester:
    """Infers causal direction between entities from temporal ordering."""

    async def run_analysis(
        self,
        session: AsyncSession,
        tenant_id: str,
    ) -> dict:
        """Analyze temporal co-occurrence for directional causality."""
        run = CausalAnalysisRunORM(
            id=uuid4(),
            tenant_id=tenant_id,
            started_at=datetime.now(timezone.utc),
        )
        session.add(run)

        # Load entity sequence logs
        stmt = (
            select(EntitySequenceLogORM)
            .where(EntitySequenceLogORM.tenant_id == tenant_id)
            .order_by(EntitySequenceLogORM.event_timestamp.asc())
            .limit(50000)
        )
        result = await session.execute(stmt)
        entries = list(result.scalars().all())

        if len(entries) < MIN_PAIRS_FOR_CANDIDATE:
            run.completed_at = datetime.now(timezone.utc)
            run.candidates_evaluated = 0
            run.candidates_promoted = 0
            await session.flush()
            return {"evaluated": 0, "promoted": 0}

        # Group by entity
        entity_events: dict[UUID, list[EntitySequenceLogORM]] = defaultdict(list)
        for e in entries:
            entity_events[e.entity_id].append(e)

        # Find co-occurring entity pairs (within 1h windows)
        entity_ids = list(entity_events.keys())
        candidates_evaluated = 0
        candidates_promoted = 0

        for i in range(len(entity_ids)):
            for j in range(i + 1, len(entity_ids)):
                e_a = entity_ids[i]
                e_b = entity_ids[j]

                pairs = self._find_temporal_pairs(
                    entity_events[e_a], entity_events[e_b],
                )

                if len(pairs) < MIN_PAIRS_FOR_CANDIDATE:
                    continue

                candidates_evaluated += 1

                # Compute directional fraction
                a_before_b = sum(1 for dt in pairs if dt > 0)
                b_before_a = sum(1 for dt in pairs if dt < 0)
                total = len(pairs)
                frac_ab = a_before_b / total
                frac_ba = b_before_a / total

                if max(frac_ab, frac_ba) < DIRECTIONAL_FRACTION_THRESHOLD:
                    continue

                direction = "A->B" if frac_ab > frac_ba else "B->A"
                directional_fraction = max(frac_ab, frac_ba)
                confidence = directional_fraction * min(1.0, total / 20)

                if confidence < CONFIDENCE_THRESHOLD:
                    continue

                candidate = CausalCandidateORM(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    entity_a_id=e_a,
                    entity_b_id=e_b,
                    direction=direction,
                    directional_fraction=round(directional_fraction, 4),
                    confidence=round(confidence, 4),
                    sample_count=total,
                )
                session.add(candidate)
                candidates_promoted += 1

                # Store evidence pairs (first 10)
                for dt_val, frag_a_id, frag_b_id in pairs[:10]:
                    if isinstance(dt_val, (int, float)):
                        ep = CausalEvidencePairORM(
                            id=uuid4(),
                            causal_candidate_id=candidate.id,
                            fragment_a_id=frag_a_id,
                            fragment_b_id=frag_b_id,
                            time_delta_seconds=dt_val,
                            direction="A->B" if dt_val > 0 else "B->A",
                        )
                        session.add(ep)

        run.completed_at = datetime.now(timezone.utc)
        run.candidates_evaluated = candidates_evaluated
        run.candidates_promoted = candidates_promoted

        await session.flush()
        logger.info(
            "Causal analysis: tenant=%s evaluated=%d promoted=%d",
            tenant_id, candidates_evaluated, candidates_promoted,
        )
        return {"evaluated": candidates_evaluated, "promoted": candidates_promoted}

    @staticmethod
    def _find_temporal_pairs(
        events_a: list[EntitySequenceLogORM],
        events_b: list[EntitySequenceLogORM],
        window_seconds: float = 3600.0,
    ) -> list[tuple[float, UUID, UUID]]:
        """Find temporally proximate event pairs. Returns (delta_seconds, frag_a, frag_b)."""
        pairs = []
        j = 0
        for ea in events_a:
            while j < len(events_b) and events_b[j].event_timestamp < ea.event_timestamp:
                dt = (ea.event_timestamp - events_b[j].event_timestamp).total_seconds()
                if abs(dt) <= window_seconds:
                    pairs.append((-dt, ea.fragment_id, events_b[j].fragment_id))
                j += 1
            # Check forward
            for k in range(j, min(j + 10, len(events_b))):
                dt = (events_b[k].event_timestamp - ea.event_timestamp).total_seconds()
                if abs(dt) <= window_seconds:
                    pairs.append((dt, ea.fragment_id, events_b[k].fragment_id))
                elif dt > window_seconds:
                    break
        return pairs
