import pytest
import uuid
from datetime import datetime, timezone, timedelta
from backend.app.services.llm_service import get_llm_service
from backend.app.models.decision_trace_orm import DecisionTraceORM
from backend.app.services.policy_engine import get_policy_engine

@pytest.mark.asyncio
async def test_cumulative_risk_protection(db_session):
    """Finding M-7: Verify that 'Death by a Thousand Cuts' is blocked."""
    llm_service = get_llm_service()
    
    # 1. Seed 6 active decisions, each with $9,000 risk (Total: $54,000)
    # This should exceed POL-005's $50,000 limit.
    for i in range(6):
        trace = DecisionTraceORM(
            tenant_id="test",
            trigger_type="anomaly",
            trigger_description=f"Minor event {i}",
            decision_summary=f"Automated test decision {i}",
            tradeoff_rationale="Simulated risk for cumulative test",
            action_taken="NO_ACTION",
            decision_maker="pedkai:test_suite",
            context={"predicted_revenue_loss": 9000},
            created_at=datetime.now(timezone.utc)
        )
        db_session.add(trace)
    
    await db_session.commit()
    
    # 2. Trigger an explanation for a NEW incident
    context = {
        "entity_name": "Test-Node",
        "entity_type": "cell",
        "impacted_customer_ids": [], # No additional risk here
        "service_type": "DATA"
    }
    
    # 3. Generate SITREP (Mock LLM call to avoid 429/Token Quota)
    from unittest.mock import patch, AsyncMock
    with patch("backend.app.services.llm_adapter.GeminiAdapter.generate", new_callable=AsyncMock) as mock_gen:
        from backend.app.services.llm_adapter import LLMResponse
        mock_gen.return_value = LLMResponse(
            text="This is a dummy SITREP for policy testing.",
            model_version="gemini-test",
            prompt_hash="abc",
            timestamp=datetime.now(timezone.utc),
            provider="gemini"
        )
        sitrep_resp = await llm_service.generate_sitrep(context, [], session=db_session)
        sitrep = sitrep_resp.get("text", "")
    
    # 4. Assert POLICY BLOCK
    # The policy engine should have blocked the real LLM call and returned a block message
    # or the sitrep should contain the policy section.
    assert "🛑 **POLICY BLOCK**" in sitrep
    assert "Cumulative Revenue Protection" in sitrep
    print("Successfully blocked autonomous action due to cumulative risk threshold breach!")
