from typing import List, Optional
from uuid import UUID
from sqlalchemy import select, func, and_, cast, Float
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.models.bss_orm import BillingAccountORM, ServicePlanORM
from backend.app.models.customer_orm import CustomerORM

class BSSService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_account_by_customer_id(self, customer_id: UUID) -> Optional[BillingAccountORM]:
        """Retrieve the billing account for a specific customer."""
        result = await self.session.execute(
            select(BillingAccountORM)
            .options(selectinload(BillingAccountORM.service_plan))
            .where(BillingAccountORM.customer_id == customer_id)
        )
        return result.scalar_one_or_none()

    async def calculate_revenue_at_risk(self, impacted_customer_ids: List[UUID]) -> float:
        """
        Calculates total monthly revenue for a list of impacted customers.
        This represents the 'Value at Risk' for the anomaly.
        """
        if not impacted_customer_ids:
            return 0.0

        result = await self.session.execute(
            select(func.sum(ServicePlanORM.monthly_fee))
            .join(BillingAccountORM, BillingAccountORM.plan_id == ServicePlanORM.id)
            .where(BillingAccountORM.customer_id.in_(impacted_customer_ids))
        )
        
        total_revenue = result.scalar()
        return float(total_revenue) if total_revenue else 0.0

    async def check_recent_disputes(self, customer_ids: List[UUID]) -> List[UUID]:
        """
        Returns a list of customer IDs who have had a billing dispute in the last 30 days.
        Used to escalate priority for 'fragile' customers.
        """
        from datetime import datetime, timedelta, timezone
        thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
        
        result = await self.session.execute(
            select(BillingAccountORM.customer_id)
            .where(
                BillingAccountORM.customer_id.in_(customer_ids),
                BillingAccountORM.last_billing_dispute >= thirty_days_ago
            )
        )
        return result.scalars().all()

    async def calculate_cumulative_active_risk(self) -> float:
        """
        Finding M-7 FIX: Sums 'predicted_revenue_loss' from all active decisions in last 1h.
        Used to prevent 'Death by a Thousand Cuts'.
        """
        from datetime import datetime, timedelta, timezone
        from backend.app.models.decision_trace_orm import DecisionTraceORM
        from sqlalchemy import cast, Float
        import json
        
        one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
        
        # Finding M-7: Multi-DB JSON extraction
        # SQLAlchemy handles DecisionTraceORM.context['key'] -> json_extract in SQLite
        # and as_text handles the cast to string/numeric
        query = select(func.sum(cast(DecisionTraceORM.context['predicted_revenue_loss'], Float)))
        
        result = await self.session.execute(
            query.where(and_(
                DecisionTraceORM.created_at >= one_hour_ago,
                DecisionTraceORM.outcome == None
            ))
        )
        total = result.scalar()
        return float(total) if total else 0.0
