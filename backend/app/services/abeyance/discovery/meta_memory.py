"""
Meta-Memory — Layer 5, Mechanism #13 (LLD v3.0 §10.3).

Feedback Loop B: tracks per-area productivity and adjusts exploration
bias allocation across failure modes and topological regions.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.abeyance_v3_orm import (
    MetaMemoryAreaORM,
    MetaMemoryProductivityORM,
    MetaMemoryBiasORM,
    MetaMemoryTenantStateORM,
    MetaMemoryJobRunORM,
    SnapOutcomeFeedbackORM,
)

logger = logging.getLogger(__name__)

ACTIVATION_THRESHOLD = 50  # Min labeled outcomes to activate
SMOOTHING_ALPHA = 0.2
PRODUCTIVITY_EPSILON = 0.01


class MetaMemoryService:
    """Manages exploration bias allocation based on area productivity."""

    async def check_activation(
        self,
        session: AsyncSession,
        tenant_id: str,
    ) -> bool:
        """Check if meta-memory should be activated for this tenant."""
        state = await self._get_or_create_state(session, tenant_id)
        if state.activation_status == "ACTIVE":
            return True

        # Count labeled outcomes
        count_stmt = (
            select(func.count())
            .select_from(SnapOutcomeFeedbackORM)
            .where(SnapOutcomeFeedbackORM.tenant_id == tenant_id)
        )
        result = await session.execute(count_stmt)
        total = result.scalar() or 0

        state.total_labeled_outcomes = total

        if total >= ACTIVATION_THRESHOLD:
            state.activation_status = "ACTIVE"
            state.last_activated_at = datetime.now(timezone.utc)
            await session.flush()
            logger.info("Meta-memory activated for tenant=%s (%d outcomes)", tenant_id, total)
            return True

        await session.flush()
        return False

    async def record_outcome(
        self,
        session: AsyncSession,
        tenant_id: str,
        dimension: str,
        area_key: str,
        is_true_positive: bool,
    ) -> None:
        """Record an outcome for an area's productivity tracking."""
        area = await self._get_or_create_area(session, tenant_id, dimension, area_key)
        prod = await self._get_or_create_productivity(session, area.id)

        prod.n_total += 1
        if is_true_positive:
            prod.n_tp += 1
        else:
            prod.n_fp += 1

        # Update raw productivity
        if prod.n_total > 0:
            prod.raw_productivity = prod.n_tp / prod.n_total

        # EMA smoothing
        prod.smoothed_productivity = (
            SMOOTHING_ALPHA * prod.raw_productivity
            + (1 - SMOOTHING_ALPHA) * prod.smoothed_productivity
        )
        prod.last_outcome_at = datetime.now(timezone.utc)

        await session.flush()

    async def compute_bias(
        self,
        session: AsyncSession,
        tenant_id: str,
    ) -> dict:
        """Compute exploration bias allocation across areas (Loop B output)."""
        if not await self.check_activation(session, tenant_id):
            return {}

        job = MetaMemoryJobRunORM(
            id=uuid4(),
            tenant_id=tenant_id,
            started_at=datetime.now(timezone.utc),
        )
        session.add(job)

        # Get all areas with productivity
        area_stmt = (
            select(MetaMemoryAreaORM)
            .where(MetaMemoryAreaORM.tenant_id == tenant_id)
        )
        area_result = await session.execute(area_stmt)
        areas = list(area_result.scalars().all())

        if not areas:
            job.completed_at = datetime.now(timezone.utc)
            job.areas_evaluated = 0
            await session.flush()
            return {}

        # Get productivity for each area
        productivities = {}
        for area in areas:
            prod_stmt = select(MetaMemoryProductivityORM).where(
                MetaMemoryProductivityORM.area_id == area.id
            )
            prod_result = await session.execute(prod_stmt)
            prod = prod_result.scalar_one_or_none()
            if prod:
                productivities[area.id] = prod.smoothed_productivity

        if not productivities:
            job.completed_at = datetime.now(timezone.utc)
            job.areas_evaluated = 0
            await session.flush()
            return {}

        # Inverse productivity allocation:
        # Low-productivity areas get MORE exploration bias
        inverse_prods = {
            aid: 1.0 / (prod + PRODUCTIVITY_EPSILON)
            for aid, prod in productivities.items()
        }
        total_inverse = sum(inverse_prods.values())

        bias_allocation = {}
        bias_changed = False
        for area in areas:
            if area.id in inverse_prods:
                allocation = inverse_prods[area.id] / max(total_inverse, 1e-10)
                bias_allocation[f"{area.dimension}:{area.area_key}"] = round(allocation, 4)

                bias_entry = MetaMemoryBiasORM(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    area_id=area.id,
                    bias_allocation=round(allocation, 4),
                )
                session.add(bias_entry)
                bias_changed = True

        job.completed_at = datetime.now(timezone.utc)
        job.areas_evaluated = len(areas)
        job.bias_changed = bias_changed

        await session.flush()
        logger.info(
            "Meta-memory bias computed: tenant=%s areas=%d",
            tenant_id, len(areas),
        )
        return bias_allocation

    async def _get_or_create_state(
        self, session: AsyncSession, tenant_id: str,
    ) -> MetaMemoryTenantStateORM:
        stmt = select(MetaMemoryTenantStateORM).where(
            MetaMemoryTenantStateORM.tenant_id == tenant_id
        )
        result = await session.execute(stmt)
        state = result.scalar_one_or_none()
        if state is None:
            state = MetaMemoryTenantStateORM(
                tenant_id=tenant_id,
                activation_status="INACTIVE",
            )
            session.add(state)
            await session.flush()
        return state

    async def _get_or_create_area(
        self, session: AsyncSession, tenant_id: str, dimension: str, area_key: str,
    ) -> MetaMemoryAreaORM:
        stmt = select(MetaMemoryAreaORM).where(
            MetaMemoryAreaORM.tenant_id == tenant_id,
            MetaMemoryAreaORM.dimension == dimension,
            MetaMemoryAreaORM.area_key == area_key,
        )
        result = await session.execute(stmt)
        area = result.scalar_one_or_none()
        if area is None:
            area = MetaMemoryAreaORM(
                id=uuid4(),
                tenant_id=tenant_id,
                dimension=dimension,
                area_key=area_key,
            )
            session.add(area)
            await session.flush()
        return area

    async def _get_or_create_productivity(
        self, session: AsyncSession, area_id: UUID,
    ) -> MetaMemoryProductivityORM:
        stmt = select(MetaMemoryProductivityORM).where(
            MetaMemoryProductivityORM.area_id == area_id
        )
        result = await session.execute(stmt)
        prod = result.scalar_one_or_none()
        if prod is None:
            prod = MetaMemoryProductivityORM(
                id=uuid4(),
                area_id=area_id,
            )
            session.add(prod)
            await session.flush()
        return prod
