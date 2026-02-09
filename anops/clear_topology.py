"""
Script to clear network topology (entities and relationships).
"""

import asyncio
import sys
from pathlib import Path
from sqlalchemy import delete

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.app.core.database import get_db_context
from decision_memory.graph_orm import NetworkEntityORM, EntityRelationshipORM

async def clear_topology(tenant_id: str = "global-demo"):
    """Deletes all topology data for the given tenant."""
    print(f"🗑️ Clearing topology for {tenant_id}...")
    
    async with get_db_context() as session:
        # Delete relationships first due to FK (if any, though here it's likely manual)
        await session.execute(delete(EntityRelationshipORM).where(EntityRelationshipORM.tenant_id == tenant_id))
        await session.execute(delete(NetworkEntityORM).where(NetworkEntityORM.tenant_id == tenant_id))
        await session.commit()
        print("✅ Cleared.")

if __name__ == "__main__":
    asyncio.run(clear_topology())
