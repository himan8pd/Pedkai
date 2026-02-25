from uuid import UUID
from typing import Dict, Any, Optional
from backend.app.models.decision_trace import DecisionTrace, DecisionOutcome
from backend.app.services.policy_engine import get_policy_engine
from backend.app.core.logging import get_logger

# Configure logging
logger = get_logger(__name__)

class RLEvaluatorService:
    """
    Closed-Loop RL Evaluator.
    Automatically upvotes or downvotes decisions based on technical outcomes 
    and adherence to the Telco Constitution (Policy Engine).
    """
    
    # Reward Constants
    REWARD_SUCCESS = 5
    PENALTY_FAILURE = -10
    PENALTY_POLICY_VIOLATION = -5
    BONUS_CONSTITUTIONAL = 2

    def __init__(self, db_session=None):
        self.db_session = db_session

    async def evaluate_decision_outcome(self, decision: DecisionTrace) -> int:
        """
        Calculates the total reward for a decision based on its outcome and policy compliance.
        Finding C-2 FIX: Now uses real KPI improvements from metrics DB.
        """
        if not decision.outcome:
            logger.warning(f"Evaluator skipped: No outcome recorded for decision {decision.id}")
            return 0
            
        # 1. Technical Outcome Reward via KPI Delta (Real Closed-Loop)
        total_reward = await self._calculate_kpi_improvement_reward(decision)
        
        # 2. Policy Adherence Check
        policy_context = self._construct_policy_context(decision)
        engine = get_policy_engine()
        policy_result = engine.evaluate(policy_context)
        
        if not policy_result.allowed:
            total_reward += self.PENALTY_POLICY_VIOLATION
            logger.warning(f"RL Evaluator: Decision {decision.id} violated policy: {policy_result.reason}. Penalty: {self.PENALTY_POLICY_VIOLATION}")
        else:
            if decision.outcome.status == DecisionOutcome.SUCCESS and len(policy_result.applied_policies) > 0:
                total_reward += self.BONUS_CONSTITUTIONAL
                logger.info(f"RL Evaluator: Decision {decision.id} followed Constitution. Bonus: {self.BONUS_CONSTITUTIONAL}")
                
        return total_reward

    async def _calculate_kpi_improvement_reward(self, decision: DecisionTrace) -> int:
        """
        Finding C-2: Query Metrics to see if the action actually improved the network.
        Now considers:
        1. Pre-decision baseline (avg of 30m window before)
        2. Post-decision performance (avg of 30m window after)
        3. Improvement delta vs threshold
        """
        try:
            from sqlalchemy import select, func, and_
            from backend.app.models.kpi_orm import KPIMetricORM
            from datetime import timedelta
            
            # 1. Identify the target KPI and Entity from context
            entity_id = decision.context.affected_entities[0] if decision.context.affected_entities else None
            
            # Finding H-7 FIX: Hardened Metric Mapping
            # First check if context explicitly defines the target metric (Ground Truth)
            target_metric = decision.context.external_context.get("target_metric")
            
            if not target_metric:
                # Fallback to enhanced heuristic mapping
                desc = decision.trigger_description.lower()
                if any(x in desc for x in ["latency", "ping", "delay"]):
                    target_metric = "latency"
                elif any(x in desc for x in ["drop", "disconnect", "failure"]):
                    target_metric = "call_drop_rate"
                elif any(x in desc for x in ["congestion", "prb", "heavy traffic", "overloaded"]):
                    target_metric = "prb_utilization"
                else:
                    target_metric = "throughput" # Default

            if not entity_id:
                logger.warning(f"RL Evaluator: No entity_id found for decision {decision.id}, cannot check KPIs.")
                return 0

            # 2. Define Time Windows
            decision_time = decision.decision_made_at
            window_pre_start = decision_time - timedelta(minutes=30)
            window_post_end = decision_time + timedelta(minutes=30)
            
            # 3. Query Pre-Decision Baseline
            res_pre = await self.db_session.execute(
                select(func.avg(KPIMetricORM.value))
                .where(and_(
                    KPIMetricORM.entity_id == entity_id,
                    KPIMetricORM.metric_name == target_metric,
                    KPIMetricORM.timestamp.between(window_pre_start, decision_time)
                ))
            )
            baseline = res_pre.scalar() or 0.0

            # 4. Query Post-Decision Performance
            res_post = await self.db_session.execute(
                select(func.avg(KPIMetricORM.value))
                .where(and_(
                    KPIMetricORM.entity_id == entity_id,
                    KPIMetricORM.metric_name == target_metric,
                    KPIMetricORM.timestamp.between(decision_time, window_post_end)
                ))
            )
            post_value = res_post.scalar()
            
            # If no post-data yet (e.g., immediate check), we can't evaluate
            if post_value is None:
                logger.info(f"RL Evaluator: No post-decision data yet for {decision.id}. Skipping reward.")
                return 0

            # 5. Calculate Improvement
            is_minimization = target_metric in ["latency", "call_drop_rate", "prb_utilization"]
            
            if is_minimization:
                if baseline == 0: baseline = 0.001
                delta_pct = (baseline - post_value) / baseline
            else:
                if baseline == 0: baseline = 0.001
                delta_pct = (post_value - baseline) / baseline

            logger.info(f"RL Metric Check for {decision.id}: {target_metric} went from {baseline:.2f} to {post_value:.2f} (Delta: {delta_pct:.2%})")

            # 6. Assign Reward (Finding H-6 FIX: Use Policy Engine Parameters)
            engine = get_policy_engine()
            reward_threshold = engine.get_parameter("rl_reward_improvement_threshold", 0.10)
            penalty_threshold = engine.get_parameter("rl_penalty_degradation_threshold", -0.05)

            if delta_pct > reward_threshold:
                return int(self.REWARD_SUCCESS + (delta_pct * 10)) # Scaled reward
            elif delta_pct < penalty_threshold:
                return self.PENALTY_FAILURE
            else:
                return 0 # Neutral/Noise
                
        except Exception as e:
            logger.error(f"KPI Reward Calculation failed: {e}")
            return 0

    def _construct_policy_context(self, decision: DecisionTrace) -> Dict[str, Any]:
        """Maps decision context to Policy Engine evaluation schema."""
        ctx = decision.context
        
        # Extract variables used in global_policies.yaml
        # (service_type, customer_tier, network_load, predicted_revenue_loss)
        return {
            "service_type": ctx.external_context.get("service_type", "DATA"),
            "slice_id": ctx.external_context.get("slice_id", ""),
            "customer_tier": ctx.external_context.get("customer_tier", "BRONZE"),
            "network_load": ctx.external_context.get("network_load", 0),
            "predicted_revenue_loss": ctx.external_context.get("predicted_revenue_loss", 0),
            "affected_entities": ctx.affected_entities
        }

    async def apply_feedback(self, decision_id: UUID, reward: int):
        """Records the calculated reward as system-generated feedback."""
        if reward == 0:
            return
            
        if not self.db_session:
            logger.error("RL Evaluator: No DB session available to apply feedback.")
            return
            
        from backend.app.services.decision_repository import DecisionTraceRepository
        repo = DecisionTraceRepository(self.db_session)
        
        # We record the feedback with a specific system operator ID
        # The reward score is normalized or kept as-is (repository aggregates them)
        success = await repo.record_feedback(
            decision_id, 
            operator_id="pedkai:rl_evaluator", 
            score=reward
        )
        
        if success:
            logger.info(f"RL Evaluator: Applied {reward} feedback to decision {decision_id}")
            await self.db_session.flush()
        else:
            logger.error(f"RL Evaluator: Failed to record feedback for decision {decision_id}")

# Factory function
def get_rl_evaluator(db_session=None):
    return RLEvaluatorService(db_session)
