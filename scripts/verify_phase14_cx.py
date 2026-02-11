"""
Verification Script for Phase 14: Customer Experience Intelligence.
Seeds test data and validates the CX correlation logic.
"""
import asyncio
import uuid
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgresUUID
from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, String, Text

# --- SQLite Compliance Patches ---
@compiles(JSONB, 'sqlite')
def compile_jsonb_sqlite(type_, compiler, **kw):
    return "JSON"

@compiles(Vector, 'sqlite')
def compile_vector_sqlite(type_, compiler, **kw):
    return "TEXT"

@compiles(PostgresUUID, 'sqlite')
def compile_uuid_sqlite(type_, compiler, **kw):
    return "VARCHAR(36)"

from backend.app.core.database import engine, Base, get_db_context
from backend.app.models.customer_orm import CustomerORM, ProactiveCareORM
from backend.app.models.decision_trace_orm import DecisionTraceORM
from backend.app.services.cx_intelligence import CXIntelligenceService

async def verify_cx_flow():
    print("🚀 Verifying Phase 14: Customer Experience Intelligence...")

    # 1. Initialize Tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with get_db_context() as session:
        # 2. Seed Test Customers
        site_id = "Site-VERIFY-14"
        customers = [
            CustomerORM(
                external_id="CUST-HIGH-001",
                name="Alice HighRisk",
                churn_risk_score=0.95,
                associated_site_id=site_id
            ),
            CustomerORM(
                external_id="CUST-LOW-002",
                name="Bob LowRisk",
                churn_risk_score=0.20,
                associated_site_id=site_id
            ),
            CustomerORM(
                external_id="CUST-OTHER-003",
                name="Charlie OtherSite",
                churn_risk_score=0.99,
                associated_site_id="Site-B"
            )
        ]
        session.add_all(customers)
        await session.commit()
        print("✅ Seeded test customers (1 high risk on site, 1 low risk on site, 1 high risk other site).")

        # 3. Seed an Anomaly
        anomaly = DecisionTraceORM(
            tenant_id="default",
            trigger_type="anomaly",
            trigger_description=f"Critical congestion on {site_id}",
            decision_summary="Optimization required",
            tradeoff_rationale="CX prioritized",
            action_taken="Load balanced",
            decision_maker="AI",
            domain="anops",
            context={"site_id": site_id}
        )
        session.add(anomaly)
        await session.commit()
        await session.refresh(anomaly)
        print(f"✅ Seeded anomaly for {site_id} (ID: {anomaly.id})")

        # 4. Run Impact Analysis
        service = CXIntelligenceService(session)
        impacted = await service.identify_impacted_customers(anomaly.id)
        
        print(f"🔍 Impact Analysis Result: Found {len(impacted)} impacted customers.")
        for c in impacted:
             print(f"   - Impacted: {c.name} (Risk: {c.churn_risk_score})")

        # Assertions
        assert len(impacted) == 1, f"Expected 1 impacted customer, found {len(impacted)}"
        assert impacted[0].external_id == "CUST-HIGH-001", "Wrong customer identified"

        # 5. Trigger Proactive Care
        c_ids = [c.id for c in impacted]
        records = await service.trigger_proactive_care(c_ids, anomaly.id)
        print(f"📢 Proactive Care Result: {len(records)} notifications triggered.")
        
        assert len(records) == 1
        assert records[0].status == "sent"

    print("\n✨ Phase 14 Verification SUCCESSFUL!")

if __name__ == "__main__":
    asyncio.run(verify_cx_flow())
