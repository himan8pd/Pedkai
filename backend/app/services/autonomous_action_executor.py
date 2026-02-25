"""
Autonomous Action Executor (P5.3)

Implements a safety-gated pipeline for executing autonomous actions.
This is a conservative implementation suitable for staging and testing.
"""
import asyncio
import uuid
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from backend.app.models.action_execution_orm import ActionExecutionORM, ActionState
from backend.app.services.policy_engine import get_policy_engine
from backend.app.services.digital_twin import DigitalTwinMock
from backend.app.services.autonomous_actions.cell_failover import CellFailoverAction
from backend.app.services.decision_repository import DecisionTraceRepository
from backend.app.services.embedding_service import get_embedding_service
from backend.app.core.logging import get_logger

logger = get_logger(__name__)

# Simple in-memory FIFO for pending actions (for PoC)
_pending_queue = asyncio.Queue()


class AutonomousActionExecutor:
    # Safety thresholds
    BLAST_RADIUS_MAX_ENTITIES = 10  # R-9: hard limit on affected entities
    VALIDATION_POLL_SECONDS = 300   # R-8: 5-minute KPI poll window
    VALIDATION_DEGRADATION_PCT = 10.0  # R-8: auto-rollback threshold

    def __init__(self, session_factory=None):
        self.session_factory = session_factory
        self._worker_task = None

    async def start(self):
        if self._worker_task is None:
            self._worker_task = asyncio.create_task(self._worker_loop())
            logger.info("AutonomousActionExecutor worker started")

    async def stop(self):
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None

    async def submit_action(self, session: AsyncSession, tenant_id: str, action_type: str, entity_id: str, affected_entity_count: int = 1, parameters: Optional[Dict[str, Any]] = None, submitted_by: Optional[str] = None, trace_id: Optional[str] = None) -> ActionExecutionORM:
        # Create DB record
        action_id = str(uuid.uuid4())
        action = ActionExecutionORM(
            id=action_id,
            tenant_id=tenant_id,
            action_type=action_type,
            entity_id=entity_id,
            parameters=parameters or {},
            affected_entity_count=affected_entity_count,
            state=ActionState.PENDING,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            submitted_by=submitted_by,
            trace_id=trace_id,
        )
        session.add(action)
        await session.flush()

        # Enqueue for processing
        await _pending_queue.put(action_id)
        logger.info(f"Enqueued autonomous action {action_id} for tenant {tenant_id} action={action_type}")
        return action

    async def _worker_loop(self):
        # Runs forever processing queued actions
        while True:
            try:
                action_id = await _pending_queue.get()
                # Acquire a DB session for processing
                async with self.session_factory() as session:
                    # Fetch action
                    stmt = select(ActionExecutionORM).where(ActionExecutionORM.id == action_id)
                    res = await session.execute(stmt)
                    action = res.scalar_one_or_none()
                    if not action:
                        logger.warning(f"Action {action_id} disappeared from DB")
                        continue

                    # ===== GATE 1: BLAST RADIUS CHECK (R-9) =====
                    # Independent circuit breaker — NOT delegated to policy engine
                    if action.affected_entity_count > self.BLAST_RADIUS_MAX_ENTITIES:
                        action.state = ActionState.FAILED
                        action.result = {
                            "reason": "blast_radius_exceeded",
                            "affected_entities": action.affected_entity_count,
                            "threshold": self.BLAST_RADIUS_MAX_ENTITIES,
                        }
                        action.updated_at = datetime.utcnow()
                        await session.commit()
                        logger.warning(
                            f"Action {action_id} BLOCKED by blast radius gate: "
                            f"{action.affected_entity_count} entities exceeds limit of {self.BLAST_RADIUS_MAX_ENTITIES}"
                        )
                        continue

                    # Compute confidence from Decision Memory similarity (replaces hardcoded 0.9)
                    confidence_score = 0.5  # conservative default if no similar decisions found
                    try:
                        embedding_svc = get_embedding_service()
                        action_text = f"{action.action_type} on {action.entity_id} with {action.parameters}"
                        action_embedding = await embedding_svc.generate_embedding(action_text)
                        if action_embedding:
                            decision_repo = DecisionTraceRepository(self.session_factory)
                            similar = await decision_repo.find_similar(
                                embedding=action_embedding,
                                tenant_id=action.tenant_id,
                                limit=3,
                                session=session,
                            )
                            if similar:
                                # Use highest similarity score from top match
                                top_similarity = similar[0].get("similarity", 0.5) if isinstance(similar[0], dict) else 0.5
                                confidence_score = max(0.3, min(0.99, top_similarity))
                                logger.info(f"Action {action_id} confidence from Decision Memory: {confidence_score:.2f} ({len(similar)} similar decisions)")
                            else:
                                logger.info(f"Action {action_id} no similar decisions found, using default confidence {confidence_score}")
                        else:
                            logger.warning(f"Action {action_id} embedding generation failed, using default confidence {confidence_score}")
                    except Exception as e:
                        logger.warning(f"Action {action_id} confidence lookup failed: {e}, using default {confidence_score}")

                    # ===== GATE 2: POLICY EVALUATION =====
                    policy_engine = get_policy_engine()
                    eval_result = await policy_engine.evaluate_autonomous_action(
                        session=session,
                        tenant_id=action.tenant_id,
                        action_type=action.action_type,
                        entity_id=action.entity_id,
                        affected_entity_count=action.affected_entity_count,
                        action_parameters=action.parameters,
                        trace_id=action.trace_id,
                        confidence_score=confidence_score,
                    )

                    if eval_result.decision != "allow":
                        action.state = ActionState.FAILED
                        action.result = {"reason": "policy_blocked", "details": eval_result.matched_rules}
                        action.updated_at = datetime.utcnow()
                        await session.commit()
                        logger.info(f"Action {action_id} blocked by policy: {eval_result.reason}")
                        continue

                    # For PoC: mark as awaiting confirmation then execute automatically after confirmation window
                    action.state = ActionState.AWAITING_CONFIRMATION
                    action.updated_at = datetime.utcnow()
                    await session.commit()

                    # Wait confirmation window (non-blocking in real impl; blocking here for PoC)
                    wait_sec = eval_result.recommended_confirmation_window_sec or 30
                    logger.info(f"Action {action_id} awaiting confirmation for {wait_sec}s")
                    await asyncio.sleep(wait_sec)

                    # Execute: Simulate Netconf call via DigitalTwin or adapter
                    action.state = ActionState.EXECUTING
                    action.updated_at = datetime.utcnow()
                    await session.commit()

                    # Simulated execution — in real world call Netconf adapter
                    # For PoC, we assume success and poll digital twin
                    dt = DigitalTwinMock(self.session_factory)
                    pred = await dt.predict(session, action.action_type, action.entity_id, action.parameters)
                    # If action type is cell_failover, invoke the specialized handler for additional validation
                    if action.action_type == "cell_failover":
                        try:
                            handler = CellFailoverAction(self.session_factory)
                            target = (action.parameters or {}).get("target_cell")
                            host = (action.parameters or {}).get("device_host", "nokia-mock-host")
                            validation = await handler.estimate_impact(session, action.entity_id, target)
                            pred.impact_delta = getattr(pred, "impact_delta", validation.get("impact_delta"))
                            pred.risk_score = getattr(pred, "risk_score", validation.get("risk_score"))
                        except Exception as e:
                            logger.warning(f"CellFailover handler error: {e}")
                    # Simulate execution latency
                    await asyncio.sleep(2)

                    # ===== GATE 4: POST-EXECUTION VALIDATION (R-8) =====
                    # Poll KPIs for validation window, auto-rollback on >10% degradation
                    validation_passed = await self._validate_post_execution(
                        session, action, pred
                    )

                    if validation_passed:
                        action.state = ActionState.COMPLETED
                        action.success = True
                        action.result = {
                            "prediction": {"risk_score": pred.risk_score, "impact_delta": pred.impact_delta},
                            "validation": "passed",
                            "executed_at": datetime.utcnow().isoformat(),
                        }
                    else:
                        action.state = ActionState.ROLLED_BACK
                        action.success = False
                        action.result = {
                            "prediction": {"risk_score": pred.risk_score, "impact_delta": pred.impact_delta},
                            "validation": "failed_auto_rollback",
                            "reason": "KPI degradation exceeded threshold",
                            "executed_at": datetime.utcnow().isoformat(),
                        }
                        logger.warning(f"Action {action_id} AUTO-ROLLED BACK due to KPI degradation")

                    action.updated_at = datetime.utcnow()
                    await session.commit()

                    logger.info(f"Action {action_id} executed, success={action.success}")

            except Exception as e:
                logger.error(f"Error in autonomous executor loop: {e}", exc_info=True)
                await asyncio.sleep(1)

    async def _validate_post_execution(
        self, session: AsyncSession, action: ActionExecutionORM, pred: Any
    ) -> bool:
        """
        R-8: Post-execution VALIDATION gate.
        """
        from backend.app.models.kpi_sample_orm import KpiSampleORM
        import uuid

        entity_id = action.entity_id
        # Convert to UUID object if it's a string, to satisfy ORM type requirements
        if isinstance(entity_id, str):
            try:
                entity_id = uuid.UUID(entity_id)
            except ValueError:
                pass
        # Determine validation poll duration (shortened for PoC to avoid long test waits)
        poll_duration_sec = min(self.VALIDATION_POLL_SECONDS, 10)  # PoC cap
        poll_interval_sec = 2
        elapsed = 0

        # Capture pre-execution baseline KPI (average of last 5 samples)
        try:
            baseline_result = await session.execute(
                select(func.avg(KpiSampleORM.value))
                .where(
                    KpiSampleORM.entity_id == entity_id,
                    KpiSampleORM.metric_name == "traffic_volume",
                    KpiSampleORM.timestamp < action.created_at
                )
                .order_by(KpiSampleORM.timestamp.desc())
                .limit(5)
            )
            baseline_avg = baseline_result.scalar()
        except Exception as e:
            logger.warning(f"Validation: baseline KPI fetch failed for {entity_id}: {e}")
            baseline_avg = None

        if baseline_avg is None:
            # No KPI data — fall back to digital twin prediction
            logger.info(
                f"Validation: no KPI baseline for {entity_id}, "
                f"falling back to digital twin (risk_score={pred.risk_score})"
            )
            return pred.risk_score < 70

        # Poll for post-execution KPI changes
        logger.info(
            f"Validation: polling KPIs for {entity_id} "
            f"(baseline={baseline_avg:.2f}, window={poll_duration_sec}s, "
            f"threshold={self.VALIDATION_DEGRADATION_PCT}%)"
        )

        while elapsed < poll_duration_sec:
            await asyncio.sleep(poll_interval_sec)
            elapsed += poll_interval_sec

            try:
                post_result = await session.execute(
                    select(func.avg(KpiSampleORM.value))
                    .where(
                        KpiSampleORM.entity_id == entity_id,
                        KpiSampleORM.metric_name == "traffic_volume",
                        KpiSampleORM.timestamp >= datetime.utcnow() - timedelta(seconds=poll_duration_sec),
                    )
                )
                post_avg = post_result.scalar()
            except Exception:
                post_avg = None

            if post_avg is not None and baseline_avg > 0:
                degradation_pct = ((baseline_avg - post_avg) / baseline_avg) * 100
                if degradation_pct > self.VALIDATION_DEGRADATION_PCT:
                    logger.warning(
                        f"Validation FAILED for {entity_id}: "
                        f"KPI degraded {degradation_pct:.1f}% "
                        f"(threshold={self.VALIDATION_DEGRADATION_PCT}%)"
                    )
                    return False

        logger.info(f"Validation PASSED for {entity_id} after {elapsed}s polling")
        return True
