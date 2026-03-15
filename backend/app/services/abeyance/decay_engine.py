"""
Decay Engine — bounded, auditable exponential decay.

Remediation targets:
- Audit §2.2: Unbounded relevance boosting → capped at 1.5 total
- Audit §7.2: No decay audit trail → append-only fragment_history

Invariants enforced:
- INV-2: Decay is strictly monotonic decreasing under constant conditions
- INV-3: All scoring in bounded domains
- INV-6: Hard lifetime and idle duration bounds
- INV-8: No output outside [0.0, 1.0]
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone, timedelta
from typing import Optional
from uuid import UUID

from sqlalchemy import select, update, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.abeyance_orm import (
    AbeyanceFragmentORM,
    VALID_TRANSITIONS,
)
from backend.app.services.abeyance.events import (
    FragmentStateChange,
    ProvenanceLogger,
    RedisNotifier,
)

logger = logging.getLogger(__name__)


# Source-type decay time constants (LLD §5 table)
DECAY_TAU: dict[str, float] = {
    "TICKET_TEXT": 270.0,
    "ALARM": 90.0,
    "TELEMETRY_EVENT": 60.0,
    "CLI_OUTPUT": 180.0,
    "CHANGE_RECORD": 365.0,
    "CMDB_DELTA": 90.0,
}

# Near-miss boost parameters (remediated per Audit §2.2)
MAX_NEAR_MISS_BOOST_COUNT = 10  # Max near-misses that contribute to boost
BOOST_PER_NEAR_MISS = 0.05  # Additive per near-miss
MAX_BOOST_FACTOR = 1.5  # Hard cap: 1.0 + 10 * 0.05 = 1.5

# Lifecycle thresholds
STALE_THRESHOLD = 0.15
EXPIRATION_THRESHOLD = 0.10
MAX_IDLE_DAYS = 90  # INV-6: force expiration after 90 days idle


class DecayEngine:
    """Computes and applies exponential decay to abeyance fragments.

    Decay formula (remediated):
        decay_score = base_relevance * boost_factor * exp(-age_days / tau)

    Where boost_factor = 1.0 + min(near_miss_count, 10) * 0.05
    Guaranteed properties:
        - boost_factor in [1.0, 1.5] (INV-2, Audit §2.2)
        - exp(-age/tau) is strictly decreasing in age (INV-2)
        - decay_score in [0.0, base_relevance * 1.5] clamped to [0.0, 1.0] (INV-8)
    """

    def __init__(
        self,
        provenance: ProvenanceLogger,
        notifier: Optional[RedisNotifier] = None,
    ):
        self._provenance = provenance
        self._notifier = notifier or RedisNotifier()

    @staticmethod
    def compute_boost_factor(near_miss_count: int) -> float:
        """Compute bounded boost factor from near-miss count.

        Returns value in [1.0, MAX_BOOST_FACTOR].
        """
        effective_count = min(near_miss_count, MAX_NEAR_MISS_BOOST_COUNT)
        return 1.0 + effective_count * BOOST_PER_NEAR_MISS

    @staticmethod
    def compute_decay_score(
        base_relevance: float,
        near_miss_count: int,
        age_days: float,
        source_type: str,
    ) -> float:
        """Pure computation of decay score.

        Deterministic: same inputs always produce same output.
        Output clamped to [0.0, 1.0] (INV-8).
        """
        tau = DECAY_TAU.get(source_type, 90.0)
        boost = DecayEngine.compute_boost_factor(near_miss_count)
        raw_score = base_relevance * boost * math.exp(-age_days / tau)
        return max(0.0, min(1.0, raw_score))

    async def run_decay_pass(
        self,
        session: AsyncSession,
        tenant_id: str,
        now: Optional[datetime] = None,
        batch_size: int = 10000,
    ) -> tuple[int, int]:
        """Execute a bounded decay pass for a tenant.

        Returns (fragments_updated, fragments_expired).
        Processes at most batch_size fragments per invocation (Phase 5).
        """
        if now is None:
            now = datetime.now(timezone.utc)

        # Fetch active/near-miss fragments for this tenant
        stmt = (
            select(AbeyanceFragmentORM)
            .where(
                AbeyanceFragmentORM.tenant_id == tenant_id,
                AbeyanceFragmentORM.snap_status.in_(["ACTIVE", "NEAR_MISS"]),
            )
            .order_by(AbeyanceFragmentORM.current_decay_score.asc())
            .limit(batch_size)
        )
        result = await session.execute(stmt)
        fragments = list(result.scalars().all())

        updated = 0
        expired = 0

        for frag in fragments:
            event_time = frag.event_timestamp or frag.created_at
            age_days = max(0.0, (now - event_time).total_seconds() / 86400.0)

            old_score = frag.current_decay_score
            old_status = frag.snap_status

            new_score = self.compute_decay_score(
                base_relevance=frag.base_relevance,
                near_miss_count=frag.near_miss_count,
                age_days=age_days,
                source_type=frag.source_type or "ALARM",
            )

            # Enforce monotonicity (INV-2): new score cannot exceed old score
            # unless near_miss_count increased (which is a different event)
            new_score = min(new_score, old_score)

            # Check hard lifetime bound (INV-6)
            max_lifetime = frag.max_lifetime_days or 730
            if age_days > max_lifetime:
                new_score = 0.0

            # Check idle duration bound (INV-6)
            if frag.updated_at:
                idle_days = (now - frag.updated_at).total_seconds() / 86400.0
                if idle_days > MAX_IDLE_DAYS:
                    new_score = 0.0

            # Determine new status
            new_status = old_status
            if new_score < EXPIRATION_THRESHOLD:
                if "EXPIRED" in VALID_TRANSITIONS.get(old_status, set()):
                    new_status = "EXPIRED"
                    expired += 1
                elif "STALE" in VALID_TRANSITIONS.get(old_status, set()):
                    new_status = "STALE"
            elif new_score < STALE_THRESHOLD:
                if "STALE" in VALID_TRANSITIONS.get(old_status, set()):
                    new_status = "STALE"

            # Apply updates
            frag.current_decay_score = new_score
            frag.snap_status = new_status
            frag.updated_at = now

            # Log provenance (INV-10)
            if new_score != old_score or new_status != old_status:
                await self._provenance.log_state_change(
                    session,
                    FragmentStateChange(
                        fragment_id=frag.id,
                        tenant_id=tenant_id,
                        event_type="DECAY_UPDATE",
                        old_state={
                            "decay_score": old_score,
                            "status": old_status,
                        },
                        new_state={
                            "decay_score": new_score,
                            "status": new_status,
                        },
                        event_detail={
                            "age_days": round(age_days, 2),
                            "boost_factor": self.compute_boost_factor(frag.near_miss_count),
                            "tau": DECAY_TAU.get(frag.source_type or "ALARM", 90.0),
                        },
                    ),
                )
                updated += 1

        await session.flush()

        # Best-effort Redis notification (INV-12: after PostgreSQL persist)
        if updated > 0 or expired > 0:
            await self._notifier.notify_decay_batch(tenant_id, updated, expired)

        logger.info(
            "Decay pass complete: tenant=%s updated=%d expired=%d",
            tenant_id, updated, expired,
        )
        return updated, expired

    async def apply_near_miss_boost(
        self,
        session: AsyncSession,
        fragment_id: UUID,
        tenant_id: str,
    ) -> float:
        """Apply a near-miss boost to a fragment.

        Increments near_miss_count (capped at MAX_NEAR_MISS_BOOST_COUNT).
        Does NOT modify base_relevance (Audit §2.2 fix).
        Returns the new decay score.
        """
        stmt = (
            select(AbeyanceFragmentORM)
            .where(
                AbeyanceFragmentORM.id == fragment_id,
                AbeyanceFragmentORM.tenant_id == tenant_id,  # INV-7
            )
        )
        result = await session.execute(stmt)
        frag = result.scalar_one_or_none()

        if frag is None:
            logger.warning("Fragment %s not found for tenant %s", fragment_id, tenant_id)
            return 0.0

        old_count = frag.near_miss_count
        new_count = min(old_count + 1, MAX_NEAR_MISS_BOOST_COUNT)
        frag.near_miss_count = new_count

        # Update status if appropriate
        if frag.snap_status == "ACTIVE":
            frag.snap_status = "NEAR_MISS"

        # Recompute decay with new boost
        event_time = frag.event_timestamp or frag.created_at
        now = datetime.now(timezone.utc)
        age_days = max(0.0, (now - event_time).total_seconds() / 86400.0)
        new_score = self.compute_decay_score(
            base_relevance=frag.base_relevance,
            near_miss_count=new_count,
            age_days=age_days,
            source_type=frag.source_type or "ALARM",
        )
        frag.current_decay_score = new_score
        frag.updated_at = now

        # Log provenance
        await self._provenance.log_state_change(
            session,
            FragmentStateChange(
                fragment_id=fragment_id,
                tenant_id=tenant_id,
                event_type="NEAR_MISS",
                old_state={"near_miss_count": old_count, "status": "ACTIVE"},
                new_state={"near_miss_count": new_count, "status": frag.snap_status},
                event_detail={"new_decay_score": new_score},
            ),
        )

        await session.flush()
        return new_score
