import pytest
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from backend.app.models.kpi_orm import KPIMetricORM
from backend.app.models.decision_trace_orm import DecisionTraceORM
from backend.app.services.rl_evaluator import get_rl_evaluator
from backend.app.services.policy_engine import get_policy_engine
from backend.app.models.decision_trace import DecisionTrace, DecisionContext, DecisionOutcome, DecisionOutcomeRecord

@pytest.mark.asyncio
async def test_rl_evaluator_closed_loop_logic(db_session):
    """
    Verifies that the RL Evaluator correctly queries KCIs to calculate rewards.
    Finding C-2 Verification.
    """
    evaluator = get_rl_evaluator(db_session)
    entity_id = "cell-001"
    
    # TIMESTAMP SETUP
    now = datetime.now(timezone.utc)
    decision_time = now - timedelta(hours=1)
    
    # 1. Seed Pre-Decision Metrics (Baseline: High Congestion)
    # 30 mins before decision
    for i in range(5):
        m = KPIMetricORM(
            entity_id=entity_id,
            tenant_id="test",
            metric_name="prb_utilization",
            value=0.90, # 90% congestion
            timestamp=decision_time - timedelta(minutes=10 + i)
        )
        db_session.add(m)
        
    # 2. Seed Post-Decision Metrics (Improvement: Low Congestion)
    # 30 mins after decision
    for i in range(5):
        m = KPIMetricORM(
            entity_id=entity_id,
            tenant_id="test",
            metric_name="prb_utilization",
            value=0.50, # 50% congestion (Huge improvement)
            timestamp=decision_time + timedelta(minutes=10 + i)
        )
        db_session.add(m)
        
    await db_session.commit()
    
    # 3. Create Decision Trace
    trace = DecisionTrace(
        id=uuid4(),
        tenant_id="test",
        created_at=decision_time,
        decision_made_at=decision_time,
        trigger_type="anomaly",
        trigger_description="High PRB Congestion",
        decision_summary="Added capacity",
        tradeoff_rationale="Cost vs performance",
        action_taken="add_capacity",
        decision_maker="AI",
        context=DecisionContext(affected_entities=[entity_id]),
        outcome=DecisionOutcomeRecord(status=DecisionOutcome.SUCCESS)
    )
    
    # 4. Evaluate (should be SUCCESS since 44% improvement > 10% default threshold)
    reward = await evaluator._calculate_kpi_improvement_reward(trace)
    assert reward >= 5
    
    # 5. TEST GOVERNANCE: Raise threshold in Policy Engine to 50%
    engine = get_policy_engine()
    engine.parameters["rl_reward_improvement_threshold"] = 0.50
    
    # Re-evaluate: 44% is now BELOW the 50% threshold. Reward should be 0.
    reward_stricter = await evaluator._calculate_kpi_improvement_reward(trace)
    print(f"Reward with 50% threshold: {reward_stricter}")
    assert reward_stricter == 0
    
    # Cleanup: Reset threshold
    engine.parameters["rl_reward_improvement_threshold"] = 0.10
