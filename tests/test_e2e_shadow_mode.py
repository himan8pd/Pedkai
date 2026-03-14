"""
TASK-602: E2E Integration tests for Shadow Mode deployment flow.

Shadow Mode is the Month-3 read-only deployment where Pedk.ai:
- Taps production telemetry via Kafka (asyncio.Queue fallback in tests)
- Runs full alarm correlation pipeline in parallel
- Generates SITREPs for internal use only (never sent externally)
- SafetyGates enforce no-write / no-autonomous-action policy
- Operator receives recommendations but takes all actions manually

All tests run without a live DB or live Kafka. EventBus uses asyncio.Queue
fallback when REDIS_URL is absent.

Run with:
    pytest tests/test_e2e_shadow_mode.py -v --noconftest
"""
import os

# Must be set BEFORE any backend imports
os.environ.setdefault("SECRET_KEY", "test-secret-shadow-mode")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_shadow.db")
# No REDIS_URL → EventBus falls back to asyncio.Queue
os.environ.pop("REDIS_URL", None)

import asyncio
import uuid
from datetime import datetime

import pytest

from backend.app.services.event_bus import Event, EventBus
from backend.app.services.sitrep_router import (
    EscalationTier,
    SeverityLevel,
    SitrepRouter,
    get_sitrep_router,
)
from backend.app.services.safety_gate import (
    GateStatus,
    SafetyDecision,
    SafetyGateService,
)
from backend.app.services.playbook_generator import (
    Playbook,
    PlaybookGenerator,
    PlaybookStep,
    get_playbook_generator,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_bus() -> EventBus:
    """Return a fresh EventBus with no Redis URL (fallback mode)."""
    bus = EventBus()
    assert bus._redis_url is None, "REDIS_URL must not be set for shadow-mode tests"
    return bus


def _shadow_mode_action(overrides: dict = None) -> dict:
    """
    A fully read-only assessment action for shadow mode.
    All gates pass: blast_radius=0 entities, read-only action type,
    high confidence, not ghost-masked, no recent duplicate, LOW risk, low rate.
    """
    base = {
        "action_id": "shadow-assess-001",
        "affected_entities": [],                    # Gate 1: 0 entities — read-only
        "action_type": "acknowledge",               # Gate 2: allowed read-only action
        "allowed_action_types": ["acknowledge", "create_ticket"],
        "confidence": 0.93,                         # Gate 3: >= 0.85
        "ghost_masked": False,                      # Gate 4: no maintenance window
        "last_executed_seconds_ago": None,          # Gate 5: no duplicate
        "risk_level": "LOW",                        # Gate 6: no human approval needed
        "actions_this_hour": 1,                     # Gate 7: well within limit
    }
    if overrides:
        base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Test 1: EventBus offline queue fallback
# ---------------------------------------------------------------------------

async def test_eventbus_offline_queue_fallback():
    """
    In shadow mode Kafka is not available in test env.
    EventBus must fall back to asyncio.Queue and deliver events correctly.
    """
    bus = _make_bus()
    tenant_id = uuid.uuid4()
    event_type = "anomaly.detected"
    payload = {"alarm_id": "shadow-A1", "severity": "high", "cell": "RAN-007"}

    event_id = await bus.publish(event_type, payload, tenant_id)

    # Fallback IDs are prefixed "fallback-"
    assert event_id.startswith("fallback-"), f"Expected fallback ID, got: {event_id}"

    # Queue must exist and hold exactly 1 event
    queue_key = f"{tenant_id}:{event_type}"
    assert queue_key in bus._fallback_queues
    assert bus._fallback_queues[queue_key].qsize() == 1

    # Redis client must NOT have been created
    assert bus._redis_client is None

    # Consume via subscribe and verify payload fidelity
    received: list[Event] = []

    async def _consume():
        async for event in bus.subscribe(event_type, "shadow-group", "c1", tenant_id=str(tenant_id)):
            received.append(event)
            return

    await asyncio.wait_for(_consume(), timeout=2)

    assert len(received) == 1
    assert received[0].payload == payload
    assert received[0].event_type == event_type
    assert received[0].tenant_id == str(tenant_id)


# ---------------------------------------------------------------------------
# Test 2: SitrepRouter routing for HIGH severity alarms
# ---------------------------------------------------------------------------

def test_sitrep_router_high_severity_ran():
    """
    HIGH severity RAN alarm must be routed to NOC_ENGINEER (Tier 1)
    with escalation path to NOC_MANAGER after 30 min per DEFAULT_RULES.
    """
    router = get_sitrep_router()
    decision = router.route(
        sitrep_id="sitrep-ran-high-001",
        entity_id="cell-RAN-007",
        domain="RAN",
        severity=SeverityLevel.HIGH,
    )

    assert decision.assigned_tier == EscalationTier.NOC_ENGINEER
    assert EscalationTier.NOC_ENGINEER.value in decision.assigned_team_ids
    assert decision.escalation_rule is not None
    assert decision.escalation_rule.escalate_to == EscalationTier.NOC_MANAGER
    assert decision.escalation_rule.escalation_after_minutes == 30
    # Shadow mode: decision is internal-only, verify rationale is populated
    assert "RAN" in decision.rationale
    assert "high" in decision.rationale.lower()


# ---------------------------------------------------------------------------
# Test 3: SafetyGate blocks autonomous writes (HIGH risk, no human approval)
# ---------------------------------------------------------------------------

def test_safety_gate_blocks_autonomous_write_high_risk():
    """
    Shadow mode core constraint: any HIGH-risk autonomous action must be
    blocked by Gate 6 (human gate) when human_approved=False.
    In shadow mode the system NEVER sets human_approved=True autonomously.
    """
    svc = SafetyGateService()
    action = _shadow_mode_action({
        "action_id": "shadow-write-attempt-001",
        "action_type": "reboot",
        "allowed_action_types": ["reboot"],
        "risk_level": "HIGH",
        "human_approved": False,  # Shadow mode: no autonomous approval
    })

    decision = svc.evaluate(action, tenant_id="shadow-tenant")

    assert decision.approved is False, "HIGH-risk action without human approval must be BLOCKED"
    assert decision.gates_failed >= 1

    # Verify it is gate_6 (human_gate) that failed
    gate_names = [r.gate_name for r in decision.results if r.status == GateStatus.FAIL]
    assert "human_gate" in gate_names, f"Expected human_gate to fail, failed gates: {gate_names}"


# ---------------------------------------------------------------------------
# Test 4: SafetyGate passes read-only assessments (blast_radius=0, MEDIUM)
# ---------------------------------------------------------------------------

def test_safety_gate_passes_readonly_assessment():
    """
    A pure read-only assessment with 0 affected entities, LOW risk, and
    high confidence must pass all 7 gates — this is the only class of
    'action' that shadow mode takes autonomously.
    """
    svc = SafetyGateService()
    action = _shadow_mode_action()  # blast_radius=0, LOW risk, no writes

    decision = svc.evaluate(action, tenant_id="shadow-tenant")

    assert decision.approved is True, f"Read-only assessment must be APPROVED. Summary: {decision.summary()}"
    assert decision.gates_passed == 7
    assert decision.gates_failed == 0
    assert "APPROVED" in decision.summary()


# ---------------------------------------------------------------------------
# Test 5: PlaybookGenerator produces playbook data (pure data, no execution)
# ---------------------------------------------------------------------------

async def test_playbook_generator_produces_data_no_execution():
    """
    PlaybookGenerator.generate_playbook() must return a Playbook dataclass
    with populated steps and metadata. No DB writes, no external calls.
    The playbook is data-only — it does NOT execute any actions.
    """
    gen = get_playbook_generator()
    pattern = {
        "fault_pattern": "sleeping_cell",
        "avg_confidence": 0.94,
        "decision_ids": ["d-001", "d-002", "d-003"],
    }

    playbook = await gen.generate_playbook(pattern, tenant_id="shadow-tenant")

    assert isinstance(playbook, Playbook)
    assert playbook.playbook_id  # UUID string, non-empty
    assert playbook.fault_pattern == "sleeping_cell"
    assert playbook.domain == "RAN"
    assert playbook.confidence == 0.94
    assert len(playbook.steps) >= 1
    assert playbook.source_decision_ids == ["d-001", "d-002", "d-003"]

    # Verify no side-effects: times_applied stays 0 (shadow mode — not executed)
    assert playbook.times_applied == 0
    assert playbook.last_applied is None

    # Playbook must be serialisable to dict (used for internal SITREP display)
    pb_dict = playbook.to_dict()
    assert pb_dict["fault_pattern"] == "sleeping_cell"
    assert "steps" in pb_dict
    assert len(pb_dict["steps"]) >= 1


# ---------------------------------------------------------------------------
# Test 6: Full event→route→recommend flow (no writes)
# ---------------------------------------------------------------------------

async def test_full_shadow_mode_flow_event_route_recommend():
    """
    Full shadow mode pipeline:
      1. Publish anomaly event to EventBus (offline queue)
      2. Consume event and extract alarm metadata
      3. Route via SitrepRouter → RoutingDecision
      4. Evaluate via SafetyGate with read-only action → APPROVED
      5. Generate playbook recommendation
    No writes to any external system throughout.
    """
    bus = _make_bus()
    tenant_id = uuid.uuid4()
    event_type = "sleeping_cell.detected"

    # Step 1: Publish telemetry event (simulates Kafka tap in shadow mode)
    await bus.publish(event_type, {
        "cell_id": "RAN-SHADOW-001",
        "prb_utilization": 0.03,
        "severity": "high",
        "domain": "RAN",
    }, tenant_id)

    # Step 2: Consume event
    consumed: list[Event] = []

    async def _consume():
        async for event in bus.subscribe(event_type, "shadow-pipeline", "worker-1", tenant_id=str(tenant_id)):
            consumed.append(event)
            return

    await asyncio.wait_for(_consume(), timeout=2)
    assert len(consumed) == 1
    event = consumed[0]
    domain = event.payload["domain"]
    severity_str = event.payload["severity"]

    # Step 3: Route SITREP (internal only in shadow mode — not sent externally)
    router = get_sitrep_router()
    routing = router.route(
        sitrep_id=f"shadow-sitrep-{event.event_id}",
        entity_id=event.payload["cell_id"],
        domain=domain,
        severity=SeverityLevel(severity_str),
    )
    assert routing.assigned_tier == EscalationTier.NOC_ENGINEER
    assert routing.escalation_rule is not None

    # Step 4: Safety gate evaluation — read-only assessment only
    svc = SafetyGateService()
    action = _shadow_mode_action({
        "action_id": f"shadow-assess-{event.event_id}",
    })
    decision = svc.evaluate(action, tenant_id=str(tenant_id))
    assert decision.approved is True

    # Step 5: Generate playbook recommendation (recommendation only, not executed)
    gen = get_playbook_generator()
    pattern = {
        "fault_pattern": "sleeping_cell",
        "avg_confidence": 0.91,
        "decision_ids": [event.event_id],
    }
    playbook = await gen.generate_playbook(pattern, tenant_id=str(tenant_id))
    assert playbook.domain == "RAN"
    assert len(playbook.steps) >= 1


# ---------------------------------------------------------------------------
# Test 7: Shadow mode no-write constraint validation
# ---------------------------------------------------------------------------

def test_shadow_mode_no_write_constraint():
    """
    Validate the shadow mode no-write constraint across multiple action types
    that would represent writes to external systems.
    All must be BLOCKED by SafetyGate when risk_level=HIGH and no human approval.
    """
    svc = SafetyGateService()
    write_actions = [
        "reboot",
        "cell_reset",
        "parameter_change",
        "ticket_close",
        "config_push",
    ]

    for action_type in write_actions:
        action = _shadow_mode_action({
            "action_id": f"shadow-write-{action_type}",
            "action_type": action_type,
            "allowed_action_types": [action_type],  # Policy allows it but human gate blocks
            "risk_level": "HIGH",
            "human_approved": False,
        })
        decision = svc.evaluate(action, tenant_id="shadow-tenant")

        assert decision.approved is False, (
            f"Action '{action_type}' with risk_level=HIGH and no human approval "
            f"must be BLOCKED in shadow mode. Got: {decision.summary()}"
        )
        failed_gate_names = [r.gate_name for r in decision.results if r.status == GateStatus.FAIL]
        assert "human_gate" in failed_gate_names, (
            f"human_gate must fail for write action '{action_type}', "
            f"failed: {failed_gate_names}"
        )


# ---------------------------------------------------------------------------
# Test 8: Escalation path correctness for different severity/domain combos
# ---------------------------------------------------------------------------

def test_escalation_path_correctness_multiple_combos():
    """
    Verify escalation paths are correct across domain/severity combinations
    that are critical for shadow mode recommendation accuracy.
    """
    router = get_sitrep_router()

    # RAN HIGH → NOC_ENGINEER → NOC_MANAGER
    path = router.get_escalation_path("RAN", SeverityLevel.HIGH)
    assert path == [EscalationTier.NOC_ENGINEER, EscalationTier.NOC_MANAGER], (
        f"RAN HIGH escalation path wrong: {path}"
    )

    # RAN CRITICAL → NOC_ENGINEER → NOC_MANAGER (faster, 15 min)
    path = router.get_escalation_path("RAN", SeverityLevel.CRITICAL)
    assert path == [EscalationTier.NOC_ENGINEER, EscalationTier.NOC_MANAGER], (
        f"RAN CRITICAL escalation path wrong: {path}"
    )

    # Core CRITICAL → NOC_MANAGER → EXECUTIVE (most critical path)
    path = router.get_escalation_path("Core", SeverityLevel.CRITICAL)
    assert path == [EscalationTier.NOC_MANAGER, EscalationTier.EXECUTIVE], (
        f"Core CRITICAL escalation path wrong: {path}"
    )

    # Transport HIGH → NOC_ENGINEER → FIELD_TEAM (requires physical investigation)
    path = router.get_escalation_path("Transport", SeverityLevel.HIGH)
    assert path == [EscalationTier.NOC_ENGINEER, EscalationTier.FIELD_TEAM], (
        f"Transport HIGH escalation path wrong: {path}"
    )

    # Verify field_required for Transport
    field_domains = router.get_field_required_domains()
    assert "Transport" in field_domains

    # LOW severity on unknown domain → fallback NOC_ENGINEER only
    path = router.get_escalation_path("BSS", SeverityLevel.LOW)
    assert EscalationTier.NOC_ENGINEER in path


# ---------------------------------------------------------------------------
# Test 9 (bonus): SitrepRouter fallback for unknown domain+severity
# ---------------------------------------------------------------------------

def test_sitrep_router_fallback_unknown_domain():
    """
    An unknown domain with MEDIUM severity has no explicit rule.
    Router must fall back to NOC_ENGINEER with no escalation rule in the
    RoutingDecision (graceful degradation required for shadow mode robustness).
    """
    router = get_sitrep_router()
    decision = router.route(
        sitrep_id="sitrep-unknown-001",
        entity_id="entity-BSS-999",
        domain="BSS",
        severity=SeverityLevel.MEDIUM,
    )

    assert decision.assigned_tier == EscalationTier.NOC_ENGINEER
    assert decision.escalation_rule is None
    assert "NOC_ENGINEER" in decision.rationale.lower() or "noc_engineer" in decision.rationale.lower()


# ---------------------------------------------------------------------------
# Test 10 (bonus): PlaybookGenerator get_playbook_by_fault_pattern
# ---------------------------------------------------------------------------

async def test_playbook_generator_get_by_fault_pattern():
    """
    get_playbook_by_fault_pattern() must return a Playbook for known patterns
    and None for unknown ones. Used by shadow mode SITREP display to attach
    playbooks to recommendations without any DB access.
    """
    gen = get_playbook_generator()

    # Known pattern: sleeping_cell
    pb = await gen.get_playbook_by_fault_pattern("sleeping_cell_prb_degradation")
    assert pb is not None
    assert pb.domain == "RAN"
    assert pb.title == "Sleeping Cell Recovery Procedure"
    assert len(pb.steps) == 5

    # Known pattern: transport_degradation
    pb2 = await gen.get_playbook_by_fault_pattern("transport_degradation")
    assert pb2 is not None
    assert pb2.domain == "Transport"

    # Unknown pattern → None (shadow mode gracefully skips)
    pb_none = await gen.get_playbook_by_fault_pattern("completely_unknown_fault_xyz")
    assert pb_none is None

    # Markdown rendering must work (used for internal SITREP display)
    md = pb.to_markdown()
    assert "# Playbook:" in md
    assert "Sleeping Cell" in md
    assert "## Steps" in md
