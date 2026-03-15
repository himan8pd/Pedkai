"""
Structured event schema and provenance logging for Abeyance Memory.

Remediation targets:
- Audit §6.1: Snap events silently lost on Redis failure
- Audit §7.1: Snap score not persisted
- Audit §7.2: No decay audit trail
- Audit §7.3: Cluster formation unobservable

Invariants enforced:
- INV-10: All provenance is append-only
- INV-12: PostgreSQL is source of truth; Redis is notification layer
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.abeyance_orm import (
    ClusterSnapshotORM,
    FragmentHistoryORM,
    SnapDecisionRecordORM,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Event Dataclasses (typed, serialisable)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FragmentStateChange:
    """Records a fragment lifecycle state transition."""
    fragment_id: UUID
    tenant_id: str
    event_type: str
    old_state: dict[str, Any] = field(default_factory=dict)
    new_state: dict[str, Any] = field(default_factory=dict)
    event_detail: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class SnapDecision:
    """Full scoring breakdown for a snap evaluation."""
    tenant_id: str
    new_fragment_id: UUID
    candidate_fragment_id: UUID
    failure_mode_profile: str
    component_scores: dict[str, float]
    weights_used: dict[str, float]
    raw_composite: float
    temporal_modifier: float
    final_score: float
    threshold_applied: float
    decision: str  # SNAP, NEAR_MISS, AFFINITY, NONE
    multiple_comparisons_k: int = 1
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class ClusterEvaluation:
    """Cluster membership and scoring at evaluation time."""
    tenant_id: str
    member_fragment_ids: list[UUID]
    edges: list[dict[str, Any]]
    cluster_score: float
    correlation_discount: float
    adjusted_score: float
    threshold: float
    decision: str  # SNAP, NO_SNAP
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Provenance Logger — write-ahead to PostgreSQL (INV-12)
# ---------------------------------------------------------------------------

class ProvenanceLogger:
    """Persists provenance events to PostgreSQL before any notification.

    All writes are append-only (INV-10).  The caller must provide a session
    that is committed after the provenance write and before any Redis
    notification, ensuring the write-ahead invariant (INV-12).
    """

    async def log_state_change(
        self, session: AsyncSession, event: FragmentStateChange
    ) -> UUID:
        """Persist a fragment state change to the history log."""
        record_id = uuid4()
        record = FragmentHistoryORM(
            id=record_id,
            fragment_id=event.fragment_id,
            tenant_id=event.tenant_id,
            event_type=event.event_type,
            event_timestamp=event.timestamp,
            old_state=event.old_state,
            new_state=event.new_state,
            event_detail=event.event_detail,
        )
        session.add(record)
        return record_id

    async def log_snap_decision(
        self, session: AsyncSession, decision: SnapDecision
    ) -> UUID:
        """Persist a snap evaluation record."""
        record_id = uuid4()
        record = SnapDecisionRecordORM(
            id=record_id,
            tenant_id=decision.tenant_id,
            new_fragment_id=decision.new_fragment_id,
            candidate_fragment_id=decision.candidate_fragment_id,
            evaluated_at=decision.timestamp,
            failure_mode_profile=decision.failure_mode_profile,
            component_scores=decision.component_scores,
            weights_used=decision.weights_used,
            raw_composite=decision.raw_composite,
            temporal_modifier=decision.temporal_modifier,
            final_score=decision.final_score,
            threshold_applied=decision.threshold_applied,
            decision=decision.decision,
            multiple_comparisons_k=decision.multiple_comparisons_k,
        )
        session.add(record)
        return record_id

    async def log_cluster_evaluation(
        self, session: AsyncSession, evaluation: ClusterEvaluation
    ) -> UUID:
        """Persist a cluster evaluation snapshot."""
        record_id = uuid4()
        record = ClusterSnapshotORM(
            id=record_id,
            tenant_id=evaluation.tenant_id,
            evaluated_at=evaluation.timestamp,
            member_fragment_ids=[str(fid) for fid in evaluation.member_fragment_ids],
            edges=evaluation.edges,
            cluster_score=evaluation.cluster_score,
            correlation_discount=evaluation.correlation_discount,
            adjusted_score=evaluation.adjusted_score,
            threshold=evaluation.threshold,
            decision=evaluation.decision,
        )
        session.add(record)
        return record_id

    async def get_fragment_history(
        self,
        session: AsyncSession,
        fragment_id: UUID,
        tenant_id: str,
        limit: int = 100,
    ) -> list[FragmentHistoryORM]:
        """Query fragment history for operator forensics."""
        stmt = (
            select(FragmentHistoryORM)
            .where(
                FragmentHistoryORM.fragment_id == fragment_id,
                FragmentHistoryORM.tenant_id == tenant_id,
            )
            .order_by(FragmentHistoryORM.event_timestamp.asc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_snap_decisions_for_fragment(
        self,
        session: AsyncSession,
        fragment_id: UUID,
        tenant_id: str,
        limit: int = 50,
    ) -> list[SnapDecisionRecordORM]:
        """Query snap decisions involving a specific fragment."""
        stmt = (
            select(SnapDecisionRecordORM)
            .where(
                SnapDecisionRecordORM.tenant_id == tenant_id,
                (
                    (SnapDecisionRecordORM.new_fragment_id == fragment_id)
                    | (SnapDecisionRecordORM.candidate_fragment_id == fragment_id)
                ),
            )
            .order_by(SnapDecisionRecordORM.evaluated_at.desc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Redis Notifier — best-effort notification after PostgreSQL commit
# ---------------------------------------------------------------------------

class RedisNotifier:
    """Best-effort Redis notification layer.

    Redis is NOT source of truth (INV-12).  Events are persisted to
    PostgreSQL first.  Redis notification failure is logged but does
    not cause data loss — consumers can recover by querying PostgreSQL
    for events newer than their last-processed timestamp.
    """

    def __init__(self, redis_client: Optional[Any] = None):
        self._redis = redis_client

    async def notify_snap(
        self, tenant_id: str, fragment_id: UUID, hypothesis_id: UUID,
        score: float, failure_mode: str
    ) -> bool:
        """Notify downstream consumers of a snap event.

        Returns True if notification succeeded, False otherwise.
        Failure is non-fatal — state is already in PostgreSQL.
        """
        if self._redis is None:
            logger.warning("Redis unavailable — snap notification skipped "
                           "(state persisted in PostgreSQL)")
            return False

        try:
            stream_key = f"events:{tenant_id}:abeyance.snap_occurred"
            await self._redis.xadd(
                stream_key,
                {
                    "fragment_id": str(fragment_id),
                    "hypothesis_id": str(hypothesis_id),
                    "score": str(score),
                    "failure_mode": failure_mode,
                },
                maxlen=10000,  # Bounded stream (Phase 5)
            )
            return True
        except Exception:
            logger.warning(
                "Redis notification failed for snap event "
                f"(fragment={fragment_id}, tenant={tenant_id}). "
                "State is safe in PostgreSQL.",
                exc_info=True,
            )
            return False

    async def notify_cluster_snap(
        self, tenant_id: str, cluster_snapshot_id: UUID,
        member_count: int, score: float
    ) -> bool:
        """Notify downstream of a cluster snap."""
        if self._redis is None:
            return False

        try:
            stream_key = f"events:{tenant_id}:abeyance.cluster_snap"
            await self._redis.xadd(
                stream_key,
                {
                    "cluster_snapshot_id": str(cluster_snapshot_id),
                    "member_count": str(member_count),
                    "score": str(score),
                },
                maxlen=10000,
            )
            return True
        except Exception:
            logger.warning(
                "Redis notification failed for cluster snap "
                f"(tenant={tenant_id}). State safe in PostgreSQL.",
                exc_info=True,
            )
            return False

    async def notify_decay_batch(
        self, tenant_id: str, fragments_updated: int, fragments_expired: int
    ) -> bool:
        """Notify of decay batch completion."""
        if self._redis is None:
            return False

        try:
            stream_key = f"events:{tenant_id}:abeyance.decay_batch"
            await self._redis.xadd(
                stream_key,
                {
                    "fragments_updated": str(fragments_updated),
                    "fragments_expired": str(fragments_expired),
                },
                maxlen=10000,
            )
            return True
        except Exception:
            logger.warning("Redis notification failed for decay batch", exc_info=True)
            return False
