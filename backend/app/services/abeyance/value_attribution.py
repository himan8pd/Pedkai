"""
Value Attribution Service — measures operational value of discoveries.

Implements ABEYANCE_MEMORY_LLD.md §13 (Value Attribution Methodology).

Tracks the ongoing business impact of every Abeyance Memory discovery
through a permanent Discovery Ledger and Value Events, enabling
counterfactual value reporting (MTTR savings, licence reclamation,
illumination ratio, Dark Graph Reduction Index).
"""

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.core.logging import get_logger
from backend.app.models.abeyance_orm import (
    DiscoveryLedgerORM,
    ValueEventORM,
)
from backend.app.schemas.abeyance import (
    DarkGraphIndexResponse,
    DiscoveryLedgerResponse,
    IlluminationRatioResponse,
    ValueEventResponse,
    ValueReportResponse,
)

logger = get_logger(__name__)


class ValueAttributionService:
    """Tracks ongoing business impact of PedkAI discoveries (LLD §13).

    Every validated snap creates a permanent Discovery Ledger entry.
    Subsequent incidents involving PedkAI-discovered entities generate
    Value Events with MTTR attribution and counterfactual analysis.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self.session_factory = session_factory

    async def record_discovery(
        self,
        tenant_id: str,
        hypothesis_id: UUID,
        discovery_type: str,
        entity_ids: list[str],
        relationships: Optional[list[str]] = None,
        confidence: float = 0.0,
        session: Optional[AsyncSession] = None,
    ) -> DiscoveryLedgerORM:
        """Create permanent ledger entry for a validated discovery (LLD §13 Rule 1).

        Generates a CMDB reference tag linking the discovery to PedkAI's
        internal ledger for future value attribution.
        """
        ref_tag = f"PEDKAI-{str(tenant_id)[:8]}-{str(hypothesis_id)[:8]}"

        async with self._get_session(session) as s:
            entry = DiscoveryLedgerORM(
                id=uuid4(),
                tenant_id=tenant_id,
                hypothesis_id=hypothesis_id,
                discovery_type=discovery_type,
                discovered_entities=entity_ids,
                discovered_relationships=relationships or [],
                cmdb_reference_tag=ref_tag,
                discovery_confidence=confidence,
                status="ACTIVE",
            )
            s.add(entry)
            await s.flush()

            logger.info(
                f"Discovery recorded: type={discovery_type}, "
                f"entities={len(entity_ids)}, tag={ref_tag}"
            )
            return entry

    async def record_value_event(
        self,
        tenant_id: str,
        ledger_entry_id: UUID,
        event_type: str,
        attributed_hours: Optional[float] = None,
        attributed_currency: Optional[float] = None,
        rationale: str = "",
        event_detail: Optional[dict] = None,
        session: Optional[AsyncSession] = None,
    ) -> ValueEventORM:
        """Record a value realization event (LLD §13 Rules 2-5)."""
        async with self._get_session(session) as s:
            event = ValueEventORM(
                id=uuid4(),
                tenant_id=tenant_id,
                ledger_entry_id=ledger_entry_id,
                event_type=event_type,
                event_detail=event_detail or {},
                attributed_value_hours=attributed_hours,
                attributed_value_currency=attributed_currency,
                attribution_rationale=rationale,
            )
            s.add(event)
            await s.flush()
            return event

    async def correlate_incident(
        self,
        tenant_id: str,
        incident_id: str,
        resolved_entity_ids: list[str],
        actual_mttr_hours: Optional[float] = None,
        session: Optional[AsyncSession] = None,
    ) -> list[ValueEventORM]:
        """Check if a resolved incident touched PedkAI-discovered entities (LLD §13 Rule 2).

        Compares incident entities against the Discovery Ledger.
        Creates MTTR_REDUCTION value events for matches.
        """
        async with self._get_session(session) as s:
            # Find discoveries matching the resolved entities
            result = await s.execute(
                select(DiscoveryLedgerORM).where(
                    DiscoveryLedgerORM.tenant_id == tenant_id,
                    DiscoveryLedgerORM.status == "ACTIVE",
                )
            )
            discoveries = result.scalars().all()

            events = []
            resolved_set = set(resolved_entity_ids)

            for discovery in discoveries:
                discovered_entities = set(discovery.discovered_entities or [])
                if discovered_entities & resolved_set:
                    # Match found — create MTTR attribution event
                    overlap = discovered_entities & resolved_set
                    event = await self.record_value_event(
                        tenant_id=tenant_id,
                        ledger_entry_id=discovery.id,
                        event_type="MTTR_REDUCTION",
                        attributed_hours=actual_mttr_hours,
                        rationale=(
                            f"Incident {incident_id} resolved using "
                            f"PedkAI-discovered {discovery.discovery_type} "
                            f"(tag: {discovery.cmdb_reference_tag}). "
                            f"Overlapping entities: {', '.join(overlap)}"
                        ),
                        event_detail={
                            "incident_id": incident_id,
                            "overlapping_entities": list(overlap),
                        },
                        session=s,
                    )
                    events.append(event)

            if events:
                logger.info(
                    f"Incident correlation: incident={incident_id}, "
                    f"matched {len(events)} discoveries"
                )
            return events

    async def compute_illumination_ratio(
        self,
        tenant_id: str,
        session: Optional[AsyncSession] = None,
    ) -> IlluminationRatioResponse:
        """Compute the illumination ratio (LLD §13 Rule 5).

        Ratio of incidents touching PedkAI-discovered entities to total incidents.
        """
        async with self._get_session(session) as s:
            # Count value events of type MTTR_REDUCTION (each represents an illuminated incident)
            illuminated_result = await s.execute(
                select(func.count(func.distinct(
                    ValueEventORM.event_detail["incident_id"].as_string()
                ))).where(
                    ValueEventORM.tenant_id == tenant_id,
                    ValueEventORM.event_type == "MTTR_REDUCTION",
                )
            )
            illuminated_count = illuminated_result.scalar() or 0

            # Total incidents — estimate from incidents table
            try:
                from backend.app.models.incident_orm import IncidentORM
                total_result = await s.execute(
                    select(func.count(IncidentORM.id)).where(
                        IncidentORM.tenant_id == tenant_id,
                    )
                )
                total_count = total_result.scalar() or 0
            except Exception:
                total_count = max(illuminated_count, 1)

            ratio = illuminated_count / total_count if total_count > 0 else 0.0

            return IlluminationRatioResponse(
                tenant_id=tenant_id,
                ratio=ratio,
                incidents_with_pedkai_entities=illuminated_count,
                total_incidents=total_count,
            )

    async def compute_dark_graph_reduction_index(
        self,
        tenant_id: str,
        baseline_divergences: Optional[int] = None,
        session: Optional[AsyncSession] = None,
    ) -> DarkGraphIndexResponse:
        """Compute the Dark Graph Reduction Index (LLD §13 Rule 6).

        dark_graph_reduction = 1 - (current_divergences / baseline_divergences)
        """
        async with self._get_session(session) as s:
            # Count active discoveries (each represents a resolved divergence)
            result = await s.execute(
                select(func.count(DiscoveryLedgerORM.id)).where(
                    DiscoveryLedgerORM.tenant_id == tenant_id,
                    DiscoveryLedgerORM.status == "ACTIVE",
                )
            )
            resolved_count = result.scalar() or 0

            # Baseline: use provided value or estimate from initial deployment
            if baseline_divergences is None:
                # Estimate: resolved + remaining unresolved
                # For MVP, assume 2× resolved as baseline estimate
                baseline_divergences = max(resolved_count * 2, 1)

            current_divergences = max(baseline_divergences - resolved_count, 0)
            index = 1.0 - (current_divergences / baseline_divergences) if baseline_divergences > 0 else 0.0

            return DarkGraphIndexResponse(
                tenant_id=tenant_id,
                index=index,
                current_divergences=current_divergences,
                baseline_divergences=baseline_divergences,
            )

    async def get_ledger(
        self,
        tenant_id: str,
        limit: int = 50,
        offset: int = 0,
        session: Optional[AsyncSession] = None,
    ) -> list[DiscoveryLedgerResponse]:
        """Query discovery ledger entries."""
        async with self._get_session(session) as s:
            result = await s.execute(
                select(DiscoveryLedgerORM)
                .where(DiscoveryLedgerORM.tenant_id == tenant_id)
                .order_by(DiscoveryLedgerORM.discovered_at.desc())
                .offset(offset)
                .limit(limit)
            )
            return [
                DiscoveryLedgerResponse.model_validate(e)
                for e in result.scalars().all()
            ]

    async def get_value_events(
        self,
        tenant_id: str,
        limit: int = 50,
        offset: int = 0,
        session: Optional[AsyncSession] = None,
    ) -> list[ValueEventResponse]:
        """Query value attribution events."""
        async with self._get_session(session) as s:
            result = await s.execute(
                select(ValueEventORM)
                .where(ValueEventORM.tenant_id == tenant_id)
                .order_by(ValueEventORM.event_at.desc())
                .offset(offset)
                .limit(limit)
            )
            return [
                ValueEventResponse.model_validate(e)
                for e in result.scalars().all()
            ]

    async def generate_quarterly_report(
        self,
        tenant_id: str,
        period: str = "current",
        session: Optional[AsyncSession] = None,
    ) -> ValueReportResponse:
        """Generate quarterly value attribution report (LLD §13)."""
        async with self._get_session(session) as s:
            # Count discoveries
            disc_result = await s.execute(
                select(func.count(DiscoveryLedgerORM.id)).where(
                    DiscoveryLedgerORM.tenant_id == tenant_id,
                    DiscoveryLedgerORM.status == "ACTIVE",
                )
            )
            total_discoveries = disc_result.scalar() or 0

            # Discovery breakdown by type
            breakdown_result = await s.execute(
                select(
                    DiscoveryLedgerORM.discovery_type,
                    func.count(DiscoveryLedgerORM.id),
                ).where(
                    DiscoveryLedgerORM.tenant_id == tenant_id,
                    DiscoveryLedgerORM.status == "ACTIVE",
                ).group_by(DiscoveryLedgerORM.discovery_type)
            )
            breakdown = {row[0]: row[1] for row in breakdown_result.fetchall()}

            # Aggregate value events
            value_result = await s.execute(
                select(
                    func.coalesce(func.sum(ValueEventORM.attributed_value_hours), 0),
                    func.coalesce(func.sum(ValueEventORM.attributed_value_currency), 0),
                ).where(ValueEventORM.tenant_id == tenant_id)
            )
            value_row = value_result.fetchone()
            mttr_saved = float(value_row[0]) if value_row else 0.0
            licence_savings = float(value_row[1]) if value_row else 0.0

            # Get metrics
            illumination = await self.compute_illumination_ratio(tenant_id, s)
            dg_index = await self.compute_dark_graph_reduction_index(tenant_id, session=s)

            return ValueReportResponse(
                tenant_id=tenant_id,
                period=period,
                total_discoveries=total_discoveries,
                mttr_hours_saved=mttr_saved,
                licence_savings_currency=licence_savings,
                illumination_ratio=illumination.ratio,
                dark_graph_reduction_index=dg_index.index,
                discovery_breakdown=breakdown,
            )

    def _get_session(self, session: Optional[AsyncSession] = None):
        """Support both external session (reuse) and internal session creation."""
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _ctx():
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

        return _ctx()
