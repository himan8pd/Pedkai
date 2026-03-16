"""
Pattern Compression — Layer 4, Mechanism #11 (LLD v3.0 §10.1).

Discovers compact rules that explain clusters of snap decisions,
measured by compression gain (description length reduction).
"""

from __future__ import annotations

import logging
import math
from collections import Counter
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.abeyance_orm import SnapDecisionRecordORM
from backend.app.models.abeyance_v3_orm import CompressionDiscoveryEventORM

logger = logging.getLogger(__name__)

MIN_POPULATION = 20
MIN_COMPRESSION_GAIN = 0.10
MAX_RULES = 5


class PatternCompressor:
    """Discovers compact rules explaining snap decision clusters."""

    async def analyze(
        self,
        session: AsyncSession,
        tenant_id: str,
        failure_mode_profile: str,
    ) -> Optional[CompressionDiscoveryEventORM]:
        """Analyze snap decisions for compressible patterns."""
        stmt = (
            select(SnapDecisionRecordORM)
            .where(
                SnapDecisionRecordORM.tenant_id == tenant_id,
                SnapDecisionRecordORM.failure_mode_profile == failure_mode_profile,
                SnapDecisionRecordORM.decision.in_(["SNAP", "NEAR_MISS"]),
            )
            .order_by(SnapDecisionRecordORM.evaluated_at.desc())
            .limit(1000)
        )
        result = await session.execute(stmt)
        decisions = list(result.scalars().all())

        if len(decisions) < MIN_POPULATION:
            return None

        # Extract dimension dominance patterns
        patterns = []
        for d in decisions:
            pattern = self._extract_pattern(d)
            patterns.append(pattern)

        # Find compressing rules
        rules = self._find_rules(patterns)
        if not rules:
            return None

        # Compute compression gain
        raw_bits = self._description_length(patterns)
        compressed_bits = self._compressed_length(patterns, rules)
        gain = 1.0 - (compressed_bits / max(raw_bits, 1.0))

        if gain < MIN_COMPRESSION_GAIN:
            return None

        # Coverage
        covered = sum(1 for p in patterns if any(self._matches_rule(p, r) for r in rules))
        coverage = covered / len(patterns)

        dominant = rules[0]["rule_type"] if rules else None

        event = CompressionDiscoveryEventORM(
            id=uuid4(),
            tenant_id=tenant_id,
            failure_mode_profile=failure_mode_profile,
            rules=[r for r in rules],
            compression_gain=round(gain, 4),
            coverage_ratio=round(coverage, 4),
            dominant_rule=dominant,
            population_size=len(decisions),
        )
        session.add(event)
        await session.flush()

        logger.info(
            "Pattern compression: tenant=%s profile=%s gain=%.4f coverage=%.4f",
            tenant_id, failure_mode_profile, gain, coverage,
        )
        return event

    @staticmethod
    def _extract_pattern(d: SnapDecisionRecordORM) -> dict:
        """Extract a hashable pattern from a snap decision."""
        scores = {
            "semantic": getattr(d, "score_semantic", None),
            "topological": getattr(d, "score_topological", None),
            "temporal": getattr(d, "score_temporal", None),
            "operational": getattr(d, "score_operational", None),
            "entity_overlap": getattr(d, "score_entity_overlap", None),
        }
        # Bin scores into HIGH/MED/LOW
        binned = {}
        for dim, score in scores.items():
            if score is None:
                binned[dim] = "NULL"
            elif score >= 0.7:
                binned[dim] = "HIGH"
            elif score >= 0.4:
                binned[dim] = "MED"
            else:
                binned[dim] = "LOW"
        return binned

    @staticmethod
    def _find_rules(patterns: list[dict]) -> list[dict]:
        """Find recurring patterns (most common dimension combinations)."""
        # Convert to tuples for counting
        tuple_patterns = [tuple(sorted(p.items())) for p in patterns]
        counter = Counter(tuple_patterns)

        rules = []
        total = len(patterns)
        for pattern_tuple, count in counter.most_common(MAX_RULES):
            if count / total < 0.05:
                break
            rule = dict(pattern_tuple)
            # Find dominant dimension
            high_dims = [k for k, v in rule.items() if v == "HIGH"]
            rule_type = f"DOM_{'_'.join(sorted(high_dims))}" if high_dims else "MIXED"
            rules.append({
                "rule_type": rule_type,
                "pattern": rule,
                "frequency": round(count / total, 4),
                "count": count,
            })
        return rules

    @staticmethod
    def _matches_rule(pattern: dict, rule: dict) -> bool:
        return all(pattern.get(k) == v for k, v in rule.get("pattern", {}).items())

    @staticmethod
    def _description_length(patterns: list[dict]) -> float:
        """Approximate description length in bits."""
        n = len(patterns)
        unique = len(set(tuple(sorted(p.items())) for p in patterns))
        if unique <= 1:
            return 0.0
        return n * math.log2(max(unique, 2))

    @staticmethod
    def _compressed_length(patterns: list[dict], rules: list[dict]) -> float:
        """Description length after applying compression rules."""
        n = len(patterns)
        covered = sum(
            1 for p in patterns
            if any(
                all(p.get(k) == v for k, v in r.get("pattern", {}).items())
                for r in rules
            )
        )
        uncovered = n - covered
        rule_cost = len(rules) * 5 * math.log2(3)  # 5 dims × 3 bins
        uncovered_cost = uncovered * 5 * math.log2(3)
        return rule_cost + uncovered_cost
