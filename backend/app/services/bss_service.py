from typing import List, Optional
from uuid import UUID
from sqlalchemy import select, func, and_, cast, Float
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from contextlib import asynccontextmanager
from sqlalchemy.orm import selectinload

from backend.app.models.bss_orm import BillingAccountORM, ServicePlanORM
from backend.app.models.customer_orm import CustomerORM

class BSSService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self.session_factory = session_factory

    @asynccontextmanager
    async def _get_session(self, session: Optional[AsyncSession] = None):
        if session:
            yield session
        else:
            async with self.session_factory() as new_session:
                try:
                    yield new_session
                    await new_session.commit()
                except Exception:
                    await new_session.rollback()
                    raise
                finally:
                    await new_session.close()

    async def get_account_by_customer_id(self, customer_id: UUID, session: Optional[AsyncSession] = None) -> Optional[BillingAccountORM]:
        """Retrieve the billing account for a specific customer."""
        async with self._get_session(session) as s:
            result = await s.execute(
                select(BillingAccountORM)
                .options(selectinload(BillingAccountORM.service_plan))
                .where(BillingAccountORM.customer_id == customer_id)
            )
            return result.scalar_one_or_none()

    async def calculate_revenue_at_risk(self, impacted_customer_ids: List[UUID], session: Optional[AsyncSession] = None) -> float:
        """
        Calculates total monthly revenue for a list of impacted customers.
        """
        if not impacted_customer_ids:
            return 0.0

        async with self._get_session(session) as s:
            result = await s.execute(
                select(func.sum(ServicePlanORM.monthly_fee))
                .join(BillingAccountORM, BillingAccountORM.plan_id == ServicePlanORM.id)
                .where(BillingAccountORM.customer_id.in_(impacted_customer_ids))
            )
            
            total_revenue = result.scalar()
            return float(total_revenue) if total_revenue else 0.0

    async def check_recent_disputes(self, customer_ids: List[UUID], session: Optional[AsyncSession] = None) -> List[UUID]:
        """
        Returns a list of customer IDs who have had a billing dispute in the last 30 days.
        """
        from datetime import datetime, timedelta, timezone
        thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
        
        async with self._get_session(session) as s:
            result = await s.execute(
                select(BillingAccountORM.customer_id)
                .where(
                    BillingAccountORM.customer_id.in_(customer_ids),
                    BillingAccountORM.last_billing_dispute >= thirty_days_ago
                )
            )
            return result.scalars().all()

    async def calculate_cumulative_active_risk(self, session: Optional[AsyncSession] = None) -> float:
        """
        Finding M-7 FIX: Sums 'predicted_revenue_loss' from all active decisions in last 1h.
        """
        from datetime import datetime, timedelta, timezone
        from backend.app.models.decision_trace_orm import DecisionTraceORM
        from sqlalchemy import cast, Float
        
        one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
        
        async with self._get_session(session) as s:
            query = select(func.sum(cast(DecisionTraceORM.context['predicted_revenue_loss'], Float)))
            
            result = await s.execute(
                query.where(and_(
                    DecisionTraceORM.created_at >= one_hour_ago,
                    DecisionTraceORM.outcome == None
                ))
            )
            total = result.scalar()
            return float(total) if total else 0.0
