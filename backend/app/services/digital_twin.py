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
from backend.app.models.decision_trace import SimilarDecisionQuery
from backend.app.services.decision_repository import DecisionTraceRepository
from backend.app.services.llm_adapter import get_adapter
from backend.app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class Prediction:
    risk_score: int
    impact_delta: float
    confidence_interval: str


class DigitalTwinMock:
    def __init__(self, session_factory=None):
        self.session_factory = session_factory

    async def predict(self, session: AsyncSession, action_type: str, entity_id: str, parameters: Optional[Dict[str, Any]] = None) -> Prediction:
        """Compute a prediction based on semantically similar decisions in Decision Memory."""
        if session is None:
            return Prediction(risk_score=50, impact_delta=0.05, confidence_interval="0.02-0.08")

        try:
            # 1. Generate search context string
            context_str = f"Action: {action_type} on Entity: {entity_id}. Params: {parameters}"
            
            # 2. Generate embedding for query
            adapter = get_adapter()
            query_embedding = await adapter.embed(context_str)
            
            # 3. Find similar decisions in memory
            # Use a slightly wider search threshold than the default confidence gate
            repo = DecisionTraceRepository(None) # Factory not needed if passing session
            query = SimilarDecisionQuery(
                tenant_id="global",  # Search across tenants for "Twin" knowledge
                limit=5,
                min_similarity=0.7,
                embedding_provider=adapter.__class__.__name__.lower().replace("adapter", ""),
            )
            
            similar = await repo.find_similar(query, query_embedding, session=session)
            
            if not similar or len(similar) < 2:
                # Fallback to trigger_type heuristic if no semantic matches
                logger.info(f"DigitalTwin: Low semantic matches for {action_type}, falling back to type-based heuristic.")
                return self._heuristic_fallback(action_type)

            # 4. Synthesize top-3 results
            top_3 = similar[:3]
            weighted_impacts = []
            weighted_success_rates = []
            total_sim = 0.0

            for decision, sim in top_3:
                # outcome_success might be in outcome dict
                success = 0.0
                if decision.outcome and getattr(decision.outcome, "success_score", None) is not None:
                    success = decision.outcome.success_score / 100.0
                elif decision.outcome and getattr(decision.outcome, "technical_outcome", None) == "success":
                    success = 1.0
                
                # Estimated impact from historical data
                impact = 0.05
                if decision.outcome and hasattr(decision.outcome, "metrics_delta"):
                    # Use a representative delta (e.g., first one found)
                    deltas = decision.outcome.metrics_delta
                    if deltas and isinstance(deltas, dict):
                        impact = abs(next(iter(deltas.values()), 0.05))

                weighted_impacts.append(impact * sim)
                weighted_success_rates.append(success * sim)
                total_sim += sim

            avg_impact = sum(weighted_impacts) / total_sim
            avg_success = sum(weighted_success_rates) / total_sim

            # Risk score inversely proportional to success rate and similarity
            # High success + High similarity = Low risk
            risk_score = int(max(1, min(99, int((1.0 - avg_success) * 100))))
            
            impact_delta = round(avg_impact, 4)
            ci_low = max(0.0, impact_delta - 0.02)
            ci_high = impact_delta + 0.02

            return Prediction(
                risk_score=risk_score,
                impact_delta=impact_delta,
                confidence_interval=f"{ci_low:.2f}-{ci_high:.2f}"
            )

        except Exception as e:
            logger.exception(f"DigitalTwin similarity search failed: {e}")
            return self._heuristic_fallback(action_type)

    def _heuristic_fallback(self, action_type: str) -> Prediction:
        """Fallback deterministic heuristic for risk/impact."""
        if action_type == "cell_failover":
            return Prediction(risk_score=35, impact_delta=0.08, confidence_interval="0.04-0.12")
        elif action_type == "connection_throttle":
            return Prediction(risk_score=20, impact_delta=0.03, confidence_interval="0.01-0.05")
        return Prediction(risk_score=50, impact_delta=0.05, confidence_interval="0.02-0.08")
