import asyncio
import pytest
from datetime import datetime
from backend.app.services.policy_engine import get_policy_engine, PolicyEngine
from backend.app.services.policy_engine import ActionDecision

@pytest.mark.asyncio
async def test_policy_engine_v2_evaluate_defaults(tmp_path, monkeypatch):
    engine = get_policy_engine()
    # Create a fake async session (None) — function should handle fallback defaults
    decision = await engine.evaluate_autonomous_action(
        session=None,
        tenant_id="tenant-test",
        action_type="cell_failover",
        entity_id="cell-1",
        affected_entity_count=2,
        action_parameters={"target_cell": "cell-2"},
        trace_id="trace-123",
        confidence_score=0.9,
    )
    assert decision.decision in ("allow", "deny")
    assert hasattr(decision, "matched_rules")
