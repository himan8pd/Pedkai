"""Health check endpoints and data-status API."""

from datetime import datetime, timezone

from fastapi import APIRouter, Query
from sqlalchemy import text as sa_text

router = APIRouter()


@router.get("/health")
async def health_check():
    """Basic health check endpoint."""
    return {"status": "healthy"}


@router.get("/ready")
async def readiness_check():
    """
    Readiness check - verify dependencies are available.
    Fails if critical dependencies (DB) are down.
    """
    health_status = {
        "status": "ready",
        "checks": {
            "database": "unknown",
            "metrics_db": "unknown",
        },
    }

    # Check Primary Graph DB
    try:
        from backend.app.core.database import engine

        async with engine.connect() as conn:
            await conn.execute(sa_text("SELECT 1"))
        health_status["checks"]["database"] = "ok"
    except Exception as e:
        health_status["checks"]["database"] = f"failed: {str(e)}"
        health_status["status"] = "not_ready"

    # Check Metrics DB
    try:
        from backend.app.core.database import metrics_engine

        async with metrics_engine.connect() as conn:
            await conn.execute(sa_text("SELECT 1"))
        health_status["checks"]["metrics_db"] = "ok"
    except Exception as e:
        health_status["checks"]["metrics_db"] = f"failed: {str(e)}"
        health_status["status"] = "not_ready"

    # Check Kafka (Optional for startup, critical for processing)
    # We skip Kafka strict check for now to avoid hard crash if broker is slow

    if health_status["status"] != "ready":
        from fastapi import Response, status

        return Response(
            content=str(health_status),
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            media_type="application/json",
        )

    return health_status


@router.get("/api/v1/data-status")
async def data_status(
    tenant_id: str = Query("pedkai_telco2_01", description="Tenant ID to inspect"),
):
    """
    Return data time-range, mode (historic vs live), and row counts for a tenant.

    Used by the frontend to render a historic-mode banner when the dataset
    is retrospective rather than real-time.
    """
    from backend.app.core.database import engine as graph_engine
    from backend.app.core.database import metrics_engine

    result: dict = {
        "tenant_id": tenant_id,
        "mode": "unknown",
        "data_period": {"earliest": None, "latest": None},
        "entity_count": 0,
        "alarm_count": 0,
        "kpi_row_count": 0,
    }

    # --- Graph DB queries (entities, alarms) ---
    try:
        async with graph_engine.connect() as conn:
            # Entity count
            row = await conn.execute(
                sa_text("SELECT COUNT(*) FROM network_entities WHERE tenant_id = :tid"),
                {"tid": tenant_id},
            )
            result["entity_count"] = row.scalar() or 0

            # Alarm count + time range
            row = await conn.execute(
                sa_text(
                    "SELECT COUNT(*), MIN(raised_at), MAX(raised_at) "
                    "FROM telco_events_alarms WHERE tenant_id = :tid"
                ),
                {"tid": tenant_id},
            )
            alarm_row = row.fetchone()
            if alarm_row:
                result["alarm_count"] = alarm_row[0] or 0
                alarm_earliest = alarm_row[1]
                alarm_latest = alarm_row[2]
            else:
                alarm_earliest = alarm_latest = None
    except Exception:
        alarm_earliest = alarm_latest = None

    # --- Metrics DB queries (kpi_metrics) ---
    kpi_earliest = kpi_latest = None
    try:
        async with metrics_engine.connect() as conn:
            row = await conn.execute(
                sa_text(
                    "SELECT COUNT(*), MIN(timestamp), MAX(timestamp) "
                    "FROM kpi_metrics WHERE tenant_id = :tid"
                ),
                {"tid": tenant_id},
            )
            kpi_row = row.fetchone()
            if kpi_row:
                result["kpi_row_count"] = kpi_row[0] or 0
                kpi_earliest = kpi_row[1]
                kpi_latest = kpi_row[2]
    except Exception:
        pass

    # Determine overall earliest / latest across both tables
    candidates_earliest = [t for t in [alarm_earliest, kpi_earliest] if t is not None]
    candidates_latest = [t for t in [alarm_latest, kpi_latest] if t is not None]

    overall_earliest = min(candidates_earliest) if candidates_earliest else None
    overall_latest = max(candidates_latest) if candidates_latest else None

    if overall_earliest:
        result["data_period"]["earliest"] = overall_earliest.isoformat()
    if overall_latest:
        result["data_period"]["latest"] = overall_latest.isoformat()

    # Mode: if the most recent data point is > 24 h old → historic
    if overall_latest:
        now_utc = datetime.now(timezone.utc)
        # Ensure overall_latest is tz-aware for comparison
        if overall_latest.tzinfo is None:
            overall_latest = overall_latest.replace(tzinfo=timezone.utc)
        age_hours = (now_utc - overall_latest).total_seconds() / 3600
        result["mode"] = "historic" if age_hours > 24 else "live"
    else:
        result["mode"] = "unknown"

    return result
