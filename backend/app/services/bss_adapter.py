"""
BSS Adapter Abstraction Layer.

Analogous to data_fabric/alarm_normalizer.py for OSS.
Provides a vendor-agnostic interface for BSS integration.

The LocalBSSAdapter wraps the existing BSSService for the current SQLAlchemy-based implementation.
Future adapters: AmdocsBSSAdapter, CerillionBSSAdapter, CSGBSSAdapter.

Used by: WS4 (service_impact.py), WS2 (incidents.py).
"""
from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
from uuid import UUID
from pydantic import BaseModel


class BillingAccountInfo(BaseModel):
    """Standardised billing account response."""
    customer_id: UUID
    account_id: Optional[UUID] = None
    plan_name: Optional[str] = None
    monthly_fee: Optional[float] = None
    currency: str = "GBP"


class RevenueResult(BaseModel):
    """Revenue-at-risk calculation result. Uses 'unpriced' flag instead of fallback ARPU."""
    total_revenue_at_risk: Optional[float] = None
    priced_customer_count: int = 0
    unpriced_customer_count: int = 0
    requires_manual_valuation: bool = False


class BSSAdapter(ABC):
    """Abstract BSS adapter."""

    @abstractmethod
    async def get_billing_account(self, customer_id: UUID) -> Optional[BillingAccountInfo]:
        ...

    @abstractmethod
    async def get_revenue_at_risk(self, customer_ids: List[UUID]) -> RevenueResult:
        """
        Calculate revenue at risk.
        If billing data is unavailable for a customer, do NOT use a fallback ARPU.
        Instead, count them as 'unpriced' and set requires_manual_valuation=True.
        """
        ...

    @abstractmethod
    async def check_disputes(self, customer_ids: List[UUID]) -> List[UUID]:
        """Return customer IDs with recent billing disputes."""
        ...


class LocalBSSAdapter(BSSAdapter):
    """
    Wraps the existing BSSService (SQLAlchemy ORM) behind the adapter interface.
    """

    def __init__(self, session):
        from backend.app.services.bss_service import BSSService
        self._service = BSSService(session)

    async def get_billing_account(self, customer_id: UUID) -> Optional[BillingAccountInfo]:
        account = await self._service.get_account_by_customer_id(customer_id)
        if not account:
            return None
        return BillingAccountInfo(
            customer_id=customer_id,
            account_id=account.id,
            plan_name=account.service_plan.name if account.service_plan else None,
            monthly_fee=float(account.service_plan.monthly_fee) if account.service_plan else None,
        )

    async def get_revenue_at_risk(self, customer_ids: List[UUID]) -> RevenueResult:
        if not customer_ids:
            return RevenueResult()

        from sqlalchemy import text as sql_text
        id_strs = [str(cid) for cid in customer_ids]
        placeholders = ", ".join(f":id_{i}" for i in range(len(id_strs)))
        params = {f"id_{i}": id_strs[i] for i in range(len(id_strs))}
        result = await self._service.session.execute(
            sql_text(f"SELECT ba.customer_id, sp.monthly_fee FROM bss_accounts ba "
                     f"LEFT JOIN service_plans sp ON ba.service_plan_id = sp.id "
                     f"WHERE ba.customer_id IN ({placeholders})"),
            params
        )
        rows = {str(r[0]): r[1] for r in result.fetchall()}
        priced = [cid for cid in id_strs if rows.get(cid) is not None]
        unpriced = [cid for cid in id_strs if rows.get(cid) is None]
        total = sum(float(rows[cid]) for cid in priced) if priced else None
        return RevenueResult(
            total_revenue_at_risk=total,
            priced_customer_count=len(priced),
            unpriced_customer_count=len(unpriced),
            requires_manual_valuation=len(unpriced) > 0,
        )

    async def check_disputes(self, customer_ids: List[UUID]) -> List[UUID]:
        return await self._service.check_recent_disputes(customer_ids)


class MockBSSAdapter(BSSAdapter):
    """
    Lightweight in-memory mock adapter for testing and CI where real BSS is unavailable.
    """
    def __init__(self):
        # simple store for mocked accounts: customer_id -> monthly_fee
        self._accounts: dict[str, float] = {}

    async def get_billing_account(self, customer_id: UUID) -> Optional[BillingAccountInfo]:
        fee = self._accounts.get(str(customer_id))
        if fee is None:
            return None
        return BillingAccountInfo(customer_id=customer_id, monthly_fee=fee, currency="USD")

    async def get_revenue_at_risk(self, customer_ids: List[UUID]) -> RevenueResult:
        priced = [cid for cid in customer_ids if str(cid) in self._accounts]
        unpriced = [cid for cid in customer_ids if str(cid) not in self._accounts]
        total = sum(self._accounts.get(str(cid), 0.0) for cid in priced) if priced else None
        return RevenueResult(
            total_revenue_at_risk=total,
            priced_customer_count=len(priced),
            unpriced_customer_count=len(unpriced),
            requires_manual_valuation=len(unpriced) > 0,
        )

    async def check_disputes(self, customer_ids: List[UUID]) -> List[UUID]:
        # No disputes in mock by default
        return []
