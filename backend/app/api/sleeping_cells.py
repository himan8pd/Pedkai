"""
Sleeping Cells API Router.

Provides endpoints to retrieve and trigger sleeping cell detection scans.
The detector compares latest KPI values against a 7-day baseline to identify
cells with anomalous traffic degradation.
"""

import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Security
from pydantic import BaseModel
from sqlalchemy import text as sa_text

from backend.app.core.config import get_settings
from backend.app.core.database import metrics_session_maker
from backend.app.core.logging import get_logger
from backend.app.core.security import INCIDENT_READ, User, get_current_user
from backend.app.events.schemas import SleepingCellDetectedEvent
from backend.app.services.sleeping_cell_detector import SleepingCellDetector

logger = get_logger(__name__)
router = APIRouter()
settings = get_settings()

# Module-level cache of last scan results per tenant
_scan_cache: Dict[str, Dict[str, Any]] = {}

_detector = SleepingCellDetector()


class SleepingCellResponse(BaseModel):
    cellId: str
    site: str
    domain: str
    kpiDeviation: float
    decayScore: float
    lastSeen: str
    status: str  # SLEEPING | RECOVERING | HEALTHY


class SleepingCellsListResponse(BaseModel):
    cells: List[SleepingCellResponse]
    last_run: Optional[str] = None


def _event_to_cell(event: SleepingCellDetectedEvent) -> SleepingCellResponse:
    """Map a SleepingCellDetectedEvent to the frontend SleepingCell shape."""
    z = event.z_score
    baseline = event.baseline_mean
    current = event.current_value

    # KPI deviation as percentage from baseline
    if baseline and baseline > 0 and current is not None:
        kpi_deviation = ((current - baseline) / baseline) * 100.0
    elif current is None:
        # No signal at all — treat as -100% deviation
        kpi_deviation = -100.0
    else:
        kpi_deviation = 0.0

    # Decay score: normalise z-score to 0-1 range (higher = worse)
    # z_score is negative for degradation; NaN means idle/no data
    if math.isnan(z):
        decay_score = 1.0  # No data = worst case
    else:
        # z of -3 maps to ~0.6, z of -6 maps to ~1.0
        decay_score = min(1.0, max(0.0, abs(z) / 6.0))

    # Status classification
    if decay_score >= 0.6:
        status = "SLEEPING"
    elif decay_score >= 0.3:
        status = "RECOVERING"
    else:
        status = "HEALTHY"

    return SleepingCellResponse(
        cellId=event.entity_id,
        site=event.entity_id,  # entity_id is the best identifier available
        domain=event.metric_name,
        kpiDeviation=round(kpi_deviation, 2),
        decayScore=round(decay_score, 3),
        lastSeen=event.timestamp.isoformat() if event.timestamp else datetime.now(timezone.utc).isoformat(),
        status=status,
    )


async def _resolve_reference_time(tenant_id: str) -> Optional[datetime]:
    """Determine reference time from actual data for historic/demo mode."""
    try:
        async with metrics_session_maker() as session:
            result = await session.execute(
                sa_text("SELECT MAX(timestamp) FROM kpi_metrics WHERE tenant_id = :tid"),
                {"tid": tenant_id},
            )
            max_ts = result.scalar()
            return max_ts if max_ts else None
    except Exception as e:
        logger.warning(f"Could not determine KPI reference time: {e}")
        return None


@router.get("/", response_model=SleepingCellsListResponse)
async def get_sleeping_cells(
    current_user: User = Security(get_current_user, scopes=[INCIDENT_READ]),
):
    """Return the latest sleeping cell detection results from cache."""
    tenant_id = current_user.tenant_id or settings.default_tenant_id
    cached = _scan_cache.get(tenant_id)

    if cached:
        return SleepingCellsListResponse(
            cells=cached["cells"],
            last_run=cached["last_run"],
        )

    # No cached results — return empty
    return SleepingCellsListResponse(cells=[], last_run=None)


@router.post("/detect", response_model=SleepingCellsListResponse)
async def detect_sleeping_cells(
    current_user: User = Security(get_current_user, scopes=[INCIDENT_READ]),
):
    """Trigger an on-demand sleeping cell detection scan."""
    tenant_id = current_user.tenant_id or settings.default_tenant_id

    try:
        ref_time = await _resolve_reference_time(tenant_id)
        events = await _detector.scan(tenant_id, reference_time=ref_time)
    except Exception as e:
        logger.error(f"Sleeping cell scan failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Detection scan failed: {e}")

    cells = [_event_to_cell(evt) for evt in events]
    last_run = datetime.now(timezone.utc).isoformat()

    # Cache results for the GET endpoint
    _scan_cache[tenant_id] = {"cells": cells, "last_run": last_run}

    return SleepingCellsListResponse(cells=cells, last_run=last_run)
