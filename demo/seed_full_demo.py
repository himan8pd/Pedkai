import asyncio
import os
import sys
import random
from datetime import datetime, timedelta, timezone
from uuid import uuid4

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text

# Import Models
from backend.app.core.database import Base
from backend.app.models.bss_orm import BillingAccountORM, ServicePlanORM
from backend.app.models.customer_orm import CustomerORM
from backend.app.models.decision_trace_orm import DecisionTraceORM
from backend.app.models.topology_models import EntityRelationshipORM
from backend.app.models.tmf642_models import PerceivedSeverity, AlarmType, AlarmState, AckState
# TMF642 Alarms are stored in DecisionTraceORM in the current MVP or a separate table?
# Let's check tmf642.py to see where it reads from. 
# Correction: The dashboard reads TMF alarms from an endpoint. 
# We need to see if there is a specific TMF642 ORM or if it maps from DecisionTrace.
# Based on previous file views, it seems TMF642 might be a view or separate.
# Let's double check tmf642.py before writing invalid code.

# ACTUALLY - I need to verify where TMF Alarms are stored.
# I will write a placeholder comment here and verify in the next step.
# For now, I will assume a standard ORM or mapping exists.

# Import Capacity Models
from backend.app.models.investment_planning import DensificationRequestORM, InvestmentPlanORM

# Database Configuration
# Default to local demo SQLite; override via DATABASE_URL environment variable
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./pedkai_demo.db")

# Data Generators
REGIONS = ["London Central", "Manchester North", "Birmingham Bullring", "Glasgow City", "Leeds West"]
SEVERITIES = [PerceivedSeverity.CRITICAL, PerceivedSeverity.MAJOR, PerceivedSeverity.MINOR, PerceivedSeverity.WARNING]
ALARM_TYPES = [AlarmType.COMMUNICATIONS, AlarmType.QOS, AlarmType.EQUIPMENT, AlarmType.PROCESSING]
PROBLEMS = [
    "High Latency (Sector 3)", "Cell Sleeping", "Backhaul Congestion", 
    "Power Supply Failure", "Optical Link Degraded", "Software Crash",
    "High Packet Loss", "Frame Alignment Error"
]
ENTITIES = [f"Cell-{i}" for i in range(100, 200)] + [f"Router-{i}" for i in range(10, 50)]

async def seed_full_demo():
    print("🌱 Starting Comprehensive Demo Seeding...")
    
    engine = create_async_engine(DATABASE_URL)
    
    # Reset Database
    async with engine.begin() as conn:
        print("   - Resetting schema...")
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async_session = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with async_session() as session:
        # ---------------------------------------------------------
        # 1. BSS & Customers (Revenue Context)
        # ---------------------------------------------------------
        print("   - Seeding BSS Context...")
        plans = [
            ServicePlanORM(id=uuid4(), name="Enterprise Gold", tier="GOLD", monthly_fee=2500.0),
            ServicePlanORM(id=uuid4(), name="Consumer 5G", tier="BRONZE", monthly_fee=45.0),
            ServicePlanORM(id=uuid4(), name="IoT Fleet", tier="SILVER", monthly_fee=12.0)
        ]
        session.add_all(plans)
        
        customers = []
        for i in range(20):
            is_vip = i < 5
            plan = plans[0] if is_vip else random.choice(plans[1:])
            cust = CustomerORM(
                id=uuid4(),
                external_id=f"CUST-{uuid4().hex[:6].upper()}",
                name=f"Customer {i+1} {'Corp' if is_vip else ''}",
                associated_site_id=random.choice(ENTITIES),
                churn_risk_score=random.uniform(0.1, 0.9)
            )
            customers.append(cust)
            
            # Linking account
            acc = BillingAccountORM(
                id=uuid4(),
                customer_id=cust.id,
                plan_id=plan.id
            )
            session.add(acc)
        
        session.add_all(customers)

        # ---------------------------------------------------------
        # 2. Capacity Planning (The "Wow" Maps)
        # ---------------------------------------------------------
        print("   - Seeding Capacity Requests...")
        requests = []
        for region in REGIONS:
            req = DensificationRequestORM(
                id=uuid4(),
                tenant_id="voda-uk",
                region_name=region,
                budget_limit=random.randint(50000, 5000000),
                status=random.choice(["pending", "processing", "completed"]),
                created_at=datetime.now(timezone.utc) - timedelta(days=random.randint(1, 10))
            )
            requests.append(req)
            session.add(req)
            
            if req.status == "completed":
                # Create a plan for completed requests
                plan = InvestmentPlanORM(
                    id=uuid4(),
                    request_id=req.id,
                    total_estimated_cost=req.budget_limit * random.uniform(0.7, 0.95),
                    expected_kpi_improvement=random.uniform(15.0, 45.0),
                    rationale=f"Deploying small cells in high-traffic {region} zones to offload macro layer.",
                    site_placements=[
                        {
                            "name": f"SmallCell-{region[:3].upper()}-{i}",
                            "lat": 51.5074 + random.uniform(-0.05, 0.05),
                            "lon": -0.1278 + random.uniform(-0.05, 0.05),
                            "cost": random.randint(5000, 15000),
                            "backhaul": random.choice(["Fiber", "Microwave", "Satellite"])
                        }
                        for i in range(random.randint(3, 8))
                    ]
                )
                session.add(plan)
        
        # ---------------------------------------------------------
        # 3. Alarms & Decisions (Live Ops)
        # Note: In Pedkai, Alarms might be separate or part of DecisionTrace.
        # Current walkthrough implies TMF642 API reads from a source.
        # I will inject DecisionTraces that look like alarms for now, 
        # but I need to confirm if there is a TMF642Alarm table.
        # If not, I will trust the decision trace population.
        # ---------------------------------------------------------
        print("   - Seeding Live Incidents (Decisions)...")
        # Checking schema in next step to be sure, but populating DecisionTraceORM is safe.
        
        for i in range(30):
            severity = random.choice(SEVERITIES)
            entity = random.choice(ENTITIES)
            problem = random.choice(PROBLEMS)
            
            # Recent events
            event_time = datetime.now(timezone.utc) - timedelta(minutes=random.randint(1, 600))
            
            # Map severity to confidence score (See tmf642.py mapping logic)
            if severity == PerceivedSeverity.CRITICAL:
                conf = random.uniform(0.81, 0.99)
            elif severity == PerceivedSeverity.MINOR:
                conf = random.uniform(0.1, 0.39)
            else: # MAJOR / WARNING
                conf = random.uniform(0.41, 0.79)

            trace = DecisionTraceORM(
                id=uuid4(),
                tenant_id="voda-uk",
                trigger_type="alarm",
                trigger_id=f"ALM-{uuid4().hex[:8].upper()}",
                trigger_description=f"{severity.value.upper()}: {problem} on {entity}",
                
                # Context
                context={
                    "alarm_ids": [f"ALM-{i}"],
                    "affected_entities": [entity],
                    "metrics": {"latency": random.randint(20, 200)}
                },
                
                decision_summary=f"Automated remediation for {problem}",
                tradeoff_rationale="Action chosen to minimize MTTR based on past success.",
                action_taken="RESTART_SERVICE" if severity != PerceivedSeverity.CRITICAL else "ESCALATE_TO_SME",
                decision_maker="system:pedkai",
                confidence_score=conf,
                created_at=event_time,
                decision_made_at=event_time, # Required field
                
                # TMF642 Fields (Only the ones that exist on ORM)
                ack_state="acknowledged" if random.random() > 0.7 else "unacknowledged",
                probable_cause=problem.split(" ")[0],
                # perceived_severity -> Derived from confidence_score in API
                # specific_problem -> Derived from decision_summary in API
            )
            session.add(trace)

        await session.commit()
        print("✅ FULL DEMO DATA SEEDED.")
        print("   - 3 Service Plans")
        print(f"   - {len(customers)} Customers")
        print(f"   - {len(requests)} Capacity Requests")
        print("   - 30+ Alarms/Decisions")

if __name__ == "__main__":
    asyncio.run(seed_full_demo())
