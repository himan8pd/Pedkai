import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.app.core.database import get_db_context
from backend.app.models.kpi_orm import KPIMetricORM
from backend.app.models.decision_trace_orm import DecisionTraceORM
from sqlalchemy import select, func

async def check():
    async with get_db_context() as session:
        m_count_res = await session.execute(select(func.count(KPIMetricORM.id)))
        d_count_res = await session.execute(select(func.count(DecisionTraceORM.id)))
        
        m_count = m_count_res.scalar()
        d_count = d_count_res.scalar()
        
        print(f"KPI Metrics count: {m_count}")
        print(f"Decision Traces count: {d_count}")
        
        # Check last 5 metrics to ensure timestamp/id format is correct
        recent_m = await session.execute(select(KPIMetricORM).order_by(KPIMetricORM.timestamp.desc()).limit(5))
        print("\nRecent Metrics:")
        for row in recent_m.all():
            m = row[0]
            print(f"  - {m.timestamp} | {m.entity_id} | {m.metric_name} = {m.value}")

if __name__ == "__main__":
    asyncio.run(check())
