import os
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_stub.db")

import pytest
from backend.app.services.sitrep_router import (
    SitrepRouter,
    EscalationTier,
    EscalationRule,
    SeverityLevel,
    get_sitrep_router,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def router():
    return SitrepRouter()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_ran_critical_routes_to_noc_engineer(router):
    """CRITICAL RAN severity routes to NOC_ENGINEER as initial tier."""
    decision = router.route("s-001", "cell-1", "RAN", SeverityLevel.CRITICAL)
    assert decision.assigned_tier == EscalationTier.NOC_ENGINEER


def test_core_critical_routes_to_noc_manager(router):
    """CRITICAL Core routes to NOC_MANAGER — elevated vs RAN CRITICAL."""
    decision = router.route("s-002", "core-1", "Core", SeverityLevel.CRITICAL)
    assert decision.assigned_tier == EscalationTier.NOC_MANAGER
    # Different (elevated) tier compared to RAN CRITICAL
    ran_decision = router.route("s-003", "cell-2", "RAN", SeverityLevel.CRITICAL)
    assert decision.assigned_tier != ran_decision.assigned_tier


def test_transport_critical_requires_field(router):
    """Transport CRITICAL routing rule has requires_field=True."""
    decision = router.route("s-004", "link-1", "Transport", SeverityLevel.CRITICAL)
    assert decision.escalation_rule is not None
    assert decision.escalation_rule.requires_field is True


def test_escalation_path_has_at_least_one_tier(router):
    """get_escalation_path returns a list with at least 1 tier for any domain+severity."""
    # Test several combinations
    combos = [
        ("RAN", SeverityLevel.CRITICAL),
        ("Core", SeverityLevel.HIGH),
        ("Transport", SeverityLevel.CRITICAL),
        ("UnknownDomain", SeverityLevel.MEDIUM),
    ]
    for domain, severity in combos:
        path = router.get_escalation_path(domain, severity)
        assert isinstance(path, list)
        assert len(path) >= 1, f"Expected at least 1 tier for {domain}/{severity}"
        assert all(isinstance(t, EscalationTier) for t in path)


def test_should_escalate_true_when_elapsed_exceeds_threshold(router):
    """should_escalate returns True when elapsed >= escalation_after_minutes."""
    rule = EscalationRule(
        "RAN", SeverityLevel.CRITICAL,
        EscalationTier.NOC_ENGINEER, 15, EscalationTier.NOC_MANAGER
    )
    assert router.should_escalate(rule, 15) is True
    assert router.should_escalate(rule, 30) is True


def test_should_escalate_false_when_elapsed_below_threshold(router):
    """should_escalate returns False when elapsed < escalation_after_minutes."""
    rule = EscalationRule(
        "RAN", SeverityLevel.CRITICAL,
        EscalationTier.NOC_ENGINEER, 15, EscalationTier.NOC_MANAGER
    )
    assert router.should_escalate(rule, 14) is False
    assert router.should_escalate(rule, 0) is False


def test_low_severity_any_domain_matches_rule(router):
    """LOW severity with any domain matches the wildcard rule."""
    decision = router.route("s-005", "entity-x", "SomeDomain", SeverityLevel.LOW)
    # Should match the wildcard "*" LOW rule and return a valid decision
    assert decision.assigned_tier is not None
    assert isinstance(decision.assigned_tier, EscalationTier)


def test_get_field_required_domains_contains_transport(router):
    """get_field_required_domains returns a non-empty list containing 'Transport'."""
    domains = router.get_field_required_domains()
    assert isinstance(domains, list)
    assert len(domains) >= 1
    assert "Transport" in domains
