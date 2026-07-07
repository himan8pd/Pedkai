"""
WIR-02 — Entity state transition logging from the fragment bridge.

Verifies TelemetryFragmentBridge feeds RAISED/CLEARED transitions into the
TemporalSequenceModeller for ALARM events:
  - one log_transition call per alarm with correct from/to states,
  - non-UUID entity ids are skipped without error,
  - env FRAGMENT_BRIDGE_LOG_TRANSITIONS=false disables logging entirely.
"""

from __future__ import annotations

import importlib
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest


ENTITY_UUID = uuid4()
EVENT_TS = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)


def _load_bridge_module(monkeypatch, log_transitions: str = "true"):
    """(Re)import the bridge module with the env gate set as requested."""
    monkeypatch.setenv("FRAGMENT_BRIDGE_LOG_TRANSITIONS", log_transitions)
    import backend.app.telemetry.fragment_bridge as fb

    return importlib.reload(fb)


def _fake_session():
    session = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    return session


def _wire_bridge(fb, monkeypatch, temporal):
    """Build a bridge with a mocked services dict and stubbed DB/stages."""
    bridge = fb.TelemetryFragmentBridge()

    fragment = MagicMock()
    fragment.id = uuid4()
    fragment.event_timestamp = EVENT_TS

    enrichment = MagicMock()
    enrichment.enrich = AsyncMock(return_value=fragment)
    snap_engine = MagicMock()
    snap_engine.evaluate = AsyncMock()
    accumulation = MagicMock()
    accumulation.detect_and_evaluate_clusters = AsyncMock()

    bridge._services = {
        "enrichment_v3": enrichment,
        "snap_engine_v3": snap_engine,
        "accumulation_graph": accumulation,
        "temporal_sequence": temporal,
    }

    session = _fake_session()

    @asynccontextmanager
    async def _fake_db_context():
        yield session

    monkeypatch.setattr(
        "backend.app.core.database.get_db_context", _fake_db_context
    )
    # Neutralise the incident-creation stage (touches ORM/DB).
    bridge._create_incident_from_snaps = AsyncMock()

    return bridge, fragment


def _alarm(entity_id, *, cleared: bool = False):
    return {
        "alarm_id": str(uuid4()),
        "tenant_id": "tenant-a",
        "entity_id": entity_id,
        "domain": "radio",
        "severity": "critical",
        "alarm_type": "LOS",
        "raised_at": EVENT_TS,
        "cleared_at": EVENT_TS if cleared else None,
    }


@pytest.mark.asyncio
async def test_raised_alarm_logs_raised_transition(monkeypatch):
    fb = _load_bridge_module(monkeypatch, "true")
    temporal = AsyncMock()
    bridge, fragment = _wire_bridge(fb, monkeypatch, temporal)

    await bridge._process_batch([("ALARM", _alarm(str(ENTITY_UUID)))])

    temporal.log_transition.assert_awaited_once()
    kwargs = temporal.log_transition.await_args.kwargs
    assert kwargs["entity_id"] == ENTITY_UUID
    assert kwargs["from_state"] == "CLEARED"
    assert kwargs["to_state"] == "RAISED"
    assert kwargs["tenant_id"] == "tenant-a"
    assert kwargs["entity_domain"] == "radio"
    assert kwargs["fragment_id"] == fragment.id
    assert kwargs["event_timestamp"] == EVENT_TS


@pytest.mark.asyncio
async def test_cleared_alarm_logs_cleared_transition(monkeypatch):
    fb = _load_bridge_module(monkeypatch, "true")
    temporal = AsyncMock()
    bridge, _ = _wire_bridge(fb, monkeypatch, temporal)

    await bridge._process_batch(
        [("ALARM", _alarm(str(ENTITY_UUID), cleared=True))]
    )

    temporal.log_transition.assert_awaited_once()
    kwargs = temporal.log_transition.await_args.kwargs
    assert kwargs["from_state"] == "RAISED"
    assert kwargs["to_state"] == "CLEARED"


@pytest.mark.asyncio
async def test_non_uuid_entity_is_skipped(monkeypatch):
    fb = _load_bridge_module(monkeypatch, "true")
    temporal = AsyncMock()
    bridge, _ = _wire_bridge(fb, monkeypatch, temporal)

    # Should not raise, and no transition should be logged.
    await bridge._process_batch([("ALARM", _alarm("not-a-uuid"))])

    temporal.log_transition.assert_not_awaited()


@pytest.mark.asyncio
async def test_env_false_produces_zero_calls(monkeypatch):
    fb = _load_bridge_module(monkeypatch, "false")
    temporal = AsyncMock()
    bridge, _ = _wire_bridge(fb, monkeypatch, temporal)

    await bridge._process_batch([("ALARM", _alarm(str(ENTITY_UUID)))])

    temporal.log_transition.assert_not_awaited()
