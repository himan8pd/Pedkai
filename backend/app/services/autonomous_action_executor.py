"""
Autonomous Action Executor (P5.3)

Implements a safety-gated pipeline for executing autonomous actions.
This is a conservative implementation suitable for staging and testing.
"""
import asyncio
import uuid
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.app.models.action_execution_orm import ActionExecutionORM, ActionState
from backend.app.services.policy_engine import get_policy_engine
from backend.app.services.digital_twin import DigitalTwinMock
from backend.app.services.autonomous_actions.cell_failover import CellFailoverAction

logger = logging.getLogger(__name__)

# Simple in-memory FIFO for pending actions (for PoC)
_pending_queue = asyncio.Queue()


class AutonomousActionExecutor:
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

                    # Gate: Policy evaluation
                    policy_engine = get_policy_engine()
                    eval_result = await policy_engine.evaluate_autonomous_action(
                        session=session,
                        tenant_id=action.tenant_id,
                        action_type=action.action_type,
                        entity_id=action.entity_id,
                        affected_entity_count=action.affected_entity_count,
                        action_parameters=action.parameters,
                        trace_id=action.trace_id,
                        confidence_score=0.9,  # placeholder; Decision Memory should supply
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
                            # parameters expected to include 'target_cell' and 'device_host' for PoC
                            target = (action.parameters or {}).get("target_cell")
                            host = (action.parameters or {}).get("device_host", "nokia-mock-host")
                            validation = await handler.estimate_impact(session, action.entity_id, target)
                            # merge prediction info
                            pred.impact_delta = getattr(pred, "impact_delta", validation.get("impact_delta"))
                            pred.risk_score = getattr(pred, "risk_score", validation.get("risk_score"))
                        except Exception as e:
                            logger.warning(f"CellFailover handler error: {e}")
                    # Simulate execution latency
                    await asyncio.sleep(2)

                    # Validation (simulate KPI check)
                    # For PoC, assume success if pred.risk_score < 70
                    success = pred.risk_score < 70
                    action.state = ActionState.COMPLETED if success else ActionState.ROLLED_BACK
                    action.success = bool(success)
                    action.result = {"prediction": {"risk_score": pred.risk_score, "impact_delta": pred.impact_delta}, "executed_at": datetime.utcnow().isoformat()}
                    action.updated_at = datetime.utcnow()
                    await session.commit()

                    logger.info(f"Action {action_id} executed, success={action.success}")

            except Exception as e:
                logger.error(f"Error in autonomous executor loop: {e}", exc_info=True)
                await asyncio.sleep(1)
