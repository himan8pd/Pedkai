"""Abeyance Memory decay scoring service.

Implements exponential relevance decay for decision_traces fragments that
serve as Abeyance Memory entries.  The formula is:

    decay_score(t) = base_relevance
                     × exp(-λ × days_since_created)
                     × corroboration_multiplier

where:
    λ                       = ABEYANCE_DECAY_LAMBDA (default 0.05)
    corroboration_multiplier = 1 + (0.3 × corroboration_count)
    base_relevance           = 1.0 (fixed — the initial score when created)

A fragment whose decay_score falls below the configured threshold is
promoted to status='STALE'.  STALE fragments are still retained in the
database; archival/deletion is handled separately by data_retention.py.
"""

import logging
import math
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.models.decision_trace_orm import DecisionTraceORM

logger = logging.getLogger(__name__)

settings = get_settings()

_BASE_RELEVANCE: float = 1.0
_CORROBORATION_WEIGHT: float = 0.3
_DEFAULT_STALE_THRESHOLD: float = 0.05


class AbeyanceDecayService:
    """Compute and persist relevance decay scores for Abeyance Memory fragments.

    All public methods accept a synchronous SQLAlchemy Session so they can be
    called from both synchronous test code and from async contexts (wrap in
    run_in_executor if needed for async callers).
    """

    def __init__(self, decay_lambda: Optional[float] = None) -> None:
        self._lambda = (
            decay_lambda
            if decay_lambda is not None
            else settings.abeyance_decay_lambda
        )

    # ------------------------------------------------------------------
    # Core formula
    # ------------------------------------------------------------------

    def compute_decay(
        self,
        days_since_created: float,
        corroboration_count: int = 0,
    ) -> float:
        """Return the decay score for a fragment of the given age.

        Parameters
        ----------
        days_since_created:
            Elapsed time since the fragment was created, in fractional days.
        corroboration_count:
            Number of times this fragment has been reinforced by corroborating
            evidence (each corroboration slows future decay).

        Returns
        -------
        float
            A value in (0, ∞) — in practice in (0, 1] for newly-created
            fragments with reasonable corroboration counts.  Callers should
            clamp to [0.0, 1.0] if they need a bounded score.
        """
        if days_since_created < 0:
            days_since_created = 0.0

        corroboration_multiplier = 1.0 + (_CORROBORATION_WEIGHT * corroboration_count)
        raw = (
            _BASE_RELEVANCE
            * math.exp(-self._lambda * days_since_created)
            * corroboration_multiplier
        )
        # Clamp to [0.0, 1.0] — corroboration can push above 1 for very fresh
        # entries but we cap at 1 to keep the score interpretable.
        return min(raw, 1.0)

    def _days_since(self, created_at: datetime) -> float:
        """Return fractional days between created_at and now (UTC)."""
        now = datetime.now(timezone.utc)
        # Ensure created_at is timezone-aware
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        delta = now - created_at
        return max(delta.total_seconds() / 86400.0, 0.0)

    # ------------------------------------------------------------------
    # Batch operations (require a DB session)
    # ------------------------------------------------------------------

    def run_decay_pass(self, tenant_id: str, session: Session) -> dict:
        """Recompute and persist decay_score for all ACTIVE fragments of a tenant.

        Parameters
        ----------
        tenant_id:
            The tenant whose fragments should be updated.
        session:
            An open synchronous SQLAlchemy session.

        Returns
        -------
        dict
            ``{"updated": int}`` — number of rows whose decay_score was written.
        """
        stmt = select(DecisionTraceORM).where(
            DecisionTraceORM.tenant_id == tenant_id,
            DecisionTraceORM.status == "ACTIVE",  # type: ignore[attr-defined]
        )
        rows = session.execute(stmt).scalars().all()

        updated = 0
        for fragment in rows:
            days = self._days_since(fragment.created_at)
            new_score = self.compute_decay(
                days_since_created=days,
                corroboration_count=fragment.corroboration_count,  # type: ignore[attr-defined]
            )
            fragment.decay_score = new_score  # type: ignore[attr-defined]
            updated += 1

        if updated:
            session.flush()

        logger.info(
            "Abeyance decay pass complete",
            extra={"tenant_id": tenant_id, "updated": updated},
        )
        return {"updated": updated}

    def mark_stale_fragments(
        self,
        tenant_id: str,
        session: Session,
        threshold: float = _DEFAULT_STALE_THRESHOLD,
    ) -> int:
        """Transition fragments with decay_score below threshold to status='STALE'.

        Parameters
        ----------
        tenant_id:
            The tenant whose fragments should be evaluated.
        session:
            An open synchronous SQLAlchemy session.
        threshold:
            Fragments with decay_score strictly below this value are marked STALE.
            Default is 0.05 (5 % of original relevance).

        Returns
        -------
        int
            Number of fragments transitioned to STALE.
        """
        stmt = (
            update(DecisionTraceORM)
            .where(
                DecisionTraceORM.tenant_id == tenant_id,
                DecisionTraceORM.status == "ACTIVE",  # type: ignore[attr-defined]
                DecisionTraceORM.decay_score < threshold,  # type: ignore[attr-defined]
            )
            .values(status="STALE")
            .execution_options(synchronize_session="fetch")
        )
        result = session.execute(stmt)
        count: int = result.rowcount
        if count:
            session.flush()

        logger.info(
            "Marked stale fragments",
            extra={"tenant_id": tenant_id, "stale_count": count, "threshold": threshold},
        )
        return count
