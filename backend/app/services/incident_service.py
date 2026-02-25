from datetime import datetime, timezone
import uuid
import logging
from typing import Optional
from uuid import UUID
from backend.app.services.bss_adapter import MockBSSAdapter, BSSAdapter

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.incident_orm import IncidentORM
from backend.app.schemas.incidents import IncidentCreate, IncidentSeverity, IncidentStatus

logger = logging.getLogger(__name__)


async def create_incident_from_cluster(payload: IncidentCreate, session: AsyncSession, tenant_id: Optional[str] = None, bss_adapter: Optional[BSSAdapter] = None) -> IncidentORM:
    """Create an incident record from service code (used by P2.2 handler).

    Mirrors API logic in `backend/app/api/incidents.py` but accepts an AsyncSession.
    """
    is_emergency = False
    severity = payload.severity

    if payload.entity_id and 'EMERGENCY' in str(payload.entity_id).upper():
        is_emergency = True

    if is_emergency:
        severity = IncidentSeverity.CRITICAL

    incident = IncidentORM(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id or payload.tenant_id,
        title=payload.title,
        severity=severity.value,
        status=IncidentStatus.ANOMALY.value,
        entity_id=str(payload.entity_id) if payload.entity_id else None,
        entity_external_id=payload.entity_external_id,
        created_at=datetime.now(timezone.utc),
    )
    session.add(incident)
    await session.flush()
    await session.refresh(incident)
    logger.info(f"Incident created: {incident.id} (tenant={incident.tenant_id})")

    # Try to enrich incident with revenue-at-risk using BSS adapter (best-effort)
    try:
        adapter = bss_adapter or MockBSSAdapter()
        customer_ids = []
        # Heuristic: if payload.entity_external_id looks like a UUID, treat it as customer id
        if payload.entity_external_id:
            try:
                customer_ids = [UUID(str(payload.entity_external_id))]
            except Exception:
                customer_ids = []

        if customer_ids:
            rev = await adapter.get_revenue_at_risk(customer_ids)
            logger.info(f"BSS revenue-at-risk for incident {incident.id}: {rev.total_revenue_at_risk}")
    except Exception as e:
        logger.debug(f"BSS enrichment skipped for incident {incident.id}: {e}")

    return incident
