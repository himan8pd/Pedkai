"""
Ignorance Mapping — Layer 2, Mechanism #2 (LLD v3.0 §7.2).

Tracks extraction failure rates, mask distribution, silent decay patterns,
and generates exploration directives for under-observed domains.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
from uuid import uuid4

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.abeyance_orm import AbeyanceFragmentORM, SnapDecisionRecordORM
from backend.app.models.abeyance_v3_orm import (
    IgnoranceExtractionStatORM,
    IgnoranceMaskDistributionORM,
    IgnoranceSilentDecayRecordORM,
    IgnoranceSilentDecayStatORM,
    IgnoranceMapEntryORM,
    ExplorationDirectiveORM,
    IgnoranceJobRunORM,
)

logger = logging.getLogger(__name__)

SILENT_DECAY_MAX_SCORE = 0.30
IGNORANCE_SCAN_LOOKBACK_DAYS = 30
MAX_DIRECTIVES_PER_RUN = 10


class IgnoranceMapper:
    """Identifies systematic blind spots in the abeyance system."""

    async def run_scan(
        self,
        session: AsyncSession,
        tenant_id: str,
        now: Optional[datetime] = None,
    ) -> dict:
        """Execute a full ignorance mapping scan."""
        now = now or datetime.now(timezone.utc)
        lookback = now - timedelta(days=IGNORANCE_SCAN_LOOKBACK_DAYS)

        job = IgnoranceJobRunORM(
            id=uuid4(), tenant_id=tenant_id, started_at=now,
            outcome="RUNNING",
        )
        session.add(job)
        await session.flush()

        try:
            # 1. Scan for silent decays
            silent_count = await self._scan_silent_decays(session, tenant_id, lookback, now)

            # 2. Compute mask distribution
            await self._compute_mask_distribution(session, tenant_id, lookback, now)

            # 3. Compute ignorance map
            await self._compute_ignorance_map(session, tenant_id, lookback, now)

            # 4. Generate exploration directives
            directives = await self._generate_directives(session, tenant_id)

            job.completed_at = datetime.now(timezone.utc)
            job.fragments_scanned = silent_count
            job.silent_decays_found = silent_count
            job.directives_generated = len(directives)
            job.outcome = "COMPLETE"
            await session.flush()

            return {
                "silent_decays": silent_count,
                "directives_generated": len(directives),
                "job_id": str(job.id),
            }
        except Exception as e:
            job.completed_at = datetime.now(timezone.utc)
            job.outcome = "FAILED"
            await session.flush()
            raise

    async def _scan_silent_decays(
        self, session: AsyncSession, tenant_id: str,
        lookback: datetime, now: datetime,
    ) -> int:
        """Find fragments that expired without ever reaching NEAR_MISS."""
        stmt = (
            select(AbeyanceFragmentORM)
            .where(
                AbeyanceFragmentORM.tenant_id == tenant_id,
                AbeyanceFragmentORM.snap_status.in_(["EXPIRED", "STALE"]),
                AbeyanceFragmentORM.updated_at >= lookback,
                AbeyanceFragmentORM.near_miss_count == 0,
            )
            .limit(5000)
        )
        result = await session.execute(stmt)
        fragments = list(result.scalars().all())

        for frag in fragments:
            mask_pattern = self._mask_to_pattern(frag)
            record = IgnoranceSilentDecayRecordORM(
                id=uuid4(),
                tenant_id=tenant_id,
                fragment_id=frag.id,
                source_type=frag.source_type,
                entity_count=len(frag.extracted_entities or []),
                mask_pattern=mask_pattern,
            )
            session.add(record)

        await session.flush()
        return len(fragments)

    async def _compute_mask_distribution(
        self, session: AsyncSession, tenant_id: str,
        lookback: datetime, now: datetime,
    ) -> None:
        """Compute distribution of embedding mask patterns."""
        stmt = (
            select(AbeyanceFragmentORM)
            .where(
                AbeyanceFragmentORM.tenant_id == tenant_id,
                AbeyanceFragmentORM.created_at >= lookback,
            )
            .limit(10000)
        )
        result = await session.execute(stmt)
        fragments = list(result.scalars().all())

        if not fragments:
            return

        pattern_counts: dict[str, int] = {}
        for frag in fragments:
            pattern = self._mask_to_pattern(frag)
            pattern_counts[pattern] = pattern_counts.get(pattern, 0) + 1

        total = len(fragments)
        for profile in set(
            tag.get("divergence_type", "ALL")
            for frag in fragments
            for tag in (frag.failure_mode_tags or [])
            if isinstance(tag, dict)
        ) | {"ALL"}:
            for pattern, count in pattern_counts.items():
                entry = IgnoranceMaskDistributionORM(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    failure_mode_profile=profile,
                    mask_pattern=pattern,
                    fragment_count=count,
                    fraction=round(count / total, 4),
                    period_start=lookback,
                    period_end=now,
                )
                session.add(entry)

        await session.flush()

    async def _compute_ignorance_map(
        self, session: AsyncSession, tenant_id: str,
        lookback: datetime, now: datetime,
    ) -> None:
        """Compute ignorance scores per entity domain."""
        stmt = (
            select(AbeyanceFragmentORM)
            .where(
                AbeyanceFragmentORM.tenant_id == tenant_id,
                AbeyanceFragmentORM.created_at >= lookback,
            )
            .limit(10000)
        )
        result = await session.execute(stmt)
        fragments = list(result.scalars().all())

        domain_counts: dict[str, dict[str, int]] = {}
        for frag in fragments:
            for entity in (frag.extracted_entities or []):
                if isinstance(entity, dict):
                    domain = entity.get("domain", "UNKNOWN") or "UNKNOWN"
                    domain_counts.setdefault(domain, {"total": 0, "no_snap": 0})
                    domain_counts[domain]["total"] += 1
                    if frag.snap_status in ("EXPIRED", "STALE"):
                        domain_counts[domain]["no_snap"] += 1

        for domain, counts in domain_counts.items():
            ignorance = counts["no_snap"] / max(counts["total"], 1)
            entry = IgnoranceMapEntryORM(
                id=uuid4(),
                tenant_id=tenant_id,
                entity_domain=domain,
                metric_type="SILENT_DECAY_RATE",
                ignorance_score=round(ignorance, 4),
                detail=counts,
            )
            session.add(entry)

        await session.flush()

    async def _generate_directives(
        self, session: AsyncSession, tenant_id: str,
    ) -> list[ExplorationDirectiveORM]:
        """Generate exploration directives for high-ignorance domains."""
        stmt = (
            select(IgnoranceMapEntryORM)
            .where(
                IgnoranceMapEntryORM.tenant_id == tenant_id,
                IgnoranceMapEntryORM.ignorance_score >= 0.5,
            )
            .order_by(IgnoranceMapEntryORM.ignorance_score.desc())
            .limit(MAX_DIRECTIVES_PER_RUN)
        )
        result = await session.execute(stmt)
        entries = list(result.scalars().all())

        directives = []
        for entry in entries:
            directive = ExplorationDirectiveORM(
                id=uuid4(),
                tenant_id=tenant_id,
                entity_domain=entry.entity_domain,
                directive_type="INCREASE_EXTRACTION_COVERAGE",
                priority=entry.ignorance_score,
                rationale=f"Domain {entry.entity_domain} has {entry.ignorance_score:.0%} silent decay rate",
            )
            session.add(directive)
            directives.append(directive)

        await session.flush()
        return directives

    @staticmethod
    def _mask_to_pattern(frag: AbeyanceFragmentORM) -> str:
        """Convert per-dimension masks to a 3-char pattern like 'STO'."""
        parts = []
        if getattr(frag, "mask_semantic", False):
            parts.append("S")
        if getattr(frag, "mask_topological", False):
            parts.append("T")
        if getattr(frag, "mask_operational", False):
            parts.append("O")
        return "".join(parts) if parts else "NONE"
