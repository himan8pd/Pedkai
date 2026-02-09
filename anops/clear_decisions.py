"""
Script to clear decision traces for a specific tenant.
Used to clean up malformed records during testing.
"""

import asyncio
import sys
from pathlib import Path
from sqlalchemy import delete

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.app.core.database import get_db_context
from backend.app.models.decision_trace_orm import DecisionTraceORM

async def clear_decisions(tenant_id: str = "global-demo"):
    """Deletes all decision traces for the given tenant."""
    print(f"🗑️ Clearing decision traces for {tenant_id}...")
    
    async with get_db_context() as session:
        query = delete(DecisionTraceORM).where(DecisionTraceORM.tenant_id == tenant_id)
        await session.execute(query)
        await session.commit()
        print("✅ Cleared.")

if __name__ == "__main__":
    asyncio.run(clear_decisions())
