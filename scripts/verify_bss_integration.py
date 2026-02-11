import asyncio
import sys
import os
import logging
from sqlalchemy import select

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Load .env manually to fix pydantic-settings issue
try:
    from scripts.fix_env import load_env_manual
    load_env_manual()
except ImportError:
    print("⚠️ Could not import fix_env!")


from backend.app.core.database import get_db_context, engine, Base
from backend.app.core.config import get_settings
from backend.app.services.bss_service import BSSService
from backend.app.models.customer_orm import CustomerORM
from backend.app.models.bss_orm import BillingAccountORM, ServicePlanORM
from sqlalchemy import func

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def verify_bss_integration():
    settings = get_settings()
    print(f"🚀 Verifying Phase 15.1: BSS Data Layer...")
    print(f"   DB URL: {settings.database_url}")
    
    # Ensure tables exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    async with get_db_context() as session:
        bss_service = BSSService(session)
        
        # Debug Counts
        c_count = await session.scalar(select(func.count()).select_from(CustomerORM))
        b_count = await session.scalar(select(func.count()).select_from(BillingAccountORM))
        print(f"   Debug: Customers={c_count}, BillingAccounts={b_count}")

        # 1. Fetch a customer with a Billing Account
        print("\n--- 1. Fetching Customer Context ---")
        result = await session.execute(
            select(CustomerORM)
            .join(BillingAccountORM)
            .limit(1)
        )
        customer = result.scalar_one_or_none()
        
        if not customer:
            print("❌ No customers with billing accounts found! (Did seeding work?)")
            return

        print(f"   Selected Customer: {customer.name} (ID: {customer.id})")
        
        # 2. Get Billing Account details
        account = await bss_service.get_account_by_customer_id(customer.id)
        if not account:
            print("❌ Failed to retrieve billing account via service!")
            return
            
        print(f"   Plan: {account.service_plan.name} ({account.service_plan.tier})")
        print(f"   Monthly Fee: ${account.service_plan.monthly_fee}")
        
        # 3. Test Revenue at Risk Calculation
        print("\n--- 2. Revenue at Risk Calculation ---")
        impacted_ids = [customer.id]
        revenue_risk = await bss_service.calculate_revenue_at_risk(impacted_ids)
        print(f"   Calculated Revenue Risk: ${revenue_risk}")
        
        expected_risk = account.service_plan.monthly_fee
        # Float comparison with tolerance
        if abs(revenue_risk - expected_risk) < 0.01:
            print("✅ Revenue calculation matches Service Plan fee.")
        else:
            print(f"❌ Revenue mismatch! Expected {expected_risk}, got {revenue_risk}")
            
        # 4. Test Dispute Check
        print("\n--- 3. Dispute History Check ---")
        disputes = await bss_service.check_recent_disputes(impacted_ids)
        print(f"   Customers with disputes: {len(disputes)}")
        # We didn't seed disputes, so this should be 0, but the call shouldn't crash
        print("✅ Dispute check executed successfully.")

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(verify_bss_integration())
