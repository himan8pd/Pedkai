"""
Counterfactual Simulation — Layer 4, Mechanism #12 (LLD v3.0 §10.2).

Replays snap decisions with individual fragments removed to measure
causal impact (decision flip rate).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.abeyance_orm import (
    AbeyanceFragmentORM,
    SnapDecisionRecordORM,
    FragmentEntityRefORM,
)
from backend.app.models.abeyance_v3_orm import (
    CounterfactualSimulationResultORM,
    CounterfactualPairDeltaORM,
    CounterfactualCandidateQueueORM,
    CounterfactualJobRunORM,
)
from backend.app.services.abeyance.snap_engine_v3 import (
    SnapEngineV3,
    _clamp,
    _cosine_similarity,
    _jaccard,
    _sidak_threshold,
    WEIGHT_PROFILES_V3,
    BASE_SNAP_THRESHOLD,
)

logger = logging.getLogger(__name__)

MAX_PAIRS_PER_CANDIDATE = 50
IMPACT_THRESHOLD = 0.3


class CounterfactualSimulator:
    """Replays snap decisions with fragments removed to measure causal impact."""

    def __init__(self, snap_engine: SnapEngineV3):
        self._snap = snap_engine

    async def enqueue_candidate(
        self,
        session: AsyncSession,
        tenant_id: str,
        fragment_id: UUID,
        priority: float = 0.0,
    ) -> CounterfactualCandidateQueueORM:
        """Enqueue a fragment for counterfactual analysis."""
        item = CounterfactualCandidateQueueORM(
            id=uuid4(),
            tenant_id=tenant_id,
            fragment_id=fragment_id,
            priority_score=priority,
            status="PENDING",
        )
        session.add(item)
        await session.flush()
        return item

    async def run_batch(
        self,
        session: AsyncSession,
        tenant_id: str,
        batch_size: int = 10,
    ) -> dict:
        """Process a batch of queued candidates."""
        job = CounterfactualJobRunORM(
            id=uuid4(),
            tenant_id=tenant_id,
            started_at=datetime.now(timezone.utc),
        )
        session.add(job)

        # Get pending candidates
        stmt = (
            select(CounterfactualCandidateQueueORM)
            .where(
                CounterfactualCandidateQueueORM.tenant_id == tenant_id,
                CounterfactualCandidateQueueORM.status == "PENDING",
            )
            .order_by(CounterfactualCandidateQueueORM.priority_score.desc())
            .limit(batch_size)
        )
        result = await session.execute(stmt)
        candidates = list(result.scalars().all())

        total_pairs = 0
        for candidate in candidates:
            pairs = await self._simulate_removal(
                session, tenant_id, candidate.fragment_id,
            )
            total_pairs += pairs
            candidate.status = "PROCESSED"

        job.completed_at = datetime.now(timezone.utc)
        job.candidates_processed = len(candidates)
        job.total_pairs_replayed = total_pairs

        await session.flush()
        return {
            "candidates_processed": len(candidates),
            "total_pairs_replayed": total_pairs,
        }

    async def _simulate_removal(
        self,
        session: AsyncSession,
        tenant_id: str,
        fragment_id: UUID,
    ) -> int:
        """Simulate removing a fragment and measure decision changes."""
        # Get all snap decisions involving this fragment
        stmt = (
            select(SnapDecisionRecordORM)
            .where(
                SnapDecisionRecordORM.tenant_id == tenant_id,
                (
                    (SnapDecisionRecordORM.new_fragment_id == fragment_id)
                    | (SnapDecisionRecordORM.candidate_fragment_id == fragment_id)
                ),
                SnapDecisionRecordORM.decision.in_(["SNAP", "NEAR_MISS"]),
            )
            .limit(MAX_PAIRS_PER_CANDIDATE)
        )
        result = await session.execute(stmt)
        decisions = list(result.scalars().all())

        if not decisions:
            return 0

        flip_count = 0
        deltas = []

        for d in decisions:
            # Counterfactual: zero out the contribution of this fragment
            original_score = d.final_score
            # Approximate counterfactual by removing entity overlap contribution
            weights = d.weights_used or {}
            entity_weight = weights.get("w_ent", 0.25)
            entity_score = getattr(d, "score_entity_overlap", 0.0) or 0.0

            # Counterfactual score: remove entity overlap contribution
            counterfactual_score = max(0.0, original_score - entity_weight * entity_score * d.temporal_modifier)
            delta = original_score - counterfactual_score

            # Would the decision change?
            k = d.multiple_comparisons_k or 1
            threshold = _sidak_threshold(BASE_SNAP_THRESHOLD, k)
            original_decision = d.decision
            cf_decision = "SNAP" if counterfactual_score >= threshold else "NONE"
            changed = (original_decision in ("SNAP", "NEAR_MISS")) and cf_decision == "NONE"

            if changed:
                flip_count += 1

            pair_delta = CounterfactualPairDeltaORM(
                id=uuid4(),
                simulation_result_id=uuid4(),  # Placeholder, will be updated
                original_score=round(original_score, 6),
                counterfactual_score=round(counterfactual_score, 6),
                delta=round(delta, 6),
                decision_changed=changed,
            )
            deltas.append(pair_delta)

        # Compute causal impact
        flip_rate = flip_count / max(len(decisions), 1)
        causal_impact = flip_rate

        sim_result = CounterfactualSimulationResultORM(
            id=uuid4(),
            tenant_id=tenant_id,
            candidate_fragment_id=fragment_id,
            causal_impact_score=round(causal_impact, 4),
            decision_flip_count=flip_count,
            decision_flip_rate=round(flip_rate, 4),
            pairs_evaluated=len(decisions),
        )
        session.add(sim_result)

        # Link deltas to result
        for pd in deltas:
            pd.simulation_result_id = sim_result.id
            session.add(pd)

        await session.flush()
        logger.info(
            "Counterfactual: tenant=%s fragment=%s impact=%.4f flips=%d/%d",
            tenant_id, fragment_id, causal_impact, flip_count, len(decisions),
        )
        return len(decisions)
