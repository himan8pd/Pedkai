"""Unit tests for the data-retention cleanup periodic job (INF-03)."""

import logging

import pytest

from backend.app.workers.jobs import data_retention
from backend.app.workers.periodic_jobs import PeriodicJob


def test_job_definition():
    """JOB is a PeriodicJob with the expected name and defaults."""
    assert isinstance(data_retention.JOB, PeriodicJob)
    assert data_retention.JOB.name == "data_retention"
    assert data_retention.JOB.interval_seconds == 86400
    assert data_retention.JOB.enabled is True


@pytest.mark.asyncio
async def test_run_invokes_service_once_and_logs(monkeypatch, caplog):
    """_run() calls run_retention_cleanup exactly once and logs the summary."""
    calls = {"n": 0}
    summary = {"llm_prompt_logs": {"deleted": 3, "cutoff": "2026-04-08"}}

    class _FakeService:
        def __init__(self, session_factory):
            self.session_factory = session_factory

        async def run_retention_cleanup(self):
            calls["n"] += 1
            return summary

    monkeypatch.setattr(data_retention, "DataRetentionService", _FakeService)

    with caplog.at_level(logging.INFO):
        await data_retention._run()

    assert calls["n"] == 1
    assert any(
        "Data-retention cleanup complete" in rec.getMessage()
        and "llm_prompt_logs" in rec.getMessage()
        for rec in caplog.records
    )
