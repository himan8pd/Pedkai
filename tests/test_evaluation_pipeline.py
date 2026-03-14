"""
Tests for the Continuous Evaluation Pipeline (TASK-403).

8 tests covering EvaluationMetrics and EvaluationPipeline behaviour,
using AsyncMock for db_session to avoid needing a real database.
"""

import os

os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_stub.db")

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.services.evaluation_pipeline import (
    EvaluationMetrics,
    EvaluationPipeline,
    get_evaluation_pipeline,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_metrics(cmdb_accuracy: float = 0.95, benchmark_threshold: float = 0.9) -> EvaluationMetrics:
    now = datetime.utcnow()
    return EvaluationMetrics(
        tenant_id="tenant-test",
        period_start=now - timedelta(days=30),
        period_end=now,
        cmdb_accuracy_rate=cmdb_accuracy,
        mttr_correlation=0.42,
        discovery_rate=3.5,
        total_decisions=100,
        total_feedback_records=50,
        benchmark_threshold=benchmark_threshold,
    )


# ---------------------------------------------------------------------------
# EvaluationMetrics unit tests
# ---------------------------------------------------------------------------

def test_passes_benchmark_true():
    """accuracy=0.95 with threshold=0.9 → passes_benchmark() is True."""
    m = _make_metrics(cmdb_accuracy=0.95, benchmark_threshold=0.9)
    assert m.passes_benchmark() is True


def test_passes_benchmark_false():
    """accuracy=0.85 with threshold=0.9 → passes_benchmark() is False."""
    m = _make_metrics(cmdb_accuracy=0.85, benchmark_threshold=0.9)
    assert m.passes_benchmark() is False


def test_to_dict_contains_all_keys():
    """to_dict() must contain all expected keys."""
    m = _make_metrics()
    d = m.to_dict()
    expected_keys = {
        "tenant_id",
        "period_start",
        "period_end",
        "cmdb_accuracy_rate",
        "mttr_correlation",
        "discovery_rate",
        "total_decisions",
        "total_feedback_records",
        "passes_benchmark",
    }
    assert expected_keys.issubset(set(d.keys())), (
        f"Missing keys: {expected_keys - set(d.keys())}"
    )


# ---------------------------------------------------------------------------
# EvaluationPipeline async tests
# ---------------------------------------------------------------------------

def _async_scalar(value):
    """Return an AsyncMock whose execute() returns a mock with scalar() returning value."""
    result_mock = MagicMock()
    result_mock.scalar.return_value = value
    result_mock.fetchall.return_value = []
    execute_mock = AsyncMock(return_value=result_mock)
    session = MagicMock()
    session.execute = execute_mock
    return session


@pytest.mark.asyncio
async def test_cmdb_accuracy_rate_empty_returns_zero():
    """When DB has no dark node records, compute_cmdb_accuracy_rate returns 0.0."""
    pipeline = EvaluationPipeline()
    since = datetime.utcnow() - timedelta(days=30)

    # execute returns empty fetchall (no dark nodes)
    result_mock = MagicMock()
    result_mock.fetchall.return_value = []
    session = MagicMock()
    session.execute = AsyncMock(return_value=result_mock)

    rate = await pipeline.compute_cmdb_accuracy_rate("tenant-test", since, session)
    assert rate == 0.0


@pytest.mark.asyncio
async def test_discovery_rate_empty_returns_zero():
    """When there are no reconciliation runs, compute_discovery_rate returns 0.0."""
    pipeline = EvaluationPipeline()
    since = datetime.utcnow() - timedelta(days=30)

    # First execute() call returns 0 runs (scalar=0)
    run_result = MagicMock()
    run_result.scalar.return_value = 0

    session = MagicMock()
    session.execute = AsyncMock(return_value=run_result)

    rate = await pipeline.compute_discovery_rate("tenant-test", since, session)
    assert rate == 0.0


@pytest.mark.asyncio
async def test_mttr_correlation_insufficient_data_returns_zero():
    """When fewer than 5 data points are available, compute_mttr_correlation returns 0.0."""
    pipeline = EvaluationPipeline()
    since = datetime.utcnow() - timedelta(days=30)

    # First execute (decisions) returns 3 rows — not enough for Pearson
    decision_rows = [
        ("entity-1", 0.8),
        ("entity-2", 0.6),
        ("entity-3", 0.9),
    ]
    now = datetime.utcnow()
    incident_rows = [
        ("entity-1", now - timedelta(hours=2), now - timedelta(hours=1)),
        ("entity-2", now - timedelta(hours=3), now - timedelta(hours=1)),
        ("entity-3", now - timedelta(hours=4), now - timedelta(hours=1)),
    ]

    decision_result = MagicMock()
    decision_result.fetchall.return_value = decision_rows
    incident_result = MagicMock()
    incident_result.fetchall.return_value = incident_rows

    call_count = 0

    async def side_effect_execute(stmt):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return decision_result
        return incident_result

    session = MagicMock()
    session.execute = side_effect_execute

    corr = await pipeline.compute_mttr_correlation("tenant-test", since, session)
    assert corr == 0.0


@pytest.mark.asyncio
async def test_run_evaluation_offline_mode():
    """When db_session=None, run_evaluation returns stub EvaluationMetrics with 0.0 values."""
    pipeline = EvaluationPipeline(benchmark_threshold=0.9)
    metrics = await pipeline.run_evaluation(tenant_id="tenant-test", db_session=None)

    assert isinstance(metrics, EvaluationMetrics)
    assert metrics.tenant_id == "tenant-test"
    assert metrics.cmdb_accuracy_rate == 0.0
    assert metrics.mttr_correlation == 0.0
    assert metrics.discovery_rate == 0.0
    assert metrics.total_decisions == 0
    assert metrics.total_feedback_records == 0
    assert metrics.benchmark_threshold == 0.9


@pytest.mark.asyncio
async def test_check_benchmark_returns_dict():
    """check_benchmark returns a dict containing 'benchmark_passed' and 'passes_benchmark'."""
    pipeline = EvaluationPipeline(benchmark_threshold=0.9)

    # Patch run_evaluation to return a known metrics object
    known_metrics = _make_metrics(cmdb_accuracy=0.95)

    async def mock_run_evaluation(tenant_id, lookback_days=30, db_session=None):
        return known_metrics

    pipeline.run_evaluation = mock_run_evaluation

    session = MagicMock()
    result = await pipeline.check_benchmark(tenant_id="tenant-test", db_session=session)

    assert isinstance(result, dict)
    assert "benchmark_passed" in result
    assert result["benchmark_passed"] is True
    assert "passes_benchmark" in result
