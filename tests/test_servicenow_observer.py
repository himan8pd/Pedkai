"""
Tests for ServiceNowObserver — Behavioural Feedback Pipeline.

Run with:
    SECRET_KEY=test-secret DATABASE_URL=sqlite+aiosqlite:///./test_stub.db \
    .venv/bin/python -m pytest tests/test_servicenow_observer.py -v --noconftest --tb=short
"""

import os
import sys

# Must be set BEFORE any backend imports
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_stub.db")

import pytest
import respx
import httpx
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, AsyncMock, patch
from uuid import uuid4

from backend.app.services.servicenow_observer import (
    ITSMAction,
    BehaviouralFeedback,
    ServiceNowObserver,
    get_servicenow_observer,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_action(
    action_type="acknowledge",
    entity_id="entity-001",
    tenant_id="tenant-a",
    operator_id="op-1",
) -> ITSMAction:
    return ITSMAction(
        ticket_id="INC001",
        entity_id=entity_id,
        action_type=action_type,
        operator_id=operator_id,
        tenant_id=tenant_id,
        timestamp=datetime.now(timezone.utc),
    )


def _mock_db_session(trace=None):
    """Return a mock AsyncSession that returns `trace` from execute()."""
    session = MagicMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = trace
    session.execute = AsyncMock(return_value=mock_result)
    session.add = MagicMock()
    session.flush = AsyncMock()
    return session


def _make_trace(action_taken="acknowledge", entity_id="entity-001", confidence=0.85):
    trace = MagicMock()
    trace.id = uuid4()
    trace.entity_id = entity_id
    trace.action_taken = action_taken
    trace.confidence_score = confidence
    trace.feedback_score = 0
    return trace


# ---------------------------------------------------------------------------
# Test 1: offline mode returns empty list
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_poll_offline_returns_empty():
    observer = ServiceNowObserver(base_url=None)
    since = datetime.now(timezone.utc) - timedelta(minutes=10)
    result = await observer.poll_recent_actions("tenant-a", since)
    assert result == []


# ---------------------------------------------------------------------------
# Test 2: successful HTTP poll parses actions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_poll_parses_incidents():
    base_url = "https://instance.service-now.com"
    observer = ServiceNowObserver(base_url=base_url, api_token="tok123")
    since = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

    payload = {
        "result": [
            {
                "sys_id": "abc123",
                "cmdb_ci": {"value": "entity-001"},
                "assigned_to": {"value": "op-1"},
                "state": "2",  # → acknowledge
                "sys_updated_on": "2024-01-02 10:00:00",
                "work_notes": "checked",
                "close_code": None,
            }
        ]
    }

    with respx.mock(base_url=base_url) as mock:
        mock.get("/api/now/table/incident").mock(
            return_value=httpx.Response(200, json=payload)
        )
        result = await observer.poll_recent_actions("tenant-a", since)

    assert len(result) == 1
    assert result[0].action_type == "acknowledge"
    assert result[0].entity_id == "entity-001"
    assert result[0].operator_id == "op-1"
    assert result[0].ticket_id == "abc123"


# ---------------------------------------------------------------------------
# Test 3: HTTP error returns empty list (no exception propagated)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_poll_http_error_returns_empty():
    base_url = "https://instance.service-now.com"
    observer = ServiceNowObserver(base_url=base_url)
    since = datetime.now(timezone.utc)

    with respx.mock(base_url=base_url) as mock:
        mock.get("/api/now/table/incident").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )
        result = await observer.poll_recent_actions("tenant-a", since)

    assert result == []


# ---------------------------------------------------------------------------
# Test 4: correlate with no DB trace → "ignored"
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_correlate_no_trace_gives_ignored():
    observer = ServiceNowObserver()
    action = _make_action()
    session = _mock_db_session(trace=None)

    feedback = await observer.correlate_with_recommendation(action, "tenant-a", session)

    assert feedback is not None
    assert feedback.outcome_label == "ignored"
    assert feedback.recommendation_followed is False
    assert action.action_type in feedback.delta_actions


# ---------------------------------------------------------------------------
# Test 5: correlate with matching trace → "aligned"
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_correlate_matching_trace_gives_aligned():
    observer = ServiceNowObserver()
    action = _make_action(action_type="acknowledge")
    trace = _make_trace(action_taken="acknowledge entity-001")
    session = _mock_db_session(trace=trace)

    feedback = await observer.correlate_with_recommendation(action, "tenant-a", session)

    assert feedback is not None
    assert feedback.outcome_label == "aligned"
    assert feedback.recommendation_followed is True
    assert feedback.delta_actions == []
    assert feedback.confidence == pytest.approx(0.85)


# ---------------------------------------------------------------------------
# Test 6: correlate with different trace → "overridden"
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_correlate_different_trace_gives_overridden():
    observer = ServiceNowObserver()
    action = _make_action(action_type="close")
    trace = _make_trace(action_taken="escalate to tier-2")
    session = _mock_db_session(trace=trace)

    feedback = await observer.correlate_with_recommendation(action, "tenant-a", session)

    assert feedback is not None
    assert feedback.outcome_label == "overridden"
    assert feedback.recommendation_followed is False
    assert "close" in feedback.delta_actions


# ---------------------------------------------------------------------------
# Test 7: store_feedback updates feedback_score for aligned outcome
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_store_feedback_increments_score_for_aligned():
    observer = ServiceNowObserver()
    trace = _make_trace(action_taken="resolve", confidence=0.9)

    action = _make_action(action_type="resolve")
    feedback = BehaviouralFeedback(
        decision_id=str(trace.id),
        tenant_id="tenant-a",
        operator_id="op-1",
        recommendation_followed=True,
        delta_actions=[],
        outcome_label="aligned",
        confidence=0.9,
        itsm_action=action,
        timestamp=datetime.now(timezone.utc),
    )

    session = _mock_db_session(trace=trace)
    await observer.store_feedback(feedback, session)

    # flush should have been called (trace was found and add called)
    session.flush.assert_awaited()


# ---------------------------------------------------------------------------
# Test 8: run_observation_cycle returns correct count and calls store
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_observation_cycle_counts_stored():
    base_url = "https://instance.service-now.com"
    observer = ServiceNowObserver(base_url=base_url, api_token="tok", poll_interval_seconds=300)

    since_arg_holder = {}

    async def fake_poll(tenant_id, since):
        since_arg_holder["since"] = since
        return [_make_action("acknowledge"), _make_action("resolve")]

    feedback_stub = BehaviouralFeedback(
        decision_id=str(uuid4()),
        tenant_id="tenant-a",
        operator_id="op-1",
        recommendation_followed=True,
        delta_actions=[],
        outcome_label="aligned",
        confidence=0.8,
        itsm_action=_make_action(),
        timestamp=datetime.now(timezone.utc),
    )

    store_calls = []

    async def fake_correlate(action, tenant_id, db_session=None):
        return feedback_stub

    async def fake_store(feedback, db_session):
        store_calls.append(feedback)

    observer.poll_recent_actions = fake_poll
    observer.correlate_with_recommendation = fake_correlate
    observer.store_feedback = fake_store

    session = _mock_db_session()
    count = await observer.run_observation_cycle("tenant-a", session)

    assert count == 2
    assert len(store_calls) == 2


# ---------------------------------------------------------------------------
# Test 9 (bonus): get_servicenow_observer reads env vars
# ---------------------------------------------------------------------------

def test_get_servicenow_observer_reads_env():
    with patch.dict(
        os.environ,
        {
            "SERVICENOW_URL": "https://example.service-now.com",
            "SERVICENOW_API_TOKEN": "mytoken",
        },
    ):
        obs = get_servicenow_observer()
    assert obs.base_url == "https://example.service-now.com"
    assert obs.api_token == "mytoken"
