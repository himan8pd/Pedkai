"""
Value Attribution Service — tracks operational value of discoveries.

Implements LLD §13.  Audit-approved as structurally sound (Audit §10 #6).
Minor fix: baseline_divergences no longer fabricated (Audit §10 table).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.abeyance_orm import (
    DiscoveryLedgerORM,
    ValueEventORM,
)

logger = logging.getLogger(__name__)


class ValueAttributionService:
    """Tracks ongoing business impact of PedkAI discoveries."""

    async def record_discovery(
        self,
        session: AsyncSession,
        tenant_id: str,
        hypothesis_id: UUID,
        discovery_type: str,
        discovered_entities: list[str],
        discovered_relationships: list[str],
        confidence: float,
    ) -> UUID:
        """Create permanent ledger entry for a validated discovery."""
        ref_tag = f"PEDKAI-{str(tenant_id)[:8]}-{str(hypothesis_id)[:8]}"

        entry = DiscoveryLedgerORM(
            id=uuid4(),
            tenant_id=tenant_id,
            hypothesis_id=hypothesis_id,
            discovery_type=discovery_type,
            discovered_entities=discovered_entities,
            discovered_relationships=discovered_relationships,
            cmdb_reference_tag=ref_tag,
            discovery_confidence=confidence,
            status="ACTIVE",
        )
        session.add(entry)
        await session.flush()
        return entry.id

    async def record_value_event(
        self,
        session: AsyncSession,
        tenant_id: str,
        ledger_entry_id: UUID,
        event_type: str,
        attributed_hours: Optional[float] = None,
        attributed_currency: Optional[float] = None,
        rationale: str = "",
        detail: Optional[dict] = None,
    ) -> UUID:
        """Record a value realization event."""
        event = ValueEventORM(
            id=uuid4(),
            tenant_id=tenant_id,
            ledger_entry_id=ledger_entry_id,
            event_type=event_type,
            attributed_value_hours=attributed_hours,
            attributed_value_currency=attributed_currency,
            attribution_rationale=rationale,
            event_detail=detail or {},
        )
        session.add(event)
        await session.flush()
        return event.id

    async def get_value_report(
        self,
        session: AsyncSession,
        tenant_id: str,
        period_start: Optional[datetime] = None,
        period_end: Optional[datetime] = None,
    ) -> dict:
        """Generate value attribution report for a period."""
        # Count discoveries
        disc_stmt = (
            select(func.count(), DiscoveryLedgerORM.discovery_type)
            .where(DiscoveryLedgerORM.tenant_id == tenant_id)
            .group_by(DiscoveryLedgerORM.discovery_type)
        )
        if period_start:
            disc_stmt = disc_stmt.where(DiscoveryLedgerORM.discovered_at >= period_start)
        if period_end:
            disc_stmt = disc_stmt.where(DiscoveryLedgerORM.discovered_at <= period_end)

        disc_result = await session.execute(disc_stmt)
        discovery_breakdown = {row[1]: row[0] for row in disc_result.fetchall()}

        # Sum value events
        val_stmt = select(
            func.sum(ValueEventORM.attributed_value_hours),
            func.sum(ValueEventORM.attributed_value_currency),
        ).where(ValueEventORM.tenant_id == tenant_id)

        if period_start:
            val_stmt = val_stmt.where(ValueEventORM.event_at >= period_start)
        if period_end:
            val_stmt = val_stmt.where(ValueEventORM.event_at <= period_end)

        val_result = await session.execute(val_stmt)
        val_row = val_result.fetchone()

        return {
            "tenant_id": tenant_id,
            "total_discoveries": sum(discovery_breakdown.values()),
            "discovery_breakdown": discovery_breakdown,
            "mttr_hours_saved": val_row[0] or 0.0 if val_row else 0.0,
            "currency_saved": val_row[1] or 0.0 if val_row else 0.0,
        }

    async def compute_illumination_ratio(
        self,
        session: AsyncSession,
        tenant_id: str,
        total_incidents: int,
    ) -> dict:
        """Compute the illumination ratio (LLD §13 Rule 5).

        illumination_ratio = incidents_involving_pedkai_entities / total_incidents
        """
        disc_stmt = (
            select(func.count())
            .select_from(DiscoveryLedgerORM)
            .where(
                DiscoveryLedgerORM.tenant_id == tenant_id,
                DiscoveryLedgerORM.status == "ACTIVE",
            )
        )
        result = await session.execute(disc_stmt)
        active_discoveries = result.scalar() or 0

        # Events that reference discoveries (proxy for incidents touching PedkAI entities)
        event_stmt = (
            select(func.count())
            .select_from(ValueEventORM)
            .where(
                ValueEventORM.tenant_id == tenant_id,
                ValueEventORM.event_type == "INCIDENT_RESOLUTION",
            )
        )
        event_result = await session.execute(event_stmt)
        pedkai_incidents = event_result.scalar() or 0

        ratio = pedkai_incidents / total_incidents if total_incidents > 0 else 0.0

        return {
            "tenant_id": tenant_id,
            "ratio": round(ratio, 4),
            "incidents_with_pedkai_entities": pedkai_incidents,
            "total_incidents": total_incidents,
            "active_discoveries": active_discoveries,
        }

    async def compute_dark_graph_index(
        self,
        session: AsyncSession,
        tenant_id: str,
        baseline_divergences: Optional[int] = None,
    ) -> dict:
        """Dark Graph Reduction Index (LLD §13 Rule 6).

        dark_graph_reduction = 1 - (current_divergences / baseline_divergences)

        Baseline must come from initial deployment measurement — NOT fabricated
        (Audit §10 fix: removed 'resolved_count * 2' baseline).
        """
        disc_stmt = (
            select(func.count())
            .select_from(DiscoveryLedgerORM)
            .where(
                DiscoveryLedgerORM.tenant_id == tenant_id,
                DiscoveryLedgerORM.status == "ACTIVE",
            )
        )
        result = await session.execute(disc_stmt)
        resolved_count = result.scalar() or 0

        if baseline_divergences is None or baseline_divergences <= 0:
            return {
                "tenant_id": tenant_id,
                "index": 0.0,
                "current_divergences": 0,
                "baseline_divergences": 0,
                "status": "INSUFFICIENT_BASELINE",
                "message": "Baseline divergence count not available. "
                           "Requires initial Divergence Report at deployment.",
            }

        current_divergences = max(0, baseline_divergences - resolved_count)
        index = 1.0 - (current_divergences / baseline_divergences)

        return {
            "tenant_id": tenant_id,
            "index": round(max(0.0, min(1.0, index)), 4),
            "current_divergences": current_divergences,
            "baseline_divergences": baseline_divergences,
            "resolved_by_pedkai": resolved_count,
        }
