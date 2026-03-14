"""
ServiceNow Observer — Behavioural Feedback Pipeline.

Polls ServiceNow ITSM for operator actions, correlates them with AI recommendations
stored in DecisionTraceORM, and writes BehaviouralFeedback records.
"""

import os
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional
from uuid import uuid4

import httpx
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.decision_trace_orm import DecisionTraceORM

logger = logging.getLogger(__name__)

VALID_ACTION_TYPES = {"acknowledge", "escalate", "resolve", "modify_priority", "close"}


@dataclass
class ITSMAction:
    ticket_id: str
    entity_id: str
    action_type: str  # "acknowledge","escalate","resolve","modify_priority","close"
    operator_id: str
    tenant_id: str
    timestamp: datetime
    notes: Optional[str] = None
    resolution_code: Optional[str] = None
    modified_fields: Optional[dict] = None


@dataclass
class BehaviouralFeedback:
    decision_id: str
    tenant_id: str
    operator_id: str
    recommendation_followed: bool
    delta_actions: list
    outcome_label: str  # "aligned","partial","overridden","ignored"
    confidence: float
    itsm_action: ITSMAction
    timestamp: datetime


class ServiceNowObserver:
    """
    Polls ServiceNow for recent ITSM actions, correlates them with AI
    recommendations, and stores BehaviouralFeedback for RL training.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_token: Optional[str] = None,
        poll_interval_seconds: int = 300,
    ):
        self.base_url = base_url.rstrip("/") if base_url else None
        self.api_token = api_token
        self.poll_interval_seconds = poll_interval_seconds

    # ------------------------------------------------------------------
    # HTTP polling
    # ------------------------------------------------------------------

    async def poll_recent_actions(
        self, tenant_id: str, since: datetime
    ) -> list[ITSMAction]:
        """
        GET {base_url}/api/now/table/incident?sysparm_query=sys_updated_on>{since}&sysparm_limit=100

        Returns [] if base_url is None (offline mode) or on any httpx error.
        """
        if self.base_url is None:
            return []

        since_str = since.strftime("%Y-%m-%d %H:%M:%S")
        url = (
            f"{self.base_url}/api/now/table/incident"
            f"?sysparm_query=sys_updated_on>{since_str}&sysparm_limit=100"
        )
        headers = {"Accept": "application/json"}
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            logger.warning("ServiceNow poll failed: %s", exc)
            return []
        except Exception as exc:
            logger.warning("ServiceNow poll unexpected error: %s", exc)
            return []

        actions: list[ITSMAction] = []
        for record in data.get("result", []):
            action_type = self._map_state_to_action(record)
            if action_type not in VALID_ACTION_TYPES:
                continue
            try:
                ts_raw = record.get("sys_updated_on", "")
                ts = datetime.strptime(ts_raw, "%Y-%m-%d %H:%M:%S").replace(
                    tzinfo=timezone.utc
                )
            except (ValueError, TypeError):
                ts = datetime.now(timezone.utc)

            actions.append(
                ITSMAction(
                    ticket_id=record.get("sys_id", ""),
                    entity_id=record.get("cmdb_ci", {}).get("value", "")
                    if isinstance(record.get("cmdb_ci"), dict)
                    else record.get("cmdb_ci", ""),
                    action_type=action_type,
                    operator_id=record.get("assigned_to", {}).get("value", "unknown")
                    if isinstance(record.get("assigned_to"), dict)
                    else record.get("assigned_to", "unknown"),
                    tenant_id=tenant_id,
                    timestamp=ts,
                    notes=record.get("work_notes"),
                    resolution_code=record.get("close_code"),
                    modified_fields=None,
                )
            )
        return actions

    def _map_state_to_action(self, record: dict) -> str:
        """Map ServiceNow incident state integer to an action type string."""
        state = str(record.get("state", ""))
        mapping = {
            "2": "acknowledge",
            "3": "escalate",
            "6": "resolve",
            "7": "close",
        }
        # Check for priority modification
        if record.get("priority_changed"):
            return "modify_priority"
        return mapping.get(state, record.get("action_type", "unknown"))

    # ------------------------------------------------------------------
    # Correlation
    # ------------------------------------------------------------------

    async def correlate_with_recommendation(
        self,
        action: ITSMAction,
        tenant_id: str,
        db_session: Optional[AsyncSession] = None,
    ) -> Optional[BehaviouralFeedback]:
        """
        Find the most recent DecisionTraceORM for the action's entity_id and
        compute an outcome_label:
          - "aligned"   if action matches recommended action
          - "overridden" if a different action was taken
          - "ignored"   if no recommendation exists / no action within time window
          - "partial"   if action partially overlaps recommendation
        """
        if db_session is None:
            return None

        # Query most recent decision trace for entity
        try:
            stmt = (
                select(DecisionTraceORM)
                .where(
                    DecisionTraceORM.tenant_id == tenant_id,
                    DecisionTraceORM.entity_id == action.entity_id,
                )
                .order_by(desc(DecisionTraceORM.decision_made_at))
                .limit(1)
            )
            result = await db_session.execute(stmt)
            trace = result.scalar_one_or_none()
        except Exception as exc:
            logger.warning("DB query for decision trace failed: %s", exc)
            return None

        if trace is None:
            # No recommendation found → ignored
            outcome_label = "ignored"
            decision_id = str(uuid4())
            confidence = 0.0
            recommendation_followed = False
            delta_actions = [action.action_type]
        else:
            decision_id = str(trace.id)
            confidence = float(trace.confidence_score or 0.0)
            recommended = (trace.action_taken or "").lower()
            taken = action.action_type.lower()

            if taken in recommended or recommended in taken:
                outcome_label = "aligned"
                recommendation_followed = True
                delta_actions = []
            elif taken and recommended and (
                self._action_overlap(taken, recommended)
            ):
                outcome_label = "partial"
                recommendation_followed = False
                delta_actions = [taken]
            else:
                outcome_label = "overridden"
                recommendation_followed = False
                delta_actions = [taken]

        return BehaviouralFeedback(
            decision_id=decision_id,
            tenant_id=tenant_id,
            operator_id=action.operator_id,
            recommendation_followed=recommendation_followed,
            delta_actions=delta_actions,
            outcome_label=outcome_label,
            confidence=confidence,
            itsm_action=action,
            timestamp=datetime.now(timezone.utc),
        )

    def _action_overlap(self, taken: str, recommended: str) -> bool:
        """Return True if there is a partial semantic overlap between actions."""
        overlap_groups = [
            {"acknowledge", "escalate"},
            {"resolve", "close"},
        ]
        for group in overlap_groups:
            if taken in group and recommended in group:
                return True
        return False

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def store_feedback(
        self, feedback: BehaviouralFeedback, db_session: AsyncSession
    ) -> None:
        """
        Persist feedback. Currently logs and could write to a feedback table.
        Structured to be extended with a BehaviouralFeedbackORM in future.
        """
        logger.info(
            "BehaviouralFeedback stored: decision_id=%s tenant=%s outcome=%s",
            feedback.decision_id,
            feedback.tenant_id,
            feedback.outcome_label,
        )
        # Placeholder: update DecisionTraceORM.feedback_score if aligned
        if feedback.outcome_label == "aligned":
            try:
                stmt = select(DecisionTraceORM).where(
                    DecisionTraceORM.id == feedback.decision_id
                )
                result = await db_session.execute(stmt)
                trace = result.scalar_one_or_none()
                if trace is not None:
                    trace.feedback_score = (trace.feedback_score or 0) + 1
                    db_session.add(trace)
                    await db_session.flush()
            except Exception as exc:
                logger.warning("Failed to update feedback_score: %s", exc)

    # ------------------------------------------------------------------
    # Observation cycle
    # ------------------------------------------------------------------

    async def run_observation_cycle(
        self, tenant_id: str, db_session: AsyncSession
    ) -> int:
        """
        Full cycle: poll → correlate → store. Returns count of feedbacks stored.
        """
        since = datetime.now(timezone.utc) - timedelta(
            seconds=self.poll_interval_seconds
        )
        actions = await self.poll_recent_actions(tenant_id, since)

        stored = 0
        for action in actions:
            feedback = await self.correlate_with_recommendation(
                action, tenant_id, db_session
            )
            if feedback is not None:
                await self.store_feedback(feedback, db_session)
                stored += 1

        return stored


# ------------------------------------------------------------------
# Factory
# ------------------------------------------------------------------


def get_servicenow_observer(base_url: Optional[str] = None) -> ServiceNowObserver:
    """Read SERVICENOW_URL and SERVICENOW_API_TOKEN from environment."""
    url = base_url or os.environ.get("SERVICENOW_URL")
    token = os.environ.get("SERVICENOW_API_TOKEN")
    return ServiceNowObserver(base_url=url, api_token=token)
