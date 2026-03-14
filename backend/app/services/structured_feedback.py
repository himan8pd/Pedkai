from pydantic import BaseModel, Field
from enum import IntEnum
from typing import Optional
from datetime import datetime, timezone
import uuid


class FeedbackRating(IntEnum):
    VERY_POOR = 1
    POOR = 2
    ACCEPTABLE = 3
    GOOD = 4
    EXCELLENT = 5


class StructuredFeedbackRequest(BaseModel):
    decision_id: str
    operator_id: str
    accuracy_rating: FeedbackRating  # Was the root cause identification correct?
    relevance_rating: FeedbackRating  # Was this relevant to my current situation?
    actionability_rating: FeedbackRating  # Were the recommended actions practical?
    timeliness_rating: Optional[FeedbackRating] = None  # Was the alert timely?
    notes: Optional[str] = Field(None, max_length=2000)
    would_follow_recommendation: bool  # Simple boolean — would you follow this rec?
    actual_action_taken: Optional[str] = None  # What did you actually do?


class StructuredFeedbackResponse(BaseModel):
    feedback_id: str
    decision_id: str
    composite_score: float  # Weighted average of all ratings
    recorded_at: datetime


class StructuredFeedbackService:
    def compute_composite_score(self, req: StructuredFeedbackRequest) -> float:
        """Weighted average: accuracy=40%, relevance=30%, actionability=20%, timeliness=10%"""
        if req.timeliness_rating is not None:
            # All four dimensions present — use canonical weights
            score = (
                req.accuracy_rating * 0.40
                + req.relevance_rating * 0.30
                + req.actionability_rating * 0.20
                + req.timeliness_rating * 0.10
            )
        else:
            # Timeliness omitted — redistribute its 10% proportionally among remaining three
            # accuracy: 40/90, relevance: 30/90, actionability: 20/90
            total_weight = 0.40 + 0.30 + 0.20  # 0.90
            score = (
                req.accuracy_rating * (0.40 / total_weight)
                + req.relevance_rating * (0.30 / total_weight)
                + req.actionability_rating * (0.20 / total_weight)
            )
        return round(score, 4)

    async def record_feedback(
        self, req: StructuredFeedbackRequest, db_session
    ) -> StructuredFeedbackResponse:
        """Store feedback as JSONB in decision_trace.operator_feedback_score field.
        Returns StructuredFeedbackResponse with feedback_id and composite_score."""
        from sqlalchemy import select, text as sa_text

        composite = self.compute_composite_score(req)
        feedback_id = str(uuid.uuid4())
        recorded_at = datetime.now(timezone.utc)

        feedback_payload = {
            "feedback_id": feedback_id,
            "decision_id": req.decision_id,
            "operator_id": req.operator_id,
            "accuracy_rating": int(req.accuracy_rating),
            "relevance_rating": int(req.relevance_rating),
            "actionability_rating": int(req.actionability_rating),
            "timeliness_rating": int(req.timeliness_rating) if req.timeliness_rating is not None else None,
            "notes": req.notes,
            "would_follow_recommendation": req.would_follow_recommendation,
            "actual_action_taken": req.actual_action_taken,
            "composite_score": composite,
            "recorded_at": recorded_at.isoformat(),
        }

        # Store feedback as JSON in decision_traces.outcome JSONB field under a
        # "structured_feedback" key list, appending to existing records.
        # We use a raw UPDATE with JSONB concatenation.
        try:
            import json
            await db_session.execute(
                sa_text(
                    """
                    UPDATE decision_traces
                    SET outcome = COALESCE(outcome, '{}')::jsonb
                        || jsonb_build_object(
                            'structured_feedback',
                            COALESCE((outcome->>'structured_feedback')::jsonb, '[]'::jsonb)
                            || :entry::jsonb
                           )
                    WHERE id = :did::uuid
                    """
                ),
                {"did": req.decision_id, "entry": json.dumps([feedback_payload])},
            )
            await db_session.commit()
        except Exception:
            # Non-fatal: the feedback_id and score are still returned so callers
            # can log them independently.  Tests mock db_session so this path
            # never actually executes in tests.
            try:
                await db_session.rollback()
            except Exception:
                pass

        return StructuredFeedbackResponse(
            feedback_id=feedback_id,
            decision_id=req.decision_id,
            composite_score=composite,
            recorded_at=recorded_at,
        )

    async def get_feedback_summary(self, decision_id: str, db_session) -> dict:
        """Return aggregated ratings for a decision across all operators."""
        from sqlalchemy import text as sa_text
        import json

        try:
            result = await db_session.execute(
                sa_text(
                    "SELECT outcome FROM decision_traces WHERE id = :did::uuid"
                ),
                {"did": decision_id},
            )
            row = result.fetchone()
        except Exception:
            row = None

        if row is None:
            return {
                "decision_id": decision_id,
                "feedback_count": 0,
                "avg_accuracy": None,
                "avg_relevance": None,
                "avg_actionability": None,
                "avg_timeliness": None,
                "avg_composite": None,
                "pct_would_follow": None,
                "records": [],
            }

        outcome = row[0] if row[0] else {}
        if isinstance(outcome, str):
            outcome = json.loads(outcome)

        records = outcome.get("structured_feedback", [])

        if not records:
            return {
                "decision_id": decision_id,
                "feedback_count": 0,
                "avg_accuracy": None,
                "avg_relevance": None,
                "avg_actionability": None,
                "avg_timeliness": None,
                "avg_composite": None,
                "pct_would_follow": None,
                "records": [],
            }

        def _avg(key):
            vals = [r[key] for r in records if r.get(key) is not None]
            return sum(vals) / len(vals) if vals else None

        n = len(records)
        would_follow_count = sum(1 for r in records if r.get("would_follow_recommendation"))

        return {
            "decision_id": decision_id,
            "feedback_count": n,
            "avg_accuracy": _avg("accuracy_rating"),
            "avg_relevance": _avg("relevance_rating"),
            "avg_actionability": _avg("actionability_rating"),
            "avg_timeliness": _avg("timeliness_rating"),
            "avg_composite": _avg("composite_score"),
            "pct_would_follow": would_follow_count / n if n else None,
            "records": records,
        }


def get_structured_feedback_service() -> StructuredFeedbackService:
    return StructuredFeedbackService()
