import asyncio
import sys
import os
import json
import logging

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Load .env manually to fix pydantic-settings issue
try:
    from scripts.fix_env import load_env_manual
    load_env_manual()
except ImportError:
    print("⚠️ Could not import fix_env!")

from backend.app.services.policy_engine import policy_engine
from backend.app.services.llm_service import LLMService, get_llm_service
from backend.app.core.config import get_settings
from backend.app.core.database import get_db_context
from backend.app.models.customer_orm import CustomerORM
from sqlalchemy import select

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def verify_policy_enforcement():
    print("🚀 Verifying Phase 15: Strategic Pivot (Policy Engine)...")
    
    # 1. Test Policy Loading
    print("\n--- 1. Policy Loading ---")
    if not policy_engine.policies:
        print("❌ Failed to load policies!")
        return
    print(f"✅ Loaded {len(policy_engine.policies)} policies.")
    for p in policy_engine.policies:
        print(f"   - [{p.priority}] {p.name}: {p.action}")

    # 2. Test Policy Evaluation Logic (Direct)
    print("\n--- 2. Logic Evaluation ---")
    
    # Scenario A: Gold user in congestion (Should be PRIORITIZE)
    ctx_gold = {
        "service_type": "DATA",
        "customer_tier": "GOLD",
        "network_load": 90,
        "predicted_revenue_loss": 500
    }
    decision_gold = policy_engine.evaluate(ctx_gold)
    print(f"Scenario A (Gold + High Load): {decision_gold.required_actions}")
    assert "PRIORITIZE_TRAFFIC" in decision_gold.required_actions, "Gold traffic not prioritized!"
    print("✅ Gold Priority logic verified.")

    # Scenario B: Revenue Risk (Should require APPROVAL)
    ctx_revenue = {
        "service_type": "DATA",
        "customer_tier": "BRONZE",
        "network_load": 50,
        "predicted_revenue_loss": 15000
    }
    decision_revenue = policy_engine.evaluate(ctx_revenue)
    print(f"Scenario B (High Revenue Risk): {decision_revenue.required_actions}")
    assert "HUMAN_APPROVAL" in decision_revenue.required_actions, "High revenue risk did not trigger approval!"
    print("✅ Revenue Protection logic verified.")

    # 3. Test LLM Integration (End-to-End with real BSS context)
    print("\n--- 3. LLM Integration (BSS-Aware) ---")
    
    llm = get_llm_service()
    if not llm._provider:
        print("⚠️ LLM Provider not configured (Mocking response check). Skipping E2E LLM test.")
    else:
        async with get_db_context() as session:
            # Fetch real customers to test BSS lookup
            # Gold Customer (from seeding)
            result_gold = await session.execute(
                select(CustomerORM).where(CustomerORM.name == "Gold Enterprise Corp")
            )
            gold_cust = result_gold.scalar_one_or_none()
            
            # Use IDs if found, fallback to name-based if not (though seeding should have worked)
            impacted_ids = [str(gold_cust.id)] if gold_cust else []
            
            anomaly_payload = {
                "entity_name": "CELL_LON_001",
                "entity_type": "Cell",
                "metrics": {"load": 88},
                "impacted_customers": ["Gold Enterprise Corp"],
                "impacted_customer_ids": impacted_ids,
                "service_type": "DATA"
            }
            
            print(f"Invoking LLM Service with real Gold Customer ID: {impacted_ids}")
            sitrep = await llm.generate_explanation(
                incident_context=anomaly_payload,
                similar_decisions=[],
                causal_evidence=[],
                db_session=session
            )
            
            print("\n--- SITREP OUTPUT ---")
            print(sitrep)
            print("---------------------")
            
            if "POLICY APPLIED" in sitrep:
                print("✅ Policy section found in SITREP.")
                if "Gold" in sitrep or "Prioritizing" in sitrep:
                    print("✅ SITREP reflects priority awareness.")
            else:
                print("❌ Policy section MISSING from SITREP!")

if __name__ == "__main__":
    asyncio.run(verify_policy_enforcement())
