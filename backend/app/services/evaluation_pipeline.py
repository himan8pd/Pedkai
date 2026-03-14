"""
Continuous Evaluation Pipeline for Pedk.ai NOC Platform.

Tracks 3 key metrics to measure platform value:
1. CMDB Accuracy Rate — % of discovered dark nodes later confirmed in CMDB
2. MTTR Correlation — Pearson r between SITREP quality score and MTTR reduction
3. Discovery Rate — dark nodes discovered per 100 reconciliation events
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class EvaluationMetrics:
    tenant_id: str
    period_start: datetime
    period_end: datetime
    cmdb_accuracy_rate: float       # 0.0-1.0: dark nodes confirmed / total dark nodes discovered
    mttr_correlation: float         # -1.0 to 1.0: Pearson r between sitrep_quality and mttr_reduction
    discovery_rate: float           # dark nodes per 100 reconciliation events
    total_decisions: int
    total_feedback_records: int
    benchmark_threshold: float = 0.9  # from product spec — Decision Memory benchmark

    def passes_benchmark(self) -> bool:
        """Returns True if cmdb_accuracy_rate >= benchmark_threshold."""
        return self.cmdb_accuracy_rate >= self.benchmark_threshold

    def to_dict(self) -> dict:
        return {
            "tenant_id": self.tenant_id,
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "cmdb_accuracy_rate": round(self.cmdb_accuracy_rate, 4),
            "mttr_correlation": round(self.mttr_correlation, 4),
            "discovery_rate": round(self.discovery_rate, 4),
            "total_decisions": self.total_decisions,
            "total_feedback_records": self.total_feedback_records,
            "passes_benchmark": self.passes_benchmark(),
        }


class EvaluationPipeline:
    def __init__(self, benchmark_threshold: float = 0.9):
        self.benchmark_threshold = benchmark_threshold

    async def compute_cmdb_accuracy_rate(self, tenant_id: str, since: datetime, db_session) -> float:
        """Query ReconciliationResultORM for dark nodes, check how many were later confirmed.

        A dark node is "confirmed" if its entity_id later appears in NetworkEntityORM
        with source='cmdb'. If no records exist, return 0.0 gracefully.

        Note: NetworkEntityORM does not have a 'source' field. We approximate confirmation
        by checking whether the dark node's target_id appears as an external_id in
        NetworkEntityORM for the same tenant (implying CMDB ingestion occurred).
        """
        try:
            from sqlalchemy import select, func
            from backend.app.models.reconciliation_result_orm import ReconciliationResultORM
            from backend.app.models.network_entity_orm import NetworkEntityORM

            # Fetch all dark node target_ids discovered since the given date
            dark_node_stmt = (
                select(ReconciliationResultORM.target_id)
                .where(
                    ReconciliationResultORM.tenant_id == tenant_id,
                    ReconciliationResultORM.divergence_type == "dark_node",
                    ReconciliationResultORM.created_at >= since,
                )
            )
            dark_node_result = await db_session.execute(dark_node_stmt)
            dark_node_ids = [row[0] for row in dark_node_result.fetchall() if row[0] is not None]

            if not dark_node_ids:
                return 0.0

            total_dark_nodes = len(dark_node_ids)

            # Count how many of those dark node target_ids now appear as external_id in NetworkEntityORM
            confirmed_stmt = (
                select(func.count(NetworkEntityORM.id))
                .where(
                    NetworkEntityORM.tenant_id == tenant_id,
                    NetworkEntityORM.external_id.in_(dark_node_ids),
                )
            )
            confirmed_result = await db_session.execute(confirmed_stmt)
            confirmed_count = confirmed_result.scalar() or 0

            return float(confirmed_count) / float(total_dark_nodes)

        except Exception as exc:
            logger.warning("compute_cmdb_accuracy_rate failed gracefully: %s", exc)
            return 0.0

    async def compute_mttr_correlation(self, tenant_id: str, since: datetime, db_session) -> float:
        """Compute Pearson correlation between decision sitrep_quality_score and
        incident resolution_time_minutes from IncidentORM.

        Join DecisionTraceORM <-> IncidentORM on entity_id + tenant_id.
        Compute pearsonr from scipy.stats. Return 0.0 if fewer than 5 data points.
        Return 0.0 gracefully if either model doesn't have the required fields.

        Note: Neither DecisionTraceORM nor IncidentORM has explicit sitrep_quality_score
        or resolution_time_minutes columns. We use confidence_score from DecisionTraceORM
        as a proxy for sitrep quality, and derive resolution_time from
        (closed_at - created_at) in IncidentORM where available.
        """
        try:
            from scipy.stats import pearsonr
            from sqlalchemy import select
            from backend.app.models.decision_trace_orm import DecisionTraceORM
            from backend.app.models.incident_orm import IncidentORM

            # Fetch decisions with confidence_score and entity_id
            decision_stmt = (
                select(
                    DecisionTraceORM.entity_id,
                    DecisionTraceORM.confidence_score,
                )
                .where(
                    DecisionTraceORM.tenant_id == tenant_id,
                    DecisionTraceORM.created_at >= since,
                    DecisionTraceORM.entity_id.isnot(None),
                    DecisionTraceORM.confidence_score.isnot(None),
                )
            )
            decision_result = await db_session.execute(decision_stmt)
            decision_rows = decision_result.fetchall()

            if not decision_rows:
                return 0.0

            # Build a map of entity_id -> confidence_score (latest / first match)
            entity_quality: dict = {}
            for entity_id, confidence in decision_rows:
                if entity_id not in entity_quality:
                    entity_quality[entity_id] = confidence

            # Fetch incidents that have both entity_id and closed_at (so we can compute resolution time)
            incident_stmt = (
                select(
                    IncidentORM.entity_id,
                    IncidentORM.created_at,
                    IncidentORM.closed_at,
                )
                .where(
                    IncidentORM.tenant_id == tenant_id,
                    IncidentORM.entity_id.isnot(None),
                    IncidentORM.closed_at.isnot(None),
                    IncidentORM.created_at.isnot(None),
                )
            )
            incident_result = await db_session.execute(incident_stmt)
            incident_rows = incident_result.fetchall()

            quality_scores = []
            mttr_values = []

            for entity_id, created_at, closed_at in incident_rows:
                if entity_id not in entity_quality:
                    continue
                # Compute resolution_time_minutes
                if hasattr(closed_at, 'timestamp') and hasattr(created_at, 'timestamp'):
                    resolution_minutes = (closed_at - created_at).total_seconds() / 60.0
                else:
                    continue
                quality_scores.append(entity_quality[entity_id])
                mttr_values.append(resolution_minutes)

            if len(quality_scores) < 5:
                return 0.0

            r, _ = pearsonr(quality_scores, mttr_values)
            # pearsonr can return nan if std dev is zero
            if r != r:  # nan check
                return 0.0
            return float(r)

        except Exception as exc:
            logger.warning("compute_mttr_correlation failed gracefully: %s", exc)
            return 0.0

    async def compute_discovery_rate(self, tenant_id: str, since: datetime, db_session) -> float:
        """Count dark nodes discovered per 100 reconciliation runs in the period.

        dark_nodes_found / total_recon_runs * 100
        Return 0.0 if no reconciliation runs.
        """
        try:
            from sqlalchemy import select, func
            from backend.app.models.reconciliation_result_orm import (
                ReconciliationResultORM,
                ReconciliationRunORM,
            )

            # Count total reconciliation runs for the tenant in the period
            run_stmt = (
                select(func.count(ReconciliationRunORM.run_id))
                .where(
                    ReconciliationRunORM.tenant_id == tenant_id,
                    ReconciliationRunORM.started_at >= since,
                )
            )
            run_result = await db_session.execute(run_stmt)
            total_runs = run_result.scalar() or 0

            if total_runs == 0:
                return 0.0

            # Count dark nodes discovered in the period
            dark_stmt = (
                select(func.count(ReconciliationResultORM.result_id))
                .where(
                    ReconciliationResultORM.tenant_id == tenant_id,
                    ReconciliationResultORM.divergence_type == "dark_node",
                    ReconciliationResultORM.created_at >= since,
                )
            )
            dark_result = await db_session.execute(dark_stmt)
            dark_nodes_found = dark_result.scalar() or 0

            return float(dark_nodes_found) / float(total_runs) * 100.0

        except Exception as exc:
            logger.warning("compute_discovery_rate failed gracefully: %s", exc)
            return 0.0

    async def run_evaluation(
        self,
        tenant_id: str,
        lookback_days: int = 30,
        db_session=None,
    ) -> EvaluationMetrics:
        """Run all 3 metrics for the tenant and return EvaluationMetrics.

        If db_session is None, return stub metrics with 0.0 values (offline mode).
        """
        period_end = datetime.utcnow()
        period_start = period_end - timedelta(days=lookback_days)

        if db_session is None:
            # Offline / stub mode
            return EvaluationMetrics(
                tenant_id=tenant_id,
                period_start=period_start,
                period_end=period_end,
                cmdb_accuracy_rate=0.0,
                mttr_correlation=0.0,
                discovery_rate=0.0,
                total_decisions=0,
                total_feedback_records=0,
                benchmark_threshold=self.benchmark_threshold,
            )

        since = period_start

        cmdb_accuracy = await self.compute_cmdb_accuracy_rate(tenant_id, since, db_session)
        mttr_corr = await self.compute_mttr_correlation(tenant_id, since, db_session)
        disc_rate = await self.compute_discovery_rate(tenant_id, since, db_session)

        # Count total decisions and feedback records for the period
        total_decisions = 0
        total_feedback = 0
        try:
            from sqlalchemy import select, func
            from backend.app.models.decision_trace_orm import DecisionTraceORM, DecisionFeedbackORM

            dec_stmt = (
                select(func.count(DecisionTraceORM.id))
                .where(
                    DecisionTraceORM.tenant_id == tenant_id,
                    DecisionTraceORM.created_at >= since,
                )
            )
            dec_result = await db_session.execute(dec_stmt)
            total_decisions = dec_result.scalar() or 0

            fb_stmt = (
                select(func.count(DecisionFeedbackORM.id))
                .where(DecisionFeedbackORM.created_at >= since)
            )
            fb_result = await db_session.execute(fb_stmt)
            total_feedback = fb_result.scalar() or 0
        except Exception as exc:
            logger.warning("Failed to count decisions/feedback gracefully: %s", exc)

        return EvaluationMetrics(
            tenant_id=tenant_id,
            period_start=period_start,
            period_end=period_end,
            cmdb_accuracy_rate=cmdb_accuracy,
            mttr_correlation=mttr_corr,
            discovery_rate=disc_rate,
            total_decisions=total_decisions,
            total_feedback_records=total_feedback,
            benchmark_threshold=self.benchmark_threshold,
        )

    async def check_benchmark(self, tenant_id: str, db_session) -> dict:
        """Run evaluation and return benchmark pass/fail with details."""
        metrics = await self.run_evaluation(tenant_id=tenant_id, db_session=db_session)
        result = metrics.to_dict()
        result["benchmark_passed"] = metrics.passes_benchmark()
        result["benchmark_threshold"] = metrics.benchmark_threshold
        return result


def get_evaluation_pipeline(threshold: float = 0.9) -> EvaluationPipeline:
    return EvaluationPipeline(benchmark_threshold=threshold)
