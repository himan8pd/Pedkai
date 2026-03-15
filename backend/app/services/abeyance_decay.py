"""DEPRECATED — Old Abeyance Memory decay scoring service.

This module operated on DecisionTraceORM (split-brain architecture, Audit §3.1).
It is superseded by backend.app.services.abeyance.decay_engine.DecayEngine,
which operates on AbeyanceFragmentORM with:
- Source-type-dependent time constants (not a single global lambda)
- Bounded near-miss boost (capped at 1.5x, not unbounded 1.15^n)
- Monotonic decay enforcement (new_score <= old_score)
- Hard lifetime (730 days) and idle timeout (90 days)
- Full provenance via ProvenanceLogger (INV-10)

DO NOT USE THIS MODULE FOR NEW CODE.
Import from backend.app.services.abeyance.decay_engine instead.

Kept solely for backward compatibility with tests/test_abeyance_decay.py.
"""

import logging
import math
import warnings
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.models.decision_trace_orm import DecisionTraceORM

logger = logging.getLogger(__name__)
warnings.warn(
    "abeyance_decay.AbeyanceDecayService is deprecated. "
    "Use abeyance.decay_engine.DecayEngine instead.",
    DeprecationWarning,
    stacklevel=2,
)

settings = get_settings()

_BASE_RELEVANCE: float = 1.0
_CORROBORATION_WEIGHT: float = 0.3
_DEFAULT_STALE_THRESHOLD: float = 0.05


class AbeyanceDecayService:
    """DEPRECATED: Compute and persist relevance decay scores.

    Use backend.app.services.abeyance.decay_engine.DecayEngine instead.
    This class is retained only for backward compatibility with existing tests.
    """

    def __init__(self, decay_lambda: Optional[float] = None) -> None:
        self._lambda = (
            decay_lambda
            if decay_lambda is not None
            else settings.abeyance_decay_lambda
        )

    def compute_decay(
        self,
        days_since_created: float,
        corroboration_count: int = 0,
    ) -> float:
        """Return the decay score for a fragment of the given age."""
        if days_since_created < 0:
            days_since_created = 0.0

        corroboration_multiplier = 1.0 + (_CORROBORATION_WEIGHT * corroboration_count)
        raw = (
            _BASE_RELEVANCE
            * math.exp(-self._lambda * days_since_created)
            * corroboration_multiplier
        )
        return min(raw, 1.0)

    def _days_since(self, created_at: datetime) -> float:
        """Return fractional days between created_at and now (UTC)."""
        now = datetime.now(timezone.utc)
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        delta = now - created_at
        return max(delta.total_seconds() / 86400.0, 0.0)

    def run_decay_pass(self, tenant_id: str, session: Session) -> dict:
        """Recompute and persist decay_score for all ACTIVE fragments of a tenant."""
        stmt = select(DecisionTraceORM).where(
            DecisionTraceORM.tenant_id == tenant_id,
            DecisionTraceORM.abeyance_status == "ACTIVE",  # type: ignore[attr-defined]
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
        """Transition fragments with decay_score below threshold to status='STALE'."""
        stmt = (
            update(DecisionTraceORM)
            .where(
                DecisionTraceORM.tenant_id == tenant_id,
                DecisionTraceORM.abeyance_status == "ACTIVE",  # type: ignore[attr-defined]
                DecisionTraceORM.decay_score < threshold,  # type: ignore[attr-defined]
            )
            .values(abeyance_status="STALE")
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
