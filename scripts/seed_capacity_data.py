import asyncio
from datetime import datetime, timedelta
from sqlalchemy import select
from backend.app.core.database import get_db_context, engine, Base
from backend.app.models.kpi_orm import KPIMetricORM
from backend.app.models.investment_planning import DensificationRequestORM
from backend.app.services.capacity_engine import CapacityEngine

from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB, UUID

@compiles(JSONB, 'sqlite')
def compile_jsonb_sqlite(type_, compiler, **kw):
    return "JSON"

@compiles(UUID, 'sqlite')
def compile_uuid_sqlite(type_, compiler, **kw):
    return "VARCHAR(36)"

async def seed_capacity_data():
    print("🌱 Seeding data-driven capacity hotspots...")
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with get_db_context() as session:
        # 1. Seed some high-congestion KPIs
        metrics = []
        now = datetime.utcnow()
        for i in range(5):
            metrics.append({
                "tenant_id": "default",
                "entity_id": f"Cell-Pune-{i:03d}",
                "timestamp": now,
                "metric_name": "prb_utilization",
                "value": 0.88 + (i * 0.02), # 88% to 96%
                "tags": {"region": "Pune", "band": "3500MHz"}
            })
        
        await KPIMetricORM.bulk_insert(session, metrics)
        print(f"✅ Seeded {len(metrics)} hotspots.")

        # 2. Create a Densification Request
        request = DensificationRequestORM(
            tenant_id="default",
            region_name="Maharashtra-Pune",
            budget_limit=150000.0,
            target_kpi="prb_utilization",
            parameters={"priority": "high"}
        )
        session.add(request)
        await session.commit()
        await session.refresh(request)
        print(f"✅ Created request for {request.region_name} with $150k budget.")

        # 3. Trigger optimization
        engine_svc = CapacityEngine(session)
        plan = await engine_svc.optimize_densification(request.id)
        print(f"✅ Generated plan: {plan.rationale}")
        print(f"💰 Total Cost: ${plan.total_estimated_cost}")
        print(f"📍 Sites: {len(plan.site_placements)}")

if __name__ == "__main__":
    asyncio.run(seed_capacity_data())
