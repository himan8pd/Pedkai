from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from backend.app.core.database import get_db
from backend.app.core.security import get_current_user, User
from backend.app.models.decision_trace_orm import DecisionFeedbackORM, DecisionTraceORM

router = APIRouter()


class OperatorFeedbackRequest(BaseModel):
    decision_id: str
    operator_id: str
    score: int  # 1 or -1
    action: str | None = None  # 'dismiss' | 'confirm' | None
    notes: str | None = None


@router.post("/operator/feedback")
async def submit_feedback(
    payload: OperatorFeedbackRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Record operator feedback on a decision trace and update aggregate feedback score.
    If action == 'dismiss', mark the decision trace status as 'dismissed' (used by calibration).
    """
    if payload.score not in (1, -1):
        raise HTTPException(status_code=400, detail="score must be 1 or -1")

    # Create feedback entry
    fb = DecisionFeedbackORM(
        decision_id=payload.decision_id,
        operator_id=payload.operator_id,
        score=payload.score,
    )
    db.add(fb)
    try:
        await db.flush()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to record feedback: {e}")

    # Recompute aggregate score
    try:
        result = await db.execute(
            "SELECT COALESCE(SUM(score),0) FROM decision_feedback WHERE decision_id = :did",
            {"did": payload.decision_id},
        )
        agg = result.scalar() or 0
        # Update the DecisionTraceORM.feedback_score and optionally status
        await db.execute(
            "UPDATE decision_traces SET feedback_score = :agg WHERE id = :did",
            {"agg": int(agg), "did": payload.decision_id},
        )

        if payload.action == "dismiss":
            await db.execute(
                "UPDATE decision_traces SET status = 'dismissed' WHERE id = :did",
                {"did": payload.decision_id},
            )

        await db.commit()
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to update decision trace: {e}")

    return {"ok": True, "decision_id": payload.decision_id, "aggregate_score": int(agg)}
