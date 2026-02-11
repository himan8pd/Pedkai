"""
Verification Script for Phase 15.4: Closed-Loop RL Evaluator

This script validates:
1. Automated feedback scoring after outcome recording.
2. Reward calculation for success/failure.
3. Penalty application for policy violations.
"""

import asyncio
import os
import sys
from uuid import uuid4

# Ensure path includes project root
project_root = "/Users/himanshu/Library/CloudStorage/GoogleDrive-himanshu@htadvisers.co.uk/My Drive/AI Learning/AntiGravity/Pedkai"
sys.path.append(project_root)

# Load environment variables
from scripts.fix_env import load_env_manual
load_env_manual()

from sqlalchemy import select, text
from backend.app.core.database import get_db_context, engine, Base
from backend.app.models.decision_trace import (
    DecisionTraceCreate,
    DecisionContext,
    DecisionOutcomeRecord,
    DecisionOutcome,
    DecisionTraceUpdate
)
from backend.app.services.decision_repository import DecisionTraceRepository

async def verify_rl_evaluator():
    print("--- Phase 15.4 Verification: Closed-Loop RL Evaluator ---")
    
    async with get_db_context() as session:
        repo = DecisionTraceRepository(session)
        tenant = "test-tenant-rl"
        
        # 1. Test Case: Policy-Compliant Success
        print("\n1. Testing Policy-Compliant Success (Expect +7: Success + Bonus)...")
        # Pol-001: Emergency Services Protection (ALLOW)
        d1_create = DecisionTraceCreate(
            tenant_id=tenant,
            trigger_type="alarm",
            trigger_description="Critical Emergency Site Down",
            context=DecisionContext(
                affected_entities=["EXCH_999"],
                external_context={"service_type": "EMERGENCY"}
            ),
            decision_summary="Restore emergency slice",
            tradeoff_rationale="Compliance requirement",
            action_taken="Flipped backup relay",
            decision_maker="pedkai:system",
            domain="anops"
        )
        d1 = await repo.create(d1_create)
        
        # Trigger record_outcome (via repo directly or API, here we simulate the logic)
        # Note: In real app, this happens at the API level.
        # We'll use the RLEvaluator manually to prove the logic, then maybe mock an API call if needed.
        from backend.app.services.rl_evaluator import get_rl_evaluator
        evaluator = get_rl_evaluator(session)
        
        # Record Success
        await repo.update(d1.id, DecisionTraceUpdate(
            outcome=DecisionOutcomeRecord(status=DecisionOutcome.SUCCESS, learnings="Restored.")
        ))
        
        # Re-fetch with outcome
        d1_updated = await repo.get_by_id(d1.id)
        reward = await evaluator.evaluate_decision_outcome(d1_updated)
        print(f"Calculated Reward: {reward}")
        await evaluator.apply_feedback(d1.id, reward)
        
        # Verify in DB
        res = await session.execute(text("SELECT score FROM decision_feedback WHERE decision_id = :id AND operator_id = 'pedkai:rl_evaluator'"), {"id": d1.id})
        db_score = res.scalar()
        print(f"Feedback stored in DB: {db_score}")
        
        if db_score == 7: # Success(5) + Constitutional Bonus(2)
            print("✅ Policy-Compliant Success rewarded correctly.")
        else:
            print(f"❌ Incorrect reward! Expected 7, got {db_score}")

        # 2. Test Case: Policy-Violating Success
        print("\n2. Testing Policy-Violating Success (Expect 0: Success + Violation)...")
        # POL-003: Revenue Protection (> $10k requires human approval)
        # If an AI takes an action that risks $15k without approval
        d2_create = DecisionTraceCreate(
            tenant_id=tenant,
            trigger_type="ai_action",
            trigger_description="Decommissioning cell for maintenance",
            context=DecisionContext(
                affected_entities=["CELL_PREMIUM"],
                external_context={
                    "predicted_revenue_loss": 15000, # Violated POL-003 REQUIRE_APPROVAL
                    "customer_tier": "GOLD"
                }
            ),
            decision_summary="Auto-decommission",
            tradeoff_rationale="Risked revenue for maintenance",
            action_taken="Deactivated Cell",
            decision_maker="pedkai:system",
            domain="anops"
        )
        d2 = await repo.create(d2_create)
        
        await repo.update(d2.id, DecisionTraceUpdate(
            outcome=DecisionOutcomeRecord(status=DecisionOutcome.SUCCESS, learnings="Maintenance done.")
        ))
        
        d2_updated = await repo.get_by_id(d2.id)
        reward = await evaluator.evaluate_decision_outcome(d2_updated)
        print(f"Calculated Reward: {reward}")
        await evaluator.apply_feedback(d2.id, reward)
        
        res = await session.execute(text("SELECT score FROM decision_feedback WHERE decision_id = :id AND operator_id = 'pedkai:rl_evaluator'"), {"id": d2.id})
        db_score = res.scalar()
        print(f"Feedback stored in DB: {db_score}")
        
        if db_score == 0: # Success(5) + Policy Violation(-5)
            print("✅ Policy-Violating Success neutralized correctly.")
        else:
            print(f"❌ Incorrect reward! Expected 0, got {db_score}")

        # 3. Test Case: Failure
        print("\n3. Testing Failure (Expect -15: Failure + Violation/No Bonus)...")
        # If it failed AND it was risky
        d3_create = DecisionTraceCreate(
            tenant_id=tenant,
            trigger_type="ai_action",
            trigger_description="Risky Reset",
            context=DecisionContext(
                affected_entities=["CELL_X"],
                external_context={"predicted_revenue_loss": 20000}
            ),
            decision_summary="Reset",
            tradeoff_rationale="Reboot",
            action_taken="Power cycle",
            decision_maker="pedkai:system",
            domain="anops"
        )
        d3 = await repo.create(d3_create)
        
        await repo.update(d3.id, DecisionTraceUpdate(
            outcome=DecisionOutcomeRecord(status=DecisionOutcome.FAILURE, learnings="Still down.")
        ))
        
        d3_updated = await repo.get_by_id(d3.id)
        reward = await evaluator.evaluate_decision_outcome(d3_updated)
        print(f"Calculated Reward: {reward}")
        await evaluator.apply_feedback(d3.id, reward)
        
        res = await session.execute(text("SELECT score FROM decision_feedback WHERE decision_id = :id AND operator_id = 'pedkai:rl_evaluator'"), {"id": d3.id})
        db_score = res.scalar()
        print(f"Feedback stored in DB: {db_score}")
        
        if db_score == -15: # Failure(-10) + Violation(-5)
            print("✅ Decision Failure penalized correctly.")
        else:
            print(f"❌ Incorrect reward! Expected -15, got {db_score}")

if __name__ == "__main__":
    asyncio.run(verify_rl_evaluator())
