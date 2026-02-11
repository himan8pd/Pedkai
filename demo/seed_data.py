import asyncio
import os
import sys
from uuid import uuid4

# Add the project root to sys.path so we can import backend.app
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text  # Added for text() queries

from backend.app.models.topology_models import EntityRelationshipORM
from backend.app.models.bss_orm import BillingAccountORM, ServicePlanORM, Base
from backend.app.models.customer_orm import CustomerORM
from backend.app.models.decision_trace_orm import DecisionTraceORM

DATABASE_URL = "postgresql+asyncpg://pedkai:secure_demo_password@localhost:5433/pedkai_demo"

async def seed_demo_data():
    engine = create_async_engine(DATABASE_URL)
    async with engine.begin() as conn:
        print("Creating tables...")
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
        # We also need to enable pgvector extension if not present (Postgres only)
        if engine.dialect.name == "postgresql":
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))

    async_session = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with async_session() as session:
        print("Seeding BSS Data...")
        
        # 1. Service Plans
        plan_gold = ServicePlanORM(id=uuid4(), name="Enterprise Gold", tier="GOLD", monthly_fee=500.0)
        plan_bronze = ServicePlanORM(id=uuid4(), name="Consumer Standard", tier="BRONZE", monthly_fee=40.0)
        session.add_all([plan_gold, plan_bronze])
        
        # 2. Topology (Defined by Relationships/Edges only)
        # Site-ABC -> Router-55 -> Cell-99
        print("Seeding Network Topology...")
        
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
        session.add_all([rel1, rel2])
        
        # 3. Customers
        print("Seeding Customers...")
        cust_gold = CustomerORM(
            id=uuid4(), external_id="CUST-GOLD-001", name="Gold Corp Ltd",
            associated_site_id="Cell-99", churn_risk_score=0.2
        )
        acc_gold = BillingAccountORM(
            id=uuid4(), customer_id=cust_gold.id, 
            plan_id=plan_gold.id, 
            last_billing_dispute=None
        )
        
        cust_bronze = CustomerORM(
            id=uuid4(), external_id="CUST-BRONZE-999", name="Joe Public",
            associated_site_id="Cell-99", churn_risk_score=0.8
        )
        acc_bronze = BillingAccountORM(
            id=uuid4(), customer_id=cust_bronze.id, 
            plan_id=plan_bronze.id, 
            last_billing_dispute=None
        )
        
        session.add_all([cust_gold, acc_gold, cust_bronze, acc_bronze])
        
        await session.commit()
        print("✅ Demo Data Seeded Successfully!")

if __name__ == "__main__":
    if "DATABASE_URL" in os.environ:
        DATABASE_URL = os.environ["DATABASE_URL"]
    asyncio.run(seed_demo_data())
