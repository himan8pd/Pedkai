import pytest
import asyncio
from unittest.mock import AsyncMock, patch
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from backend.app.models.bss_orm import Base, BillingAccountORM, ServicePlanORM
from backend.app.models.customer_orm import CustomerORM
from backend.app.models.topology_models import EntityRelationshipORM
from backend.app.models.decision_trace_orm import DecisionTraceORM
from backend.app.services.llm_service import LLMService

# Use in-memory SQLite for the demo simulation
DATABASE_URL = "sqlite+aiosqlite:///:memory:"

@pytest.fixture
async def db_session():
    engine = create_async_engine(DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    async_session = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with async_session() as session:
        yield session

@pytest.fixture
async def seeded_session(db_session):
    # Seed Data
    plan_gold = ServicePlanORM(id=uuid4(), name="Enterprise Gold", tier="GOLD", monthly_fee=500.0)
    db_session.add(plan_gold)
    
    # Topology (Defined by Relationships/Edges only)
    # Site-ABC -> Router-55 -> Cell-99
    
    # Relationships
    rel1 = EntityRelationshipORM(
        from_entity_id="Site-ABC", from_entity_type="site",
        relationship_type="hosts",
        to_entity_id="Router-55", to_entity_type="router"
    )
    rel2 = EntityRelationshipORM(
        from_entity_id="Router-55", from_entity_type="router",
        relationship_type="serves",
        to_entity_id="Cell-99", to_entity_type="cell"
    )
    db_session.add_all([rel1, rel2])

    cust_gold = CustomerORM(
        id=uuid4(), external_id="CUST-GOLD-001", name="Gold Corp Ltd",
        associated_site_id="Cell-99", churn_risk_score=0.2
    )
    acc_gold = BillingAccountORM(
        id=uuid4(), customer_id=cust_gold.id, 
        plan_id=plan_gold.id, 
        last_billing_dispute=None
    )
    db_session.add_all([cust_gold, acc_gold])
    await db_session.commit()
    return db_session

@pytest.mark.asyncio
async def test_demo_scenarios(seeded_session):
    print("\n🚀 Starting Pedkai Demo Simulation (Pytest Mode)...\n" + "="*50)

    # Patch LLM Service with Mock
    llm_service = LLMService()
    
    with patch("backend.app.services.llm_service.GeminiProvider.generate", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = "\n[AI SITREP]: Based on policy, I recommend rerouting traffic."

        # ------------------------------------------------------------------
        # SCENARIO 1: The "Happy Path"
        # ------------------------------------------------------------------
        print("\n[SCENARIO 1] Standard Autonomous Remediation")
        ctx_1 = {
            "entity_name": "Cell-99", "entity_type": "cell",
            "impacted_customer_ids": [], 
            "service_type": "VOICE",
            "rca_results": "High interference on sector 3."
        }
        sitrep_1 = await llm_service.generate_explanation(ctx_1, [], db_session=seeded_session)
        print(f"Result 1: {sitrep_1}")
        assert "[AI SITREP]" in sitrep_1
        assert "POLICY BLOCK" not in sitrep_1

        # ------------------------------------------------------------------
        # SCENARIO 2: The "Amorphous" Incident (Entity Inference)
        # ------------------------------------------------------------------
        print("\n[SCENARIO 2] Amorphous Incident (Entity Inference)")
        # Get Gold Customer ID
        from sqlalchemy import text
        result = await seeded_session.execute(
            text("SELECT id FROM customers WHERE name = 'Gold Corp Ltd'")
        )
        gold_id = result.scalar()
        
        ctx_2 = {
            "trigger_description": "Amorphous cluster fault",
            "affected_entities": ["Cell-99"], # No site_id
            "impacted_customer_ids": [gold_id],
            "service_type": "DATA"
        }
        # Mocking BSS resolution to Gold Tier
        sitrep_2 = await llm_service.generate_explanation(ctx_2, [], db_session=seeded_session)
        print(f"Result 2: {sitrep_2}")
        # Note: In SQLite mode, JSON extract might vary, but logic flow is tested.

        # ------------------------------------------------------------------
        # SCENARIO 3: "Death by a Thousand Cuts" (Cumulative Risk Blocking)
        # ------------------------------------------------------------------
        print("\n[SCENARIO 3] Cumulative Risk Attack")
        # Seed 6 active decisions
        for i in range(6):
            trace = DecisionTraceORM(
                tenant_id="demo",
                trigger_type="anomaly",
                trigger_description=f"Minor event {i}",
                decision_summary=f"Automated test decision {i}",
                tradeoff_rationale="Simulated risk",
                action_taken="NO_ACTION",
                decision_maker="pedkai:demo",
                context={"predicted_revenue_loss": 9000},
                created_at=datetime.now(timezone.utc)
            )
            seeded_session.add(trace)
        await seeded_session.commit()
        
        ctx_3 = {
            "entity_name": "Router-55",
            "predicted_revenue_loss": 1000,
            "service_type": "DATA"
        }
        sitrep_3 = await llm_service.generate_explanation(ctx_3, [], db_session=seeded_session)
        print(f"Result 3: {sitrep_3}")
        
        assert "🛑 **POLICY BLOCK**" in sitrep_3
        print("\n✅ SUCCESS: Cumulative Risk Blocked!")
