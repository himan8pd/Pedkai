"""
Digital Twin Mock (P5.2)

Provides heuristic predictions of KPI impact based on Decision Memory historical traces.
"""
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from backend.app.models.decision_trace_orm import DecisionTraceORM


@dataclass
class Prediction:
    risk_score: int
    impact_delta: float
    confidence_interval: str


class DigitalTwinMock:
    def __init__(self, session_factory=None):
        self.session_factory = session_factory

    async def predict(self, session: AsyncSession, action_type: str, entity_id: str, parameters: Optional[Dict[str, Any]] = None) -> Prediction:
        """Compute a heuristic prediction based on top-3 similar decisions in Decision Memory."""
        # Defensive: require session
        if session is None:
            # Fallback deterministic heuristic
            return Prediction(risk_score=50, impact_delta=0.05, confidence_interval="0.02-0.08")

        # Query DecisionTraceORM for recent similar actions
        # Note: DecisionTraceORM uses trigger_type for action classification
        stmt = select(DecisionTraceORM).where(DecisionTraceORM.trigger_type == action_type).order_by(DecisionTraceORM.created_at.desc()).limit(50)
        result = await session.execute(stmt)
        traces = result.scalars().all()

        # If not enough data, fallback heuristic
        if not traces or len(traces) < 3:
            # Simple heuristic: risk based on action type conservatism
            if action_type == "cell_failover":
                return Prediction(risk_score=35, impact_delta=0.08, confidence_interval="0.04-0.12")
            return Prediction(risk_score=50, impact_delta=0.03, confidence_interval="0.01-0.06")

        # Compute top-3 by simple recency-weighted metric (placeholder for similarity)
        top = traces[:3]
        weights = [0.5, 0.3, 0.2]
        weighted_impacts = []
        weighted_confidences = []
        total_weight = 0.0
        for t, w in zip(top, weights):
            # Expect DecisionTraceORM has fields: outcome_success (bool) and impact_delta (float)
            impact = getattr(t, "impact_delta", 0.05) or 0.05
            success = getattr(t, "outcome_success", True)
            conf = 0.9 if success else 0.4
            weighted_impacts.append(impact * w)
            weighted_confidences.append(conf * w)
            total_weight += w

        avg_impact = sum(weighted_impacts) / total_weight
        avg_conf = sum(weighted_confidences) / total_weight

        # Risk score inversely proportional to confidence
        risk_score = int(max(1, min(99, int((1.0 - avg_conf) * 100))))
        impact_delta = round(avg_impact, 4)
        ci_low = max(0.0, impact_delta - 0.02)
        ci_high = impact_delta + 0.02

        return Prediction(risk_score=risk_score, impact_delta=impact_delta, confidence_interval=f"{ci_low:.2f}-{ci_high:.2f}")
