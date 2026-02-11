import asyncio
import os
import sys
import uuid
import random
from datetime import datetime, timezone

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from backend.app.services.llm_service import LLMService
from backend.app.models.decision_trace_orm import DecisionTraceORM
from backend.app.models.customer_orm import CustomerORM
from backend.app.services.policy_engine import policy_engine

DATABASE_URL = "postgresql+asyncpg://pedkai:secure_demo_password@localhost:5433/pedkai_demo"

# Mock the LLM Provider to avoid external API calls/costs during demo
from backend.app.services.llm_service import LLMProvider
class MockProvider(LLMProvider):
    async def generate(self, prompt: str) -> str:
        return f"\n[AI SITREP]: Based on the analysis of RCA data and Policy Guidelines...\n(Simulated AI Response for Prompt Length: {len(prompt)})"

async def run_scenarios():
    print("\n🚀 Starting Pedkai Demo Scenarios...\n" + "="*40)
    
    engine = create_async_engine(DATABASE_URL)
    async_session = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    # Patch LLM Service with Mock
    llm_service = LLMService()
    llm_service._provider = MockProvider()

    async with async_session() as session:
        # ------------------------------------------------------------------
        # SCENARIO 1: The "Happy Path" (Autonomous Resolution)
        # ------------------------------------------------------------------
        print("\n[SCENARIO 1] Standard Autonomous Remediation")
        print("Context: Standard anomaly at Cell-99 affecting Bronze customers.")
        
        ctx_1 = {
            "entity_name": "Cell-99", "entity_type": "cell",
            "impacted_customer_ids": [], # Bronze only (simulated)
            "service_type": "VOICE",
            "rca_results": "High interference on sector 3."
        }
        sitrep_1 = await llm_service.generate_explanation(ctx_1, [], db_session=session)
        print(f"Result: {sitrep_1}")
        
        # ------------------------------------------------------------------
        # SCENARIO 2: The "Amorphous" Incident (Entity Inference)
        # ------------------------------------------------------------------
        print("\n\n[SCENARIO 2] Amorphous Incident (Entity Inference)")
        print("Context: Anomaly with NO site_id, only affected_entities=['Cell-99'].")
        
        # Get customer ID for Gold Corp
        from sqlalchemy import select
        res = await session.execute(select(CustomerORM).where(CustomerORM.name == "Gold Corp Ltd"))
        gold_cust = res.scalar_one()
        
        ctx_2 = {
            "trigger_description": "Amorphous cluster fault",
            "affected_entities": ["Cell-99"], # No site_id
            "impacted_customer_ids": [gold_cust.id],
            "service_type": "DATA"
        }
        # We manually trigger inference logic (normally done in CX service, but LLM service uses BSS)
        # For the demo, we show the LLM recognizing the high value.
        sitrep_2 = await llm_service.generate_explanation(ctx_2, [], db_session=session)
        print(f"Result: {sitrep_2}")


        # ------------------------------------------------------------------
        # SCENARIO 3: "Death by a Thousand Cuts" (Cumulative Risk Blocking)
        # ------------------------------------------------------------------
        print("\n\n[SCENARIO 3] Cumulative Risk Attack (Death by a Thousand Cuts)")
        print("Context: 6 simultaneous anomalies, each risking $9,000 (Total $54k > $50k Limit)")
        
        # Seed 6 active decisions
        for i in range(6):
            trace = DecisionTraceORM(
                tenant_id="demo",
                trigger_type="anomaly",
                trigger_description=f"Minor event {i}",
                context={"predicted_revenue_loss": 9000},
                created_at=datetime.now(timezone.utc)
            )
            session.add(trace)
        await session.commit()
        print(" -> Seeded 6 active high-risk decisions into DB.")
        
        # Trigger the 7th event
        ctx_3 = {
            "entity_name": "Router-55",
            "predicted_revenue_loss": 1000,
            "service_type": "DATA"
        }
        sitrep_3 = await llm_service.generate_explanation(ctx_3, [], db_session=session)
        print(f"Result: {sitrep_3}")
        
        if "POLICY BLOCK" in sitrep_3:
             print("\n✅ SUCCESS: Policy Engine blocked cumulative risk!")
        else:
             print("\n❌ FAILURE: Policy Engine failed to block.")

if __name__ == "__main__":
    if "DATABASE_URL" in os.environ:
        DATABASE_URL = os.environ["DATABASE_URL"]
    asyncio.run(run_scenarios())
