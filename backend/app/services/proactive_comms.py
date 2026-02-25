"""
Proactive Communications Service.

Drafts customer communications for human review when service issues are detected.
All communications are set to 'draft_pending_review' status — they are NEVER sent automatically.

Design principle: Pedkai recommends, humans decide. No automated customer contact.

Used by: WS4 (service_impact API), WS2 (incidents API).
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy import select
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)


class ProactiveCommsService:
    """
    Drafts proactive customer communications for human review.

    IMPORTANT: All communications have status='draft_pending_review'.
    This service never sends communications automatically.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self.session_factory = session_factory

    @asynccontextmanager
    async def _get_session(self, session: Optional[AsyncSession] = None):
        if session:
            yield session
        else:
            async with self.session_factory() as new_session:
                try:
                    yield new_session
                    await new_session.commit()
                except Exception:
                    await new_session.rollback()
                    raise
                finally:
                    await new_session.close()

    def should_notify_customer(
        self,
        customer_id: UUID,
        is_affected: bool,
        estimated_ttr_minutes: float,
        sla_threshold_minutes: float,
    ) -> bool:
        """
        Determine if a customer should be notified.

        Returns True ONLY if:
        1. The customer IS affected by the incident, AND
        2. The estimated TTR exceeds the SLA threshold
        """
        if not is_affected:
            return False
        return estimated_ttr_minutes > sla_threshold_minutes

    async def check_consent(self, customer_id: UUID, session: Optional[AsyncSession] = None) -> bool:
        """
        Check if the customer has opted in to proactive communications.
        """
        try:
            from backend.app.models.customer_orm import CustomerORM
            async with self._get_session(session) as s:
                result = await s.execute(
                    select(CustomerORM).where(CustomerORM.id == customer_id)
                )
                customer = result.scalar_one_or_none()
                if customer is None:
                    logger.warning(f"Customer {customer_id} not found for consent check")
                    return False
                return getattr(customer, "consent_proactive_comms", False)
        except Exception as e:
            logger.warning(f"Could not check consent for customer {customer_id}: {e}")
            return False

    async def draft_communication(
        self,
        customer_id: UUID,
        incident_summary: str,
        channel: str = "email",
        session: Optional[AsyncSession] = None,
    ) -> Dict[str, Any]:
        """
        Draft a communication for human review.
        """
        # Check consent before drafting
        has_consent = await self.check_consent(customer_id, session=session)
        if not has_consent:
            logger.info(f"Customer {customer_id} has not consented to proactive comms — skipping draft")
            return {
                "status": "skipped_no_consent",
                "customer_id": str(customer_id),
                "reason": "Customer has not opted in to proactive communications",
            }

        draft_id = str(uuid.uuid4())
        draft = {
            "draft_id": draft_id,
            "customer_id": str(customer_id),
            "channel": channel,
            "status": "draft_pending_review",  # NEVER "sent"
            "subject": "Service Update from Your Network Provider",
            "body": (
                f"Dear Valued Customer,\n\n"
                f"We are writing to inform you of a service issue that may affect your service.\n\n"
                f"{incident_summary}\n\n"
                f"Our engineering team is actively working to resolve this. "
                f"We will provide further updates as the situation develops.\n\n"
                f"We apologise for any inconvenience caused.\n\n"
                f"Kind regards,\nNetwork Operations Centre"
            ),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "review_required": True,
            "review_note": (
                "This communication was drafted by Pedkai. "
                "A human must review and approve before sending."
            ),
        }

        logger.info(f"Drafted communication {draft_id} for customer {customer_id} via {channel}")
        return draft
