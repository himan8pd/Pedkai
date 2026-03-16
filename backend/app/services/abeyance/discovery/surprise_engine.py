"""
Surprise Engine — Layer 2, Mechanism #1 (LLD v3.0 §7.1).

Detects statistically anomalous snap decisions by maintaining per-failure-mode
score histograms and computing surprise via -log(P(x)).
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.abeyance_orm import SnapDecisionRecordORM
from backend.app.models.abeyance_v3_orm import (
    SurpriseEventORM,
    SurpriseDistributionStateORM,
)

logger = logging.getLogger(__name__)

NUM_BINS = 20
ALPHA_EMA = 0.01
INITIAL_THRESHOLD = 6.64  # -log(1/768), approx top-0.13% baseline


class SurpriseEngine:
    """Maintains score histograms and flags statistically surprising snaps."""

    async def process_snap_decision(
        self,
        session: AsyncSession,
        tenant_id: str,
        sdr: SnapDecisionRecordORM,
    ) -> Optional[SurpriseEventORM]:
        """Check if a snap decision is surprising. Returns event or None."""
        profile = sdr.failure_mode_profile
        score = sdr.final_score

        # Load or initialise distribution state
        state = await self._get_or_create_state(session, tenant_id, profile)
        bins = state.histogram_bins

        # Compute surprise = -log(P(score))
        bin_idx = min(int(score * NUM_BINS), NUM_BINS - 1)
        bin_prob = bins[bin_idx] if bin_idx < len(bins) else 1.0 / NUM_BINS
        surprise = -math.log(max(bin_prob, 1e-10))

        # Update histogram via EMA
        for i in range(len(bins)):
            bins[i] = (1.0 - ALPHA_EMA) * bins[i]
        bins[bin_idx] += ALPHA_EMA
        # Renormalise
        total = sum(bins)
        if total > 0:
            for i in range(len(bins)):
                bins[i] /= total

        state.histogram_bins = bins
        state.observation_count += 1
        state.last_updated_at = datetime.now(timezone.utc)

        # Decide escalation
        event = None
        if surprise >= state.threshold_value:
            # Determine contributing dimensions from per-dim scores
            contributing = self._contributing_dimensions(sdr)

            escalation = "TIER_1_ALERT" if surprise >= state.threshold_value * 1.5 else "TIER_2_REVIEW"
            event = SurpriseEventORM(
                id=uuid4(),
                tenant_id=tenant_id,
                snap_decision_record_id=sdr.id,
                failure_mode_profile=profile,
                surprise_value=round(surprise, 4),
                threshold_at_time=state.threshold_value,
                escalation_type=escalation,
                dimensions_contributing=contributing,
                bin_index=bin_idx,
                bin_probability=round(bin_prob, 6),
            )
            session.add(event)
            logger.info(
                "Surprise event: tenant=%s profile=%s surprise=%.4f threshold=%.4f",
                tenant_id, profile, surprise, state.threshold_value,
            )
        else:
            # Adaptive threshold: decrease monotonically if no surprises
            state.threshold_monotonic_decrease_count += 1
            if state.threshold_monotonic_decrease_count >= 100:
                state.threshold_value = max(
                    3.0, state.threshold_value * 0.95
                )
                state.threshold_monotonic_decrease_count = 0

        await session.flush()
        return event

    @staticmethod
    def _contributing_dimensions(sdr: SnapDecisionRecordORM) -> dict:
        """Identify which dimensions contributed most to the surprise."""
        dims = {}
        for attr in ["score_semantic", "score_topological", "score_temporal",
                      "score_operational", "score_entity_overlap"]:
            val = getattr(sdr, attr, None)
            if val is not None:
                dims[attr.replace("score_", "")] = round(val, 4)
        return dims

    async def _get_or_create_state(
        self, session: AsyncSession, tenant_id: str, profile: str,
    ) -> SurpriseDistributionStateORM:
        stmt = select(SurpriseDistributionStateORM).where(
            SurpriseDistributionStateORM.tenant_id == tenant_id,
            SurpriseDistributionStateORM.failure_mode_profile == profile,
        )
        result = await session.execute(stmt)
        state = result.scalar_one_or_none()
        if state is None:
            uniform = [1.0 / NUM_BINS] * NUM_BINS
            state = SurpriseDistributionStateORM(
                tenant_id=tenant_id,
                failure_mode_profile=profile,
                histogram_bins=uniform,
                observation_count=0.0,
                threshold_value=INITIAL_THRESHOLD,
            )
            session.add(state)
            await session.flush()
        return state
