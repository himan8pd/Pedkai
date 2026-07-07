"""
Snap confidence calibration (PRV-02).

Ports the decision-memory bin-calibration pattern (the "≥N votes" rule from
``DecisionRepository.get_calibration_stats``) to snap scores: instead of
trusting the model's ``final_score`` at face value, we look up the historical
operator-verdict rate for the matching *final-score decile* within a given
failure-mode profile and tenant.

If that bin has accumulated at least ``MIN_VOTES`` operator verdicts we return
the empirical true-positive rate as the calibrated confidence; otherwise we fall
back to the raw ``final_score`` and flag the result as un-calibrated.
"""

import os

from sqlalchemy import Integer, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.abeyance_orm import SnapDecisionRecordORM
from backend.app.models.abeyance_v3_orm import SnapOutcomeFeedbackORM

# Minimum operator verdicts required in a bin before its empirical rate is
# trusted over the raw model score. Mirrors the decision-memory ≥N votes rule.
MIN_VOTES = int(os.environ.get("SNAP_CONFIDENCE_MIN_VOTES", "50"))

# Verdicts that count as a confirmed true positive (mirrors
# OutcomeCalibrationService.record_feedback semantics).
_TP_VERDICTS = ("TRUE_POSITIVE", "CONFIRMED")


def _score_to_bin(final_score: float) -> int:
    """Map a final score in [0, 1] to a decile bin index 0..9 (clamped)."""
    bin_index = int(final_score * 10)
    if bin_index < 0:
        return 0
    if bin_index > 9:
        return 9
    return bin_index


async def get_calibrated_confidence(
    session: AsyncSession,
    tenant_id: str,
    profile: str,
    final_score: float,
) -> dict:
    """Return a calibrated confidence for a snap score.

    Joins ``snap_outcome_feedback`` to ``snap_decision_record`` and aggregates,
    within ``(tenant_id, profile)``, every verdict whose parent decision falls in
    the same final-score decile as ``final_score``.

    Returns ``{"calibrated": bool, "confidence": float, "votes": int,
    "bin": int}``:

    * ``votes >= MIN_VOTES`` -> ``confidence = tp / votes``, ``calibrated=True``.
    * otherwise               -> ``confidence = final_score``, ``calibrated=False``.
    """
    bin_index = _score_to_bin(final_score)

    # Decile bound in raw-score space: [bin/10, (bin+1)/10). The top bin (9)
    # also captures an exact 1.0 score.
    lower = bin_index / 10.0
    upper = (bin_index + 1) / 10.0

    # Count-of-TP as a portable SUM(CASE ...) so it works on Postgres and the
    # aiosqlite test shim alike.
    tp_expr = func.sum(
        func.cast(
            SnapOutcomeFeedbackORM.operator_verdict.in_(_TP_VERDICTS),
            Integer,
        )
    )

    stmt = (
        select(
            func.count(SnapOutcomeFeedbackORM.id).label("votes"),
            tp_expr.label("tp"),
        )
        .join(
            SnapDecisionRecordORM,
            SnapDecisionRecordORM.id
            == SnapOutcomeFeedbackORM.snap_decision_record_id,
        )
        .where(
            SnapDecisionRecordORM.tenant_id == tenant_id,
            SnapDecisionRecordORM.failure_mode_profile == profile,
            SnapDecisionRecordORM.final_score >= lower,
            (
                SnapDecisionRecordORM.final_score < upper
                if bin_index < 9
                else SnapDecisionRecordORM.final_score <= upper
            ),
        )
    )

    result = await session.execute(stmt)
    row = result.one()
    votes = int(row.votes or 0)
    tp = int(row.tp or 0)

    if votes >= MIN_VOTES:
        confidence = tp / votes
        calibrated = True
    else:
        confidence = float(final_score)
        calibrated = False

    return {
        "calibrated": calibrated,
        "confidence": float(confidence),
        "votes": votes,
        "bin": bin_index,
    }
