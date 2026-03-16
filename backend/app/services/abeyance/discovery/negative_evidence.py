"""
Negative Evidence — Layer 2, Mechanism #3 (LLD v3.0 §7.3).

Operator-initiated disconfirmation: accelerated decay on false-positive clusters,
centroid computation for suppression of similar future fragments.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
from uuid import UUID, uuid4

import numpy as np
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.abeyance_orm import AbeyanceFragmentORM
from backend.app.models.abeyance_v3_orm import (
    DisconfirmationEventORM,
    DisconfirmationFragmentORM,
    DisconfirmationPatternORM,
)
from backend.app.services.abeyance.events import (
    FragmentStateChange,
    ProvenanceLogger,
)

logger = logging.getLogger(__name__)

DISCONFIRMATION_ACCELERATION_FACTOR = 5.0
DISCONFIRMATION_PATTERN_TTL_DAYS = 90
PENALTY_THRESHOLD = 0.80


class NegativeEvidenceService:
    """Handles operator disconfirmation of false-positive hypotheses."""

    def __init__(self, provenance: ProvenanceLogger):
        self._provenance = provenance

    async def disconfirm(
        self,
        session: AsyncSession,
        tenant_id: str,
        fragment_ids: list[UUID],
        initiated_by: str,
        reason: Optional[str] = None,
        pathway: str = "OPERATOR",
    ) -> DisconfirmationEventORM:
        """Apply disconfirmation to a set of fragments."""
        event = DisconfirmationEventORM(
            id=uuid4(),
            tenant_id=tenant_id,
            initiated_by=initiated_by,
            reason=reason,
            pathway=pathway,
            acceleration_factor=DISCONFIRMATION_ACCELERATION_FACTOR,
            fragment_count=len(fragment_ids),
        )
        session.add(event)

        # Fetch fragments
        stmt = (
            select(AbeyanceFragmentORM)
            .where(
                AbeyanceFragmentORM.tenant_id == tenant_id,
                AbeyanceFragmentORM.id.in_(fragment_ids),
            )
        )
        result = await session.execute(stmt)
        fragments = list(result.scalars().all())

        # Accelerate decay
        for frag in fragments:
            pre_score = frag.current_decay_score
            post_score = max(0.0, pre_score / DISCONFIRMATION_ACCELERATION_FACTOR)
            frag.current_decay_score = post_score
            frag.updated_at = datetime.now(timezone.utc)

            df = DisconfirmationFragmentORM(
                id=uuid4(),
                disconfirmation_event_id=event.id,
                fragment_id=frag.id,
                pre_decay_score=pre_score,
                post_decay_score=post_score,
            )
            session.add(df)

            await self._provenance.log_state_change(
                session,
                FragmentStateChange(
                    fragment_id=frag.id,
                    tenant_id=tenant_id,
                    event_type="DISCONFIRMED",
                    old_state={"decay_score": pre_score},
                    new_state={"decay_score": post_score},
                    event_detail={
                        "disconfirmation_event_id": str(event.id),
                        "initiated_by": initiated_by,
                        "acceleration_factor": DISCONFIRMATION_ACCELERATION_FACTOR,
                    },
                ),
            )

        # Compute and store centroid for future suppression
        await self._compute_centroid(session, tenant_id, event, fragments)

        await session.flush()
        logger.info(
            "Disconfirmed %d fragments for tenant=%s by=%s",
            len(fragments), tenant_id, initiated_by,
        )
        return event

    async def check_suppression(
        self,
        session: AsyncSession,
        tenant_id: str,
        fragment: AbeyanceFragmentORM,
    ) -> float:
        """Return penalty factor [0.0, 1.0] based on proximity to disconfirmed centroids.

        1.0 = no penalty, 0.0 = fully suppressed.
        """
        now = datetime.now(timezone.utc)
        stmt = (
            select(DisconfirmationPatternORM)
            .where(
                DisconfirmationPatternORM.tenant_id == tenant_id,
                DisconfirmationPatternORM.expires_at > now,
            )
        )
        result = await session.execute(stmt)
        patterns = list(result.scalars().all())

        if not patterns:
            return 1.0

        min_penalty = 1.0
        for pattern in patterns:
            if fragment.emb_semantic is not None and pattern.centroid_embedding_semantic is not None:
                sim = self._cosine_sim(fragment.emb_semantic, pattern.centroid_embedding_semantic)
                if sim >= PENALTY_THRESHOLD:
                    penalty = max(0.0, 1.0 - (sim - PENALTY_THRESHOLD) / (1.0 - PENALTY_THRESHOLD))
                    min_penalty = min(min_penalty, penalty * pattern.pattern_weight)

        return max(0.0, min_penalty)

    async def _compute_centroid(
        self,
        session: AsyncSession,
        tenant_id: str,
        event: DisconfirmationEventORM,
        fragments: list[AbeyanceFragmentORM],
    ) -> None:
        """Compute centroid embedding from disconfirmed fragments."""
        semantic_vecs = [
            np.asarray(f.emb_semantic, dtype=np.float64)
            for f in fragments
            if f.emb_semantic is not None and f.mask_semantic
        ]

        centroid_semantic = None
        if semantic_vecs:
            centroid = np.mean(semantic_vecs, axis=0)
            norm = np.linalg.norm(centroid)
            if norm > 1e-10:
                centroid = centroid / norm
            centroid_semantic = centroid.tolist()

        pattern = DisconfirmationPatternORM(
            id=uuid4(),
            tenant_id=tenant_id,
            disconfirmation_event_id=event.id,
            centroid_embedding_semantic=centroid_semantic,
            pattern_weight=1.0,
            fragments_in_centroid=len(semantic_vecs),
            expires_at=datetime.now(timezone.utc) + timedelta(days=DISCONFIRMATION_PATTERN_TTL_DAYS),
        )
        session.add(pattern)

    @staticmethod
    def _cosine_sim(a, b) -> float:
        a_arr = np.asarray(a, dtype=np.float64)
        b_arr = np.asarray(b, dtype=np.float64)
        na, nb = np.linalg.norm(a_arr), np.linalg.norm(b_arr)
        if na < 1e-10 or nb < 1e-10:
            return 0.0
        return float(np.dot(a_arr, b_arr) / (na * nb))
