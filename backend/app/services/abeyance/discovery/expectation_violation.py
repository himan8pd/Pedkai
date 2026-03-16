"""
Expectation Violation Detection — Layer 3, Mechanism #9 (LLD v3.0 §9.2).

Uses transition matrix to detect anomalous state transitions.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.abeyance_v3_orm import ExpectationViolationORM
from backend.app.services.abeyance.discovery.temporal_sequence import TemporalSequenceModeller

logger = logging.getLogger(__name__)

VIOLATION_THRESHOLD = 0.05


class ExpectationViolationDetector:
    """Detects entity state transitions that violate learned patterns."""

    def __init__(self, temporal_modeller: TemporalSequenceModeller):
        self._modeller = temporal_modeller

    async def check_transition(
        self,
        session: AsyncSession,
        tenant_id: str,
        entity_id: UUID,
        entity_domain: Optional[str],
        from_state: str,
        to_state: str,
        fragment_id: UUID,
        surprise_event_id: Optional[UUID] = None,
    ) -> Optional[ExpectationViolationORM]:
        """Check if a transition violates the learned distribution."""
        if not entity_domain:
            return None

        prob = await self._modeller.get_transition_probability(
            session, tenant_id, entity_domain, from_state, to_state,
        )

        if prob >= VIOLATION_THRESHOLD:
            return None

        severity = -math.log(max(prob, 1e-10))
        violation_class = "NOVEL" if prob == 0.0 else "RARE"

        violation = ExpectationViolationORM(
            id=uuid4(),
            tenant_id=tenant_id,
            entity_id=entity_id,
            entity_domain=entity_domain,
            from_state=from_state,
            to_state=to_state,
            violation_severity=round(severity, 4),
            threshold_applied=VIOLATION_THRESHOLD,
            violation_class=violation_class,
            correlated_surprise_event_id=surprise_event_id,
            fragment_id=fragment_id,
        )
        session.add(violation)
        await session.flush()

        logger.info(
            "Expectation violation: tenant=%s entity=%s %s->%s prob=%.6f severity=%.4f",
            tenant_id, entity_id, from_state, to_state, prob, severity,
        )
        return violation
