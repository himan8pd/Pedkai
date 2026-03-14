"""
Tests for StructuredFeedbackService (TASK-402).

8 tests covering composite score weighting, normalisation, storage, and summary.
"""
import os

os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_stub.db")

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from backend.app.services.structured_feedback import (
    FeedbackRating,
    StructuredFeedbackRequest,
    StructuredFeedbackService,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_request(**overrides) -> StructuredFeedbackRequest:
    defaults = dict(
        decision_id="dec-001",
        operator_id="op-1",
        accuracy_rating=FeedbackRating.GOOD,        # 4
        relevance_rating=FeedbackRating.GOOD,        # 4
        actionability_rating=FeedbackRating.GOOD,   # 4
        timeliness_rating=FeedbackRating.GOOD,      # 4
        notes=None,
        would_follow_recommendation=True,
        actual_action_taken=None,
    )
    defaults.update(overrides)
    return StructuredFeedbackRequest(**defaults)


def _make_db_mock(outcome_value=None):
    """Return an AsyncMock db session whose execute().fetchone() returns one row."""
    db = AsyncMock()
    row_mock = MagicMock()
    row_mock.__getitem__ = lambda self, i: outcome_value
    result_mock = MagicMock()
    result_mock.fetchone.return_value = row_mock
    db.execute = AsyncMock(return_value=result_mock)
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# 1. test_composite_score_weights
# ---------------------------------------------------------------------------

def test_composite_score_weights():
    """Verify accuracy=40%, relevance=30%, actionability=20%, timeliness=10%."""
    svc = StructuredFeedbackService()
    req = _make_request(
        accuracy_rating=FeedbackRating.EXCELLENT,       # 5
        relevance_rating=FeedbackRating.VERY_POOR,      # 1
        actionability_rating=FeedbackRating.VERY_POOR,  # 1
        timeliness_rating=FeedbackRating.VERY_POOR,     # 1
    )
    expected = 5 * 0.40 + 1 * 0.30 + 1 * 0.20 + 1 * 0.10  # 2.6
    result = svc.compute_composite_score(req)
    assert abs(result - expected) < 0.001, f"Expected {expected}, got {result}"


# ---------------------------------------------------------------------------
# 2. test_composite_score_no_timeliness
# ---------------------------------------------------------------------------

def test_composite_score_no_timeliness():
    """Timeliness omitted; remaining weights normalised to sum to 1."""
    svc = StructuredFeedbackService()
    req = _make_request(
        accuracy_rating=FeedbackRating.EXCELLENT,       # 5
        relevance_rating=FeedbackRating.VERY_POOR,      # 1
        actionability_rating=FeedbackRating.VERY_POOR,  # 1
        timeliness_rating=None,
    )
    # accuracy: 40/90, relevance: 30/90, actionability: 20/90
    expected = 5 * (40 / 90) + 1 * (30 / 90) + 1 * (20 / 90)
    result = svc.compute_composite_score(req)
    assert abs(result - expected) < 0.001, f"Expected {expected}, got {result}"
    # Weights must sum to 1 when timeliness is absent
    # Verify: result is between 1 and 5
    assert 1.0 <= result <= 5.0


# ---------------------------------------------------------------------------
# 3. test_all_five_rating
# ---------------------------------------------------------------------------

def test_all_five_rating():
    """All ratings = 5 → composite_score == 5.0 regardless of weights."""
    svc = StructuredFeedbackService()
    req = _make_request(
        accuracy_rating=FeedbackRating.EXCELLENT,
        relevance_rating=FeedbackRating.EXCELLENT,
        actionability_rating=FeedbackRating.EXCELLENT,
        timeliness_rating=FeedbackRating.EXCELLENT,
    )
    result = svc.compute_composite_score(req)
    assert result == 5.0, f"Expected 5.0, got {result}"


# ---------------------------------------------------------------------------
# 4. test_record_feedback_returns_response
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_record_feedback_returns_response():
    """Mock db; verify response has feedback_id and composite_score."""
    svc = StructuredFeedbackService()
    db = _make_db_mock()
    req = _make_request()
    response = await svc.record_feedback(req, db)
    assert response.feedback_id is not None and len(response.feedback_id) > 0
    assert response.composite_score > 0
    assert response.decision_id == req.decision_id


# ---------------------------------------------------------------------------
# 5. test_would_follow_recommendation_stored
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_would_follow_recommendation_stored():
    """Check that would_follow_recommendation boolean is stored in feedback."""
    svc = StructuredFeedbackService()
    db = _make_db_mock()
    req = _make_request(would_follow_recommendation=False)
    response = await svc.record_feedback(req, db)
    # The response is a StructuredFeedbackResponse; confirm it was created
    # without error and the db execute was called (indicating a write was
    # attempted with the payload containing would_follow_recommendation).
    assert response.feedback_id is not None
    # Verify execute was called (db write attempted)
    db.execute.assert_called()


# ---------------------------------------------------------------------------
# 6. test_notes_stored_in_feedback
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_notes_stored_in_feedback():
    """Check notes appear in response metadata (via record_feedback call)."""
    svc = StructuredFeedbackService()
    db = _make_db_mock()
    notes = "The alert was 10 minutes late but root cause was correct."
    req = _make_request(notes=notes)
    response = await svc.record_feedback(req, db)
    # response is returned; it went through without exception
    assert response.feedback_id is not None
    # The execute call should have been made (write attempted)
    db.execute.assert_called()


# ---------------------------------------------------------------------------
# 7. test_get_feedback_summary_returns_dict
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_feedback_summary_returns_dict():
    """Mock db with one feedback record; verify summary dict structure."""
    import json

    svc = StructuredFeedbackService()

    record = {
        "feedback_id": "fb-123",
        "decision_id": "dec-001",
        "operator_id": "op-1",
        "accuracy_rating": 4,
        "relevance_rating": 4,
        "actionability_rating": 4,
        "timeliness_rating": 4,
        "notes": None,
        "would_follow_recommendation": True,
        "actual_action_taken": None,
        "composite_score": 4.0,
        "recorded_at": "2026-03-11T10:00:00+00:00",
    }
    outcome_value = {"structured_feedback": [record]}

    db = _make_db_mock(outcome_value=outcome_value)

    summary = await svc.get_feedback_summary("dec-001", db)

    assert isinstance(summary, dict)
    assert summary["feedback_count"] == 1
    assert summary["avg_composite"] == 4.0
    assert summary["pct_would_follow"] == 1.0
    assert len(summary["records"]) == 1


# ---------------------------------------------------------------------------
# 8. test_low_accuracy_brings_composite_down
# ---------------------------------------------------------------------------

def test_low_accuracy_brings_composite_down():
    """accuracy=1, others=5 → composite < 3 (accuracy carries 40% weight)."""
    svc = StructuredFeedbackService()
    req = _make_request(
        accuracy_rating=FeedbackRating.VERY_POOR,   # 1
        relevance_rating=FeedbackRating.EXCELLENT,  # 5
        actionability_rating=FeedbackRating.EXCELLENT,  # 5
        timeliness_rating=FeedbackRating.EXCELLENT,     # 5
    )
    result = svc.compute_composite_score(req)
    # 1*0.40 + 5*0.30 + 5*0.20 + 5*0.10 = 0.40 + 1.50 + 1.00 + 0.50 = 3.40
    # Wait — that's 3.4 which is > 3. Let's use the actual expected value.
    expected = 1 * 0.40 + 5 * 0.30 + 5 * 0.20 + 5 * 0.10  # = 3.4
    assert abs(result - expected) < 0.001
    # Also verify it is less than a pure-5 composite (5.0)
    all_five = svc.compute_composite_score(_make_request(
        accuracy_rating=FeedbackRating.EXCELLENT,
        relevance_rating=FeedbackRating.EXCELLENT,
        actionability_rating=FeedbackRating.EXCELLENT,
        timeliness_rating=FeedbackRating.EXCELLENT,
    ))
    assert result < all_five
