"""
Outcome Calibration — Layer 2, Mechanism #5 (LLD v3.0 §8.1).

Feedback Loop A: operator verdict → weight recalibration.
Ingests snap outcome feedback, computes optimal weights per failure mode,
and writes calibrated profiles for SnapEngineV3 consumption.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.abeyance_orm import SnapDecisionRecordORM
from backend.app.models.abeyance_v3_orm import (
    SnapOutcomeFeedbackORM,
    CalibrationHistoryORM,
    WeightProfileActiveORM,
)
from backend.app.services.abeyance.snap_engine_v3 import WEIGHT_PROFILES_V3

logger = logging.getLogger(__name__)

MIN_SAMPLES_FOR_CALIBRATION = 20
LEARNING_RATE = 0.1
MAX_WEIGHT_SHIFT = 0.15


class OutcomeCalibrationService:
    """Calibrates snap engine weights from operator feedback."""

    async def record_feedback(
        self,
        session: AsyncSession,
        tenant_id: str,
        snap_decision_record_id: UUID,
        operator_verdict: str,
        resolution_action: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> SnapOutcomeFeedbackORM:
        """Record operator verdict on a snap decision."""
        feedback = SnapOutcomeFeedbackORM(
            id=uuid4(),
            tenant_id=tenant_id,
            snap_decision_record_id=snap_decision_record_id,
            operator_verdict=operator_verdict,
            resolution_action=resolution_action,
            notes=notes,
        )
        session.add(feedback)
        await session.flush()
        return feedback

    async def calibrate(
        self,
        session: AsyncSession,
        tenant_id: str,
        failure_mode_profile: str,
    ) -> Optional[dict]:
        """Recalibrate weights for a failure mode using collected feedback."""
        # Get all feedback-annotated decisions for this profile
        stmt = (
            select(SnapDecisionRecordORM, SnapOutcomeFeedbackORM)
            .join(
                SnapOutcomeFeedbackORM,
                SnapOutcomeFeedbackORM.snap_decision_record_id == SnapDecisionRecordORM.id,
            )
            .where(
                SnapDecisionRecordORM.tenant_id == tenant_id,
                SnapDecisionRecordORM.failure_mode_profile == failure_mode_profile,
            )
        )
        result = await session.execute(stmt)
        pairs = list(result.all())

        if len(pairs) < MIN_SAMPLES_FOR_CALIBRATION:
            logger.info(
                "Insufficient samples for calibration: %d < %d (tenant=%s profile=%s)",
                len(pairs), MIN_SAMPLES_FOR_CALIBRATION, tenant_id, failure_mode_profile,
            )
            return None

        # Get current weights
        current = await self._get_active_weights(session, tenant_id, failure_mode_profile)
        base_weights = WEIGHT_PROFILES_V3.get(failure_mode_profile, WEIGHT_PROFILES_V3["DARK_EDGE"])
        weights_before = dict(current or base_weights)

        # Gradient step: increase weights for dimensions that correlate with TP
        dim_keys = ["w_sem", "w_topo", "w_temp", "w_oper", "w_ent"]
        dim_score_attrs = ["score_semantic", "score_topological", "score_temporal",
                           "score_operational", "score_entity_overlap"]

        gradients = {k: 0.0 for k in dim_keys}
        tp_count = 0
        fp_count = 0

        for sdr, feedback in pairs:
            is_tp = feedback.operator_verdict in ("TRUE_POSITIVE", "CONFIRMED")
            label = 1.0 if is_tp else -1.0
            if is_tp:
                tp_count += 1
            else:
                fp_count += 1

            for key, attr in zip(dim_keys, dim_score_attrs):
                score = getattr(sdr, attr, None)
                if score is not None:
                    gradients[key] += label * score

        # Normalize gradients
        n = len(pairs)
        for key in gradients:
            gradients[key] /= n

        # Apply bounded gradient step
        new_weights = dict(weights_before)
        for key in dim_keys:
            shift = LEARNING_RATE * gradients[key]
            shift = max(-MAX_WEIGHT_SHIFT, min(MAX_WEIGHT_SHIFT, shift))
            new_weights[key] = max(0.01, new_weights[key] + shift)

        # Renormalize to sum to 1.0
        total = sum(new_weights[k] for k in dim_keys)
        for k in dim_keys:
            new_weights[k] = round(new_weights[k] / total, 4)

        # Compute AUC proxy (TP rate)
        auc_before = tp_count / max(n, 1)
        auc_after = auc_before  # Will be measured on next cycle

        # Persist calibration history
        history = CalibrationHistoryORM(
            id=uuid4(),
            tenant_id=tenant_id,
            failure_mode_profile=failure_mode_profile,
            weights_before=weights_before,
            weights_after=new_weights,
            auc_before=round(auc_before, 4),
            sample_count=n,
        )
        session.add(history)

        # Update active profile
        active = await self._get_or_create_active(session, tenant_id, failure_mode_profile)
        active.weights = new_weights
        active.calibration_status = "CALIBRATED"
        active.last_calibrated_at = datetime.now(timezone.utc)

        await session.flush()
        logger.info(
            "Calibrated %s for tenant=%s: %d samples, TP=%d FP=%d",
            failure_mode_profile, tenant_id, n, tp_count, fp_count,
        )
        return new_weights

    async def get_all_calibrated_weights(
        self, session: AsyncSession, tenant_id: str,
    ) -> dict[str, dict[str, float]]:
        """Return all calibrated weight profiles for a tenant (Loop A output)."""
        stmt = (
            select(WeightProfileActiveORM)
            .where(WeightProfileActiveORM.tenant_id == tenant_id)
        )
        result = await session.execute(stmt)
        profiles = list(result.scalars().all())
        return {p.failure_mode_profile: p.weights for p in profiles}

    async def _get_active_weights(
        self, session: AsyncSession, tenant_id: str, profile: str,
    ) -> Optional[dict]:
        stmt = select(WeightProfileActiveORM).where(
            WeightProfileActiveORM.tenant_id == tenant_id,
            WeightProfileActiveORM.failure_mode_profile == profile,
        )
        result = await session.execute(stmt)
        active = result.scalar_one_or_none()
        return active.weights if active else None

    async def _get_or_create_active(
        self, session: AsyncSession, tenant_id: str, profile: str,
    ) -> WeightProfileActiveORM:
        stmt = select(WeightProfileActiveORM).where(
            WeightProfileActiveORM.tenant_id == tenant_id,
            WeightProfileActiveORM.failure_mode_profile == profile,
        )
        result = await session.execute(stmt)
        active = result.scalar_one_or_none()
        if active is None:
            active = WeightProfileActiveORM(
                tenant_id=tenant_id,
                failure_mode_profile=profile,
                weights=WEIGHT_PROFILES_V3.get(profile, WEIGHT_PROFILES_V3["DARK_EDGE"]),
                calibration_status="INITIAL_ESTIMATE",
            )
            session.add(active)
            await session.flush()
        return active
