"""
TASK-405: Safety Gate Test Coverage
25 tests: 21 unit tests (3 per gate) + 4 integration tests.
"""
import os

# Must be set before any backend imports
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_stub.db")

import pytest

from backend.app.services.safety_gate import (
    GateStatus,
    GateResult,
    SafetyDecision,
    SafetyGateService,
)


@pytest.fixture
def svc():
    return SafetyGateService()


# ─────────────────────────────────────────────
# Gate 1: Blast Radius
# ─────────────────────────────────────────────

def test_gate1_blast_radius_pass(svc):
    """5 entities — well within the limit of 10."""
    action = {"affected_entities": ["e1", "e2", "e3", "e4", "e5"]}
    result = svc.gate_1_blast_radius(action)
    assert result.status == GateStatus.PASS


def test_gate1_blast_radius_fail(svc):
    """11 entities — exceeds the limit of 10."""
    action = {"affected_entities": list(range(11))}
    result = svc.gate_1_blast_radius(action)
    assert result.status == GateStatus.FAIL
    assert "11" in result.reason


def test_gate1_blast_radius_edge_exactly_10(svc):
    """Exactly 10 entities — boundary value, should PASS (limit is > 10)."""
    action = {"affected_entities": list(range(10))}
    result = svc.gate_1_blast_radius(action)
    assert result.status == GateStatus.PASS


# ─────────────────────────────────────────────
# Gate 2: Policy Rules
# ─────────────────────────────────────────────

def test_gate2_policy_rules_pass(svc):
    """'acknowledge' is in the default allowed list."""
    action = {
        "action_type": "acknowledge",
        "allowed_action_types": ["acknowledge", "create_ticket"],
    }
    result = svc.gate_2_policy_rules(action, "tenant-1")
    assert result.status == GateStatus.PASS


def test_gate2_policy_rules_fail(svc):
    """'reboot' is not in the allowed list — should FAIL."""
    action = {
        "action_type": "reboot",
        "allowed_action_types": ["acknowledge", "create_ticket"],
    }
    result = svc.gate_2_policy_rules(action, "tenant-1")
    assert result.status == GateStatus.FAIL
    assert "reboot" in result.reason


def test_gate2_policy_rules_edge_empty_allowed_list(svc):
    """Empty allowed list — any action_type should FAIL."""
    action = {
        "action_type": "acknowledge",
        "allowed_action_types": [],
    }
    result = svc.gate_2_policy_rules(action, "tenant-1")
    assert result.status == GateStatus.FAIL


# ─────────────────────────────────────────────
# Gate 3: Confidence Threshold
# ─────────────────────────────────────────────

def test_gate3_confidence_pass(svc):
    """Confidence 0.90 — above the 0.85 threshold."""
    action = {"confidence": 0.90}
    result = svc.gate_3_confidence_threshold(action)
    assert result.status == GateStatus.PASS


def test_gate3_confidence_fail(svc):
    """Confidence 0.80 — below the 0.85 threshold."""
    action = {"confidence": 0.80}
    result = svc.gate_3_confidence_threshold(action)
    assert result.status == GateStatus.FAIL
    assert "0.80" in result.reason


def test_gate3_confidence_edge_exactly_085(svc):
    """Exactly 0.85 — boundary value, should PASS (threshold is <, not <=)."""
    action = {"confidence": 0.85}
    result = svc.gate_3_confidence_threshold(action)
    assert result.status == GateStatus.PASS


# ─────────────────────────────────────────────
# Gate 4: Maintenance Window
# ─────────────────────────────────────────────

def test_gate4_maintenance_window_pass(svc):
    """ghost_masked=False — not in a maintenance window."""
    action = {"ghost_masked": False}
    result = svc.gate_4_maintenance_window(action)
    assert result.status == GateStatus.PASS


def test_gate4_maintenance_window_fail(svc):
    """ghost_masked=True — entity is under maintenance."""
    action = {"ghost_masked": True}
    result = svc.gate_4_maintenance_window(action)
    assert result.status == GateStatus.FAIL
    assert "maintenance" in result.reason.lower()


def test_gate4_maintenance_window_edge_missing_key(svc):
    """Key absent — defaults to not masked, should PASS."""
    action = {}
    result = svc.gate_4_maintenance_window(action)
    assert result.status == GateStatus.PASS


# ─────────────────────────────────────────────
# Gate 5: Duplicate Suppression
# ─────────────────────────────────────────────

def test_gate5_duplicate_suppression_pass(svc):
    """Last executed 7200s ago — outside the 3600s window."""
    action = {"last_executed_seconds_ago": 7200}
    result = svc.gate_5_duplicate_suppression(action)
    assert result.status == GateStatus.PASS


def test_gate5_duplicate_suppression_fail(svc):
    """Last executed 1800s ago — within the 3600s window."""
    action = {"last_executed_seconds_ago": 1800}
    result = svc.gate_5_duplicate_suppression(action)
    assert result.status == GateStatus.FAIL
    assert "1800" in result.reason


def test_gate5_duplicate_suppression_edge_none(svc):
    """last_executed_seconds_ago is None — no prior execution, should PASS."""
    action = {"last_executed_seconds_ago": None}
    result = svc.gate_5_duplicate_suppression(action)
    assert result.status == GateStatus.PASS


# ─────────────────────────────────────────────
# Gate 6: Human Gate
# ─────────────────────────────────────────────

def test_gate6_human_gate_pass_low_risk(svc):
    """LOW risk, no approval needed — should PASS."""
    action = {"risk_level": "LOW", "human_approved": False}
    result = svc.gate_6_human_gate(action)
    assert result.status == GateStatus.PASS


def test_gate6_human_gate_fail_high_risk_no_approval(svc):
    """HIGH risk without human_approved — should FAIL."""
    action = {"risk_level": "HIGH", "human_approved": False}
    result = svc.gate_6_human_gate(action)
    assert result.status == GateStatus.FAIL
    assert "HIGH" in result.reason


def test_gate6_human_gate_pass_high_risk_with_approval(svc):
    """HIGH risk WITH human_approved=True — should PASS."""
    action = {"risk_level": "HIGH", "human_approved": True}
    result = svc.gate_6_human_gate(action)
    assert result.status == GateStatus.PASS


# ─────────────────────────────────────────────
# Gate 7: Rate Limit
# ─────────────────────────────────────────────

def test_gate7_rate_limit_pass(svc):
    """15 actions this hour — under the limit of 20."""
    action = {"actions_this_hour": 15}
    result = svc.gate_7_rate_limit(action)
    assert result.status == GateStatus.PASS


def test_gate7_rate_limit_fail(svc):
    """20 actions this hour — at or over the limit."""
    action = {"actions_this_hour": 20}
    result = svc.gate_7_rate_limit(action)
    assert result.status == GateStatus.FAIL
    assert "20" in result.reason


def test_gate7_rate_limit_edge_exactly_19(svc):
    """Exactly 19 actions — one below the limit, should PASS."""
    action = {"actions_this_hour": 19}
    result = svc.gate_7_rate_limit(action)
    assert result.status == GateStatus.PASS


# ─────────────────────────────────────────────
# Integration tests (4)
# ─────────────────────────────────────────────

def _good_action():
    """A minimal action payload that passes all 7 gates."""
    return {
        "action_id": "act-001",
        "affected_entities": list(range(5)),        # Gate 1: 5 <= 10
        "action_type": "acknowledge",               # Gate 2: in allowed list
        "allowed_action_types": ["acknowledge"],
        "confidence": 0.92,                         # Gate 3: >= 0.85
        "ghost_masked": False,                      # Gate 4: not masked
        "last_executed_seconds_ago": 7200,          # Gate 5: > 3600
        "risk_level": "LOW",                        # Gate 6: LOW, no approval needed
        "actions_this_hour": 5,                     # Gate 7: 5 < 20
    }


def test_integration_all_gates_pass_approves_action(svc):
    """All 7 gates pass — decision must be approved=True with gates_passed=7."""
    decision = svc.evaluate(_good_action(), tenant_id="t1")
    assert decision.approved is True
    assert decision.gates_passed == 7
    assert decision.gates_failed == 0


def test_integration_single_gate_fail_blocks_action(svc):
    """One gate fails (blast radius) — approved must be False."""
    action = _good_action()
    action["affected_entities"] = list(range(11))  # 11 > 10 → Gate 1 fails
    decision = svc.evaluate(action, tenant_id="t1")
    assert decision.approved is False
    assert decision.gates_failed >= 1


def test_integration_multiple_gates_fail(svc):
    """3 gates fail simultaneously — approved=False, gates_failed=3."""
    action = _good_action()
    action["affected_entities"] = list(range(11))   # Gate 1 fails
    action["confidence"] = 0.50                     # Gate 3 fails
    action["actions_this_hour"] = 25                # Gate 7 fails
    decision = svc.evaluate(action, tenant_id="t1")
    assert decision.approved is False
    assert decision.gates_failed == 3


def test_integration_summary_string_format(svc):
    """Summary string must match the expected format."""
    decision = svc.evaluate(_good_action(), tenant_id="t1")
    summary = decision.summary()
    assert "7/7 gates passed" in summary
    assert "APPROVED" in summary

    # Also verify a blocked summary
    action = _good_action()
    action["confidence"] = 0.50  # Gate 3 fails
    blocked = svc.evaluate(action, tenant_id="t1")
    blocked_summary = blocked.summary()
    assert "BLOCKED" in blocked_summary
