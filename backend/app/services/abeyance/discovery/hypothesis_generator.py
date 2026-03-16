"""
Hypothesis Generation — Layer 3, Mechanism #8 (LLD v3.0 §9.1).

Consumes triggers from Surprise Engine, Bridge Detection, and Expectation
Violation to generate testable hypotheses.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.abeyance_v3_orm import (
    HypothesisORM,
    HypothesisEvidenceORM,
    HypothesisGenerationQueueORM,
)

logger = logging.getLogger(__name__)

HYPOTHESIS_TTL_DAYS = 30
MAX_ACTIVE_HYPOTHESES = 100
MAX_QUEUE_BATCH = 50


class HypothesisGenerator:
    """Generates and manages hypotheses from discovery triggers."""

    def __init__(self, tslam_service=None):
        self._tslam = tslam_service

    async def enqueue_trigger(
        self,
        session: AsyncSession,
        tenant_id: str,
        trigger_type: str,
        trigger_id: UUID,
        context: Optional[dict] = None,
    ) -> HypothesisGenerationQueueORM:
        """Enqueue a trigger for hypothesis generation."""
        item = HypothesisGenerationQueueORM(
            id=uuid4(),
            tenant_id=tenant_id,
            trigger_type=trigger_type,
            trigger_id=trigger_id,
            raw_context=context,
            status="PENDING",
        )
        session.add(item)
        await session.flush()
        return item

    async def process_queue(
        self,
        session: AsyncSession,
        tenant_id: str,
    ) -> list[HypothesisORM]:
        """Process pending triggers and generate hypotheses."""
        # Check active hypothesis count
        active_count_stmt = (
            select(HypothesisORM)
            .where(
                HypothesisORM.tenant_id == tenant_id,
                HypothesisORM.status == "PROPOSED",
            )
        )
        active_result = await session.execute(active_count_stmt)
        active_count = len(list(active_result.scalars().all()))

        if active_count >= MAX_ACTIVE_HYPOTHESES:
            logger.info("Max active hypotheses reached for tenant=%s", tenant_id)
            return []

        # Get pending triggers
        queue_stmt = (
            select(HypothesisGenerationQueueORM)
            .where(
                HypothesisGenerationQueueORM.tenant_id == tenant_id,
                HypothesisGenerationQueueORM.status == "PENDING",
            )
            .order_by(HypothesisGenerationQueueORM.created_at.asc())
            .limit(MAX_QUEUE_BATCH)
        )
        queue_result = await session.execute(queue_stmt)
        pending = list(queue_result.scalars().all())

        hypotheses = []
        remaining_slots = MAX_ACTIVE_HYPOTHESES - active_count

        for item in pending:
            if len(hypotheses) >= remaining_slots:
                break

            hypothesis = await self._generate_from_trigger(session, tenant_id, item)
            if hypothesis:
                hypotheses.append(hypothesis)

            item.status = "PROCESSED"
            item.attempt_count += 1

        await session.flush()
        return hypotheses

    async def _generate_from_trigger(
        self,
        session: AsyncSession,
        tenant_id: str,
        trigger: HypothesisGenerationQueueORM,
    ) -> Optional[HypothesisORM]:
        """Generate a hypothesis from a trigger."""
        now = datetime.now(timezone.utc)
        expires = now + timedelta(days=HYPOTHESIS_TTL_DAYS)

        statement = await self._formulate_statement(trigger)
        if not statement:
            return None

        hypothesis = HypothesisORM(
            id=uuid4(),
            tenant_id=tenant_id,
            statement=statement,
            status="PROPOSED",
            expires_at=expires,
        )
        session.add(hypothesis)

        # Link evidence
        evidence = HypothesisEvidenceORM(
            id=uuid4(),
            hypothesis_id=hypothesis.id,
            source_table=f"{trigger.trigger_type}_trigger",
            source_id=trigger.trigger_id,
            evidence_type="TRIGGER",
            contribution=1.0,
        )
        session.add(evidence)

        await session.flush()
        logger.info(
            "Hypothesis generated: tenant=%s id=%s trigger=%s",
            tenant_id, hypothesis.id, trigger.trigger_type,
        )
        return hypothesis

    async def _formulate_statement(
        self, trigger: HypothesisGenerationQueueORM,
    ) -> Optional[str]:
        """Formulate hypothesis statement from trigger context."""
        context = trigger.raw_context or {}

        # TSLAM-based formulation
        if self._tslam:
            prompt = (
                f"Based on this {trigger.trigger_type} event in a telecom network, "
                f"formulate a concise testable hypothesis about the underlying cause.\n"
                f"Context: {str(context)[:500]}\n"
                f"Hypothesis:"
            )
            try:
                result = await self._tslam.generate(prompt, max_tokens=200, temperature=0.3)
                if result:
                    return result.strip()[:500]
            except Exception:
                logger.debug("TSLAM hypothesis formulation failed, using template")

        # Template fallback
        templates = {
            "SURPRISE_EVENT": "Anomalous scoring pattern detected — may indicate novel failure mode or emerging topology change",
            "BRIDGE_DISCOVERY": "Cross-domain bridge fragment discovered — may indicate hidden dependency between domains",
            "EXPECTATION_VIOLATION": "State transition violated expected pattern — may indicate configuration drift or undocumented change",
            "CONFLICT": "Contradictory evidence detected — may indicate ambiguous or evolving failure scenario",
        }
        return templates.get(trigger.trigger_type, f"Discovery trigger: {trigger.trigger_type}")

    async def expire_hypotheses(
        self, session: AsyncSession, tenant_id: str,
    ) -> int:
        """Expire hypotheses past their TTL."""
        now = datetime.now(timezone.utc)
        stmt = (
            select(HypothesisORM)
            .where(
                HypothesisORM.tenant_id == tenant_id,
                HypothesisORM.status == "PROPOSED",
                HypothesisORM.expires_at <= now,
            )
        )
        result = await session.execute(stmt)
        expired = list(result.scalars().all())

        for h in expired:
            h.status = "EXPIRED"

        await session.flush()
        return len(expired)

    async def confirm_hypothesis(
        self,
        session: AsyncSession,
        tenant_id: str,
        hypothesis_id: UUID,
        confidence: float = 1.0,
    ) -> Optional[HypothesisORM]:
        """Mark a hypothesis as confirmed."""
        stmt = select(HypothesisORM).where(
            HypothesisORM.id == hypothesis_id,
            HypothesisORM.tenant_id == tenant_id,
        )
        result = await session.execute(stmt)
        hyp = result.scalar_one_or_none()
        if hyp and hyp.status == "PROPOSED":
            hyp.status = "CONFIRMED"
            hyp.confidence = confidence
            hyp.confirmed_at = datetime.now(timezone.utc)
            await session.flush()
        return hyp

    async def refute_hypothesis(
        self,
        session: AsyncSession,
        tenant_id: str,
        hypothesis_id: UUID,
    ) -> Optional[HypothesisORM]:
        """Mark a hypothesis as refuted."""
        stmt = select(HypothesisORM).where(
            HypothesisORM.id == hypothesis_id,
            HypothesisORM.tenant_id == tenant_id,
        )
        result = await session.execute(stmt)
        hyp = result.scalar_one_or_none()
        if hyp and hyp.status == "PROPOSED":
            hyp.status = "REFUTED"
            hyp.refuted_at = datetime.now(timezone.utc)
            await session.flush()
        return hyp
