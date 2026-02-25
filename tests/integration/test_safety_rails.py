import pytest
from backend.app.services.policy_engine import get_policy_engine

@pytest.mark.asyncio
async def test_policy_gate_blocks_invalid_action():
    engine = get_policy_engine()
    # Use default policy evaluation with low confidence to simulate block
    decision = await engine.evaluate_autonomous_action(
        session=None,
        tenant_id="tenant-test",
        action_type="forbidden_action",
        entity_id="e1",
        affected_entity_count=200,
        action_parameters={},
        trace_id="trace-1",
        confidence_score=0.1,
    )
    assert decision.decision == "deny"
