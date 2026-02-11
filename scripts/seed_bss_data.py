import asyncio
import sys
import os
import random
from uuid import uuid4
from datetime import datetime
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Load .env manually to fix pydantic-settings issue
try:
    from scripts.fix_env import load_env_manual
    load_env_manual()
except ImportError:
    print("⚠️ Could not import fix_env!")

from backend.app.core.database import get_db_context, engine, Base
from backend.app.models.bss_orm import ServicePlanORM, BillingAccountORM
from backend.app.models.customer_orm import CustomerORM

async def seed_bss_data():
    print("🌱 Seeding BSS Data (Service Plans & Billing Accounts)...")
    
    # Ensure tables exist and are empty
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Clean current BSS tables to ensure deterministic test data
        await conn.execute(text("DELETE FROM bss_billing_accounts"))
        await conn.execute(text("DELETE FROM bss_service_plans"))
    
    async with get_db_context() as session:
        # 1. Create Service Plans
        plans_data = [
            {"name": "Enterprise Gold 5G", "tier": "GOLD", "monthly_fee": 2500.0, "sla_guarantee": "99.999%"},
            {"name": "Business Silver 5G", "tier": "SILVER", "monthly_fee": 500.0, "sla_guarantee": "99.9%"},
            {"name": "Consumer Ultimate", "tier": "BRONZE", "monthly_fee": 85.0, "sla_guarantee": "Best Effort"},
            {"name": "IoT Basic", "tier": "BRONZE", "monthly_fee": 2.0, "sla_guarantee": "Best Effort"}
        ]
        
        created_plans = []
        for p_data in plans_data:
            existing = await session.execute(select(ServicePlanORM).where(ServicePlanORM.name == p_data["name"]))
            plan = existing.scalar_one_or_none()
            
            if not plan:
                plan = ServicePlanORM(**p_data)
                session.add(plan)
                print(f"   Created Plan: {plan.name}")
            else:
                print(f"   Plan exists: {plan.name}")
            
            created_plans.append(plan)
        
        await session.flush() # Ensure IDs are generated
        
        # 2. Assign Billing Accounts to Existing Customers
        customers_result = await session.execute(select(CustomerORM))
        customers = customers_result.scalars().all()
        
        if not customers:
            print("   ⚠️ No customers found! Creating a mock customer...")
            new_customer = CustomerORM(
                external_id="CUST-MOCK-001",
                name="Gold Enterprise Corp",
                churn_risk_score=0.1,
                associated_site_id="SITE-001",
                tenant_id="default",
                created_at=datetime.utcnow()
            )
            session.add(new_customer)
            await session.flush()
            customers = [new_customer]
            print(f"   Created Mock Customer: {new_customer.name}")
        
        print(f"   Found {len(customers)} customers to update.")
        
        for customer in customers:
            # Logic: Assign plan based on name or random
            if "Gold" in (customer.name or ""):
                plan = next((p for p in created_plans if p.tier == "GOLD"), created_plans[0])
            else:
                # Weighted random choice of plan
                plan = random.choices(created_plans, weights=[10, 30, 50, 10], k=1)[0]
            
            account = BillingAccountORM(
                customer_id=customer.id,
                plan_id=plan.id,
                account_status="ACTIVE",
                avg_monthly_revenue=plan.monthly_fee + random.uniform(0, 50), # Add some overage
                last_billing_dispute=None
            )
            session.add(account)
        
        await session.commit()
    
    print("✅ BSS Seeding Complete.")

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(seed_bss_data())
