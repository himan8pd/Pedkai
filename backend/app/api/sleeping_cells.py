"""
Sleeping Cells API Router.

Provides endpoints to retrieve and trigger sleeping cell detection scans.
The detector compares latest KPI values against a 7-day baseline to identify
cells with anomalous traffic degradation.
"""

import asyncio
import math
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Security
from pydantic import BaseModel
from sqlalchemy import text as sa_text

from backend.app.core.config import get_settings
from backend.app.core.database import async_session_maker, metrics_session_maker
from backend.app.core.logging import get_logger
from backend.app.core.security import INCIDENT_READ, User, get_current_user
from backend.app.events.schemas import SleepingCellDetectedEvent
from backend.app.services.sleeping_cell_detector import SleepingCellDetector

logger = get_logger(__name__)
router = APIRouter()
settings = get_settings()

# Module-level cache of last scan results keyed by (tenant_id, time_seed_hour)
# Keying by hour means different time seeds have independent caches.
_scan_cache: Dict[str, Dict[str, Any]] = {}

# Guards against concurrent scans for the same cache key
_scan_in_progress: Dict[str, bool] = {}

_detector = SleepingCellDetector()


def _cache_key(tenant_id: str, reference_time: Optional[datetime]) -> str:
    """Stable cache key incorporating the time seed (hourly granularity)."""
    if reference_time:
        return f"{tenant_id}:{reference_time.strftime('%Y-%m-%dT%H')}"
    return f"{tenant_id}:auto"


class SleepingCellResponse(BaseModel):
    cellId: str
    site: str
    domain: str
    kpiDeviation: float
    decayScore: float
    lastSeen: str
    status: str  # SLEEPING | RECOVERING | HEALTHY
    # Enriched fields
    entityName: Optional[str] = None   # human-readable CMDB name (e.g. NR_CELL-1234)
    entityType: Optional[str] = None   # entity type (NR_CELL, ENB, GNODEB, …)
    baselineMean: Optional[float] = None   # 7-day baseline KPI value
    currentValue: Optional[float] = None   # latest observed KPI value
    metricName: Optional[str] = None       # which KPI triggered detection


class SleepingCellsListResponse(BaseModel):
    cells: List[SleepingCellResponse]
    last_run: Optional[str] = None
    reference_time: Optional[str] = None  # ISO string of the time seed used


def _event_to_cell(
    event: SleepingCellDetectedEvent,
    name_map: Optional[Dict[str, Dict[str, str]]] = None,
) -> SleepingCellResponse:
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
    if math.isnan(z):
        decay_score = 1.0  # No data = worst case
    else:
        # z of -3 → ~0.5, z of -6 → 1.0
        decay_score = min(1.0, max(0.0, abs(z) / 6.0))

    # Status classification
    if decay_score >= 0.6:
        status = "SLEEPING"
    elif decay_score >= 0.3:
        status = "RECOVERING"
    else:
        status = "HEALTHY"

    # Resolve human-readable name from CMDB lookup map
    entity_name: Optional[str] = None
    entity_type: Optional[str] = None
    if name_map:
        info = name_map.get(str(event.entity_id))
        if info:
            # Prefer external_id (eNB-xxx style) over raw name
            entity_name = info.get("external_id") or info.get("name")
            entity_type = info.get("entity_type")

    # Display label: CMDB name if available, else compact UUID suffix
    display_label = entity_name or f"…{str(event.entity_id)[-8:]}"

    return SleepingCellResponse(
        cellId=str(event.entity_id),
        site=display_label,
        domain=event.metric_name,
        kpiDeviation=round(kpi_deviation, 2),
        decayScore=round(decay_score, 3),
        lastSeen=event.timestamp.isoformat(),
        status=status,
        entityName=entity_name,
        entityType=entity_type,
        baselineMean=round(baseline, 4) if baseline is not None else None,
        currentValue=round(current, 4) if current is not None else None,
        metricName=event.metric_name,
    )


async def _lookup_entity_names(
    entity_ids: List[str], tenant_id: str
) -> Dict[str, Dict[str, str]]:
    """Batch-lookup human-readable names from network_entities (graph DB).

    Returns a dict of entity_id → {name, external_id, entity_type}.
    Falls back gracefully to an empty dict on any error.
    """
    if not entity_ids:
        return {}
    try:
        async with async_session_maker() as session:
            result = await session.execute(
                sa_text(
                    """
                    SELECT id::text, name, external_id, entity_type
                    FROM network_entities
                    WHERE id::text = ANY(:ids)
                      AND tenant_id = :tid
                    """
                ),
                {"ids": entity_ids, "tid": tenant_id},
            )
            return {
                row[0]: {
                    "name": row[1],
                    "external_id": row[2],
                    "entity_type": row[3],
                }
                for row in result.fetchall()
            }
    except Exception as exc:
        logger.warning(f"Entity name lookup failed: {exc}")
        return {}


async def _run_scan_and_cache(
    tenant_id: str,
    reference_time: Optional[datetime] = None,
) -> None:
    """Run a full sleeping cell scan and populate the cache.

    Safe to call as a fire-and-forget background task.  Concurrent calls for
    the same (tenant, time_seed) pair are deduplicated — if a scan is already
    in progress the second call returns immediately.

    Args:
        tenant_id: Tenant to scan.
        reference_time: Analysis reference point.  None → auto-detect from
            max(kpi_metrics.timestamp).  A specific datetime lets users slice
            historical data (e.g. "analyse as of 2026-04-07").
    """
    key = _cache_key(tenant_id, reference_time)
    if _scan_in_progress.get(key):
        logger.info(f"Sleeping cell scan already in progress for {key}, skipping")
        return
    _scan_in_progress[key] = True
    try:
        # Resolve reference time (auto-detect if not provided)
        ref_time = reference_time or await _resolve_reference_time(tenant_id)

        events = await _detector.scan(tenant_id, reference_time=ref_time)

        # Batch-lookup CMDB entity names for human-readable display
        entity_ids = list({str(e.entity_id) for e in events})
        name_map = await _lookup_entity_names(entity_ids, tenant_id)

        cells = [_event_to_cell(evt, name_map) for evt in events]
        last_run = datetime.now(timezone.utc).isoformat()

        _scan_cache[key] = {
            "cells": cells,
            "last_run": last_run,
            "reference_time": ref_time.isoformat() if ref_time else None,
        }
        logger.info(
            f"Sleeping cell scan complete for {key}: {len(cells)} cells "
            f"(ref={ref_time}, named={len(name_map)})"
        )
    except Exception as e:
        logger.error(f"Sleeping cell scan failed for {key}: {e}", exc_info=True)
    finally:
        _scan_in_progress[key] = False


async def _resolve_reference_time(tenant_id: str) -> Optional[datetime]:
    """Determine the actual KPI data epoch for this tenant.

    Uses a two-pass strategy to avoid being fooled by load-time ingestion
    artifacts — rows whose ``timestamp`` was set to the server clock at the
    moment of bulk-load rather than the simulation/historic timestamp.

    Pass 1 (historic / demo mode):
        MAX(timestamp) from rows older than 48 h.  For a dataset that was
        bulk-loaded today but covers e.g. Apr 1-13, this returns Apr 13
        (the real data edge) and ignores the load-day outliers.

    Pass 2 fallback (live mode):
        If all data is recent (< 48 h old) the dataset is live; return
        MAX(timestamp) unconditionally.
    """
    try:
        async with metrics_session_maker() as session:
            now = datetime.now(timezone.utc)
            cutoff_48h = now - timedelta(hours=48)

            result = await session.execute(
                sa_text(
                    """
                    SELECT COALESCE(
                        (SELECT MAX(timestamp)
                         FROM kpi_metrics
                         WHERE tenant_id = :tid
                           AND timestamp < :cutoff),
                        (SELECT MAX(timestamp)
                         FROM kpi_metrics
                         WHERE tenant_id = :tid)
                    )
                    """
                ),
                {"tid": tenant_id, "cutoff": cutoff_48h},
            )
            max_ts = result.scalar()
            return max_ts if max_ts else None
    except Exception as e:
        logger.warning(f"Could not determine KPI reference time: {e}")
        return None


@router.get("/reference-time")
async def get_reference_time(
    current_user: User = Security(get_current_user, scopes=[INCIDENT_READ]),
):
    """Return the auto-detected analysis reference time (max KPI timestamp).

    Used by the frontend to pre-populate the time seed picker.
    """
    tenant_id = current_user.tenant_id or settings.default_tenant_id
    ref_time = await _resolve_reference_time(tenant_id)
    return {
        "reference_time": ref_time.isoformat() if ref_time else None,
        "tenant_id": tenant_id,
    }


@router.get("", response_model=SleepingCellsListResponse)
async def get_sleeping_cells(
    reference_time: Optional[str] = Query(
        None,
        description="ISO-8601 datetime to use as analysis reference point. "
        "Omit to use the most recent cached scan.",
    ),
    current_user: User = Security(get_current_user, scopes=[INCIDENT_READ]),
):
    """Return the latest sleeping cell detection results from cache.

    Pass ``reference_time`` to retrieve results for a specific time slice
    (if that slice has been computed).  Results for different time seeds are
    cached independently.
    """
    tenant_id = current_user.tenant_id or settings.default_tenant_id

    # Parse optional time seed
    ref_dt: Optional[datetime] = None
    if reference_time:
        try:
            ref_dt = datetime.fromisoformat(reference_time)
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid reference_time format")

    key = _cache_key(tenant_id, ref_dt)
    cached = _scan_cache.get(key)

    if cached:
        return SleepingCellsListResponse(
            cells=cached["cells"],
            last_run=cached["last_run"],
            reference_time=cached.get("reference_time"),
        )

    # No cached results for this key — return empty
    return SleepingCellsListResponse(cells=[], last_run=None, reference_time=None)


@router.post("/detect", response_model=SleepingCellsListResponse)
async def detect_sleeping_cells(
    reference_time: Optional[str] = Query(
        None,
        description="ISO-8601 datetime to use as the analysis reference point. "
        "Defaults to max(kpi_metrics.timestamp) for the tenant.",
    ),
    current_user: User = Security(get_current_user, scopes=[INCIDENT_READ]),
):
    """Trigger sleeping cell detection.

    Returns cached results immediately (if available for this time seed) and
    fires a background refresh.  Never blocks the HTTP connection, avoiding
    Cloudflare 524 gateway timeouts on slow queries.

    Pass ``reference_time`` to run analysis relative to a specific historical
    point — e.g. "analyse as of 2026-04-07T00:00:00" to look 7 days back
    from that date.
    """
    tenant_id = current_user.tenant_id or settings.default_tenant_id

    # Parse optional time seed
    ref_dt: Optional[datetime] = None
    if reference_time:
        try:
            ref_dt = datetime.fromisoformat(reference_time)
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid reference_time format")

    key = _cache_key(tenant_id, ref_dt)

    # Fire background refresh (deduplicated — no-op if already running)
    asyncio.create_task(_run_scan_and_cache(tenant_id, ref_dt))

    # Return cached results immediately if warm for this time seed
    cached = _scan_cache.get(key)
    if cached:
        return SleepingCellsListResponse(
            cells=cached["cells"],
            last_run=cached["last_run"],
            reference_time=cached.get("reference_time"),
        )

    # Cold cache — return empty; client should poll GET after a few seconds
    return SleepingCellsListResponse(cells=[], last_run=None, reference_time=None)
