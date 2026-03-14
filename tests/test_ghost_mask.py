"""Tests for GhostMaskService (TASK-304)."""
import os
import pytest
from datetime import datetime, timedelta, timezone

# Ensure no Redis for tests
os.environ.pop("REDIS_URL", None)
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_stub.db")

from backend.app.services.ghost_mask import GhostMaskService, ChangeWindow, AnomalyFinding

NOW = datetime(2026, 3, 10, 12, 0, 0, tzinfo=timezone.utc)
WINDOW_START = NOW - timedelta(hours=1)
WINDOW_END = NOW + timedelta(hours=2)

CHANGE_TICKETS = [
    {
        "ticket_id": "CHG-001",
        "change_type": "planned_maintenance",
        "affected_entity_ids": ["CELL-001", "CELL-002"],
        "start_time": WINDOW_START.isoformat(),
        "end_time": WINDOW_END.isoformat(),
    }
]


@pytest.fixture
def svc():
    s = GhostMaskService()
    s.load_change_schedule(CHANGE_TICKETS)
    return s


def test_entity_in_active_window_is_masked(svc):
    finding = AnomalyFinding(entity_id="CELL-001", timestamp=NOW,
                              anomaly_type="KPI_DEGRADED", confidence=0.9)
    result = svc.apply_mask([finding])
    assert result[0].status == "GHOST_MASKED"
    assert result[0].change_ticket_id == "CHG-001"


def test_entity_outside_window_is_unaffected(svc):
    finding = AnomalyFinding(entity_id="CELL-999", timestamp=NOW,
                              anomaly_type="KPI_DEGRADED", confidence=0.9)
    result = svc.apply_mask([finding])
    assert result[0].status == "ACTIVE"


def test_masking_retains_finding_not_deletes(svc):
    findings = [
        AnomalyFinding("CELL-001", NOW, "KPI_DEGRADED", 0.9),
        AnomalyFinding("CELL-999", NOW, "SLEEPING_CELL", 0.7),
    ]
    result = svc.apply_mask(findings)
    assert len(result) == 2  # no deletion
    masked = [f for f in result if f.status == "GHOST_MASKED"]
    active = [f for f in result if f.status == "ACTIVE"]
    assert len(masked) == 1
    assert len(active) == 1


def test_masking_expires_after_window_end(svc):
    after_window = WINDOW_END + timedelta(minutes=30)
    finding = AnomalyFinding("CELL-001", after_window, "KPI_DEGRADED", 0.9)
    result = svc.apply_mask([finding])
    assert result[0].status == "ACTIVE"


def test_load_change_schedule_filters_non_maintenance():
    svc = GhostMaskService()
    tickets = [
        {"ticket_id": "CHG-002", "change_type": "incident", "affected_entity_ids": ["CELL-001"],
         "start_time": WINDOW_START.isoformat(), "end_time": WINDOW_END.isoformat()},
        {"ticket_id": "CHG-003", "change_type": "planned_maintenance", "affected_entity_ids": ["CELL-005"],
         "start_time": WINDOW_START.isoformat(), "end_time": WINDOW_END.isoformat()},
    ]
    windows = svc.load_change_schedule(tickets)
    assert len(windows) == 1
    assert windows[0].ticket_id == "CHG-003"


def test_get_active_windows_returns_current(svc):
    active = svc.get_active_windows(NOW)
    assert len(active) == 1
    assert active[0].ticket_id == "CHG-001"


def test_is_masked_returns_window(svc):
    window = svc.is_masked("CELL-001", NOW)
    assert window is not None
    assert window.ticket_id == "CHG-001"


def test_is_masked_returns_none_for_unaffected(svc):
    result = svc.is_masked("CELL-999", NOW)
    assert result is None
