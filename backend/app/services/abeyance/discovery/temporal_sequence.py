"""
Temporal Sequence Modelling — Layer 2, Mechanism #7 (LLD v3.0 §8.3).

Maintains entity state transition logs and transition matrices per domain.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.abeyance_v3_orm import (
    EntitySequenceLogORM,
    TransitionMatrixORM,
    TransitionMatrixVersionORM,
)

logger = logging.getLogger(__name__)

MAX_TRANSITIONS_PER_RECOMPUTE = 50000


class TemporalSequenceModeller:
    """Maintains entity state transition logs and matrices."""

    async def log_transition(
        self,
        session: AsyncSession,
        tenant_id: str,
        entity_id: UUID,
        entity_domain: Optional[str],
        from_state: Optional[str],
        to_state: str,
        fragment_id: UUID,
        event_timestamp: datetime,
    ) -> EntitySequenceLogORM:
        """Record an entity state transition."""
        entry = EntitySequenceLogORM(
            tenant_id=tenant_id,
            entity_id=entity_id,
            entity_domain=entity_domain,
            from_state=from_state,
            to_state=to_state,
            fragment_id=fragment_id,
            event_timestamp=event_timestamp,
        )
        session.add(entry)
        await session.flush()
        return entry

    async def recompute_matrix(
        self,
        session: AsyncSession,
        tenant_id: str,
        entity_domain: str,
    ) -> dict:
        """Recompute transition matrix for a domain from sequence logs."""
        version = TransitionMatrixVersionORM(
            id=uuid4(),
            tenant_id=tenant_id,
            entity_domain=entity_domain,
            recompute_started_at=datetime.now(timezone.utc),
        )
        session.add(version)

        stmt = (
            select(EntitySequenceLogORM)
            .where(
                EntitySequenceLogORM.tenant_id == tenant_id,
                EntitySequenceLogORM.entity_domain == entity_domain,
            )
            .order_by(EntitySequenceLogORM.event_timestamp.asc())
            .limit(MAX_TRANSITIONS_PER_RECOMPUTE)
        )
        result = await session.execute(stmt)
        entries = list(result.scalars().all())

        # Build transition counts from consecutive pairs
        transition_counts: dict[tuple[str, str], int] = {}
        states: set[str] = set()

        for entry in entries:
            if entry.from_state and entry.to_state:
                key = (entry.from_state, entry.to_state)
                transition_counts[key] = transition_counts.get(key, 0) + 1
                states.add(entry.from_state)
                states.add(entry.to_state)

        # Upsert transition matrix entries
        for (from_s, to_s), count in transition_counts.items():
            existing_stmt = select(TransitionMatrixORM).where(
                TransitionMatrixORM.tenant_id == tenant_id,
                TransitionMatrixORM.entity_domain == entity_domain,
                TransitionMatrixORM.from_state == from_s,
                TransitionMatrixORM.to_state == to_s,
            )
            existing_result = await session.execute(existing_stmt)
            existing = existing_result.scalar_one_or_none()

            if existing:
                existing.count = count
                existing.last_observed_at = datetime.now(timezone.utc)
            else:
                tm = TransitionMatrixORM(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    entity_domain=entity_domain,
                    from_state=from_s,
                    to_state=to_s,
                    count=count,
                )
                session.add(tm)

        version.recompute_completed_at = datetime.now(timezone.utc)
        version.total_transitions = sum(transition_counts.values())
        version.unique_states = len(states)

        await session.flush()
        logger.info(
            "Transition matrix recomputed: tenant=%s domain=%s transitions=%d states=%d",
            tenant_id, entity_domain, version.total_transitions, version.unique_states,
        )
        return {
            "total_transitions": version.total_transitions,
            "unique_states": version.unique_states,
        }

    async def get_transition_probability(
        self,
        session: AsyncSession,
        tenant_id: str,
        entity_domain: str,
        from_state: str,
        to_state: str,
    ) -> float:
        """Get P(to_state | from_state) for a domain."""
        # Get all transitions from from_state
        stmt = (
            select(TransitionMatrixORM)
            .where(
                TransitionMatrixORM.tenant_id == tenant_id,
                TransitionMatrixORM.entity_domain == entity_domain,
                TransitionMatrixORM.from_state == from_state,
            )
        )
        result = await session.execute(stmt)
        entries = list(result.scalars().all())

        if not entries:
            return 0.0

        total = sum(e.count for e in entries)
        for e in entries:
            if e.to_state == to_state:
                return e.count / max(total, 1)
        return 0.0
