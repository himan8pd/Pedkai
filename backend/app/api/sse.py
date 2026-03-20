"""
Server-Sent Events (SSE) endpoint for real-time alarm and incident push.
Replaces the 10-second polling loop in the frontend.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional, Set

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import get_settings
from backend.app.core.database import get_db
from backend.app.core.security import User, decode_token_string, get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()

# Track active SSE connections
_active_connections: Set[str] = set()
settings = get_settings()


async def alarm_event_generator(
    request: Request, db: AsyncSession, tenant_id: str, user_id: str
):
    """
    Generate SSE events for new alarms. Includes:
    - Heartbeat every 30s to keep connection alive
    - 5-minute idle timeout to close stale connections
    - DB polling every 2s for new alarms
    """
    connection_id = f"{user_id}:{tenant_id}:{id(request)}"

    # Check if max connections exceeded
    if len(_active_connections) >= settings.sse_max_connections:
        logger.warning(f"SSE max connections ({settings.sse_max_connections}) reached")
        yield f": max_connections_exceeded\n\n"
        return

    _active_connections.add(connection_id)
    logger.info(
        f"SSE connection opened: {connection_id} (total: {len(_active_connections)})"
    )

    last_seen_id = None
    last_data_time = datetime.now(
        timezone.utc
    ).timestamp()  # Tracks real data events only
    last_heartbeat_time = datetime.now(
        timezone.utc
    ).timestamp()  # Tracks heartbeat sends
    heartbeat_interval = settings.sse_heartbeat_interval_seconds
    idle_timeout = settings.sse_max_idle_seconds
    poll_interval = 2  # Poll DB every 2s

    try:
        while True:
            # Check if client disconnected
            if await request.is_disconnected():
                logger.info(f"SSE client disconnected: {connection_id}")
                break

            now = datetime.now(timezone.utc).timestamp()

            # Check idle timeout (based on last REAL data, not heartbeats)
            if now - last_data_time > idle_timeout:
                logger.info(
                    f"SSE connection idle timeout ({idle_timeout}s): {connection_id}"
                )
                yield f": idle_timeout\n\n"
                break

            # Send heartbeat at regular intervals (does NOT reset idle timer)
            if now - last_heartbeat_time > heartbeat_interval:
                yield f": heartbeat\n\n"
                last_heartbeat_time = now
                await asyncio.sleep(0.1)
                continue

            # Poll for alarms — union security_events (CasinoLimit demo)
            # with telco_events_alarms (Telco2 live dataset)
            try:
                query = text("""
                    SELECT id, specific_problem, perceived_severity,
                           alarmed_object_id, event_time
                    FROM (
                        SELECT id, technique_name AS specific_problem,
                               severity AS perceived_severity,
                               machine_name AS alarmed_object_id,
                               detected_at AS event_time
                        FROM security_events
                        WHERE tenant_id = :tid
                        UNION ALL
                        SELECT alarm_id AS id, alarm_type AS specific_problem,
                               severity AS perceived_severity,
                               entity_id AS alarmed_object_id,
                               raised_at AS event_time
                        FROM telco_events_alarms
                        WHERE tenant_id = :tid
                    ) combined
                    ORDER BY event_time DESC
                    LIMIT 20
                """)
                result = await db.execute(query, {"tid": tenant_id})
                rows = result.fetchall()

                if rows:
                    newest_id = str(rows[0][0])
                    if newest_id != last_seen_id:
                        last_seen_id = newest_id
                        last_data_time = now  # Only real data resets the idle timer
                        last_heartbeat_time = now  # Also reset heartbeat on data
                        alarms = []
                        for r in rows:
                            alarms.append(
                                {
                                    "id": str(r[0]),
                                    "specificProblem": r[1],
                                    "perceivedSeverity": r[2] or "major",
                                    "alarmedObject": {"id": r[3] or "unknown"},
                                    "eventTime": r[4].isoformat() if r[4] else None,
                                    "tenant_id": tenant_id,
                                }
                            )
                        payload = {
                            "event": "alarms_updated",
                            "tenant_id": tenant_id,
                            "count": len(rows),
                            "alarms": alarms,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                        yield f"data: {json.dumps(payload)}\n\n"
            except Exception as e:
                logger.error(f"SSE generator error: {e}")
                yield f"data: {json.dumps({'event': 'error', 'message': str(e)})}\n\n"

            await asyncio.sleep(poll_interval)
    finally:
        # Cleanup on disconnect (whether client or timeout)
        _active_connections.discard(connection_id)
        logger.info(
            f"SSE connection closed: {connection_id} (remaining: {len(_active_connections)})"
        )
        try:
            await db.close()
        except Exception:
            pass


@router.get("/stream/alarms")
async def stream_alarms(
    request: Request,
    tenant_id: Optional[str] = None,
    token: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """
    SSE endpoint: streams alarm update notifications to connected clients.
    EventSource API cannot send Authorization headers, so the JWT token
    is passed as a query parameter: ?token=<jwt>&tenant_id=<tenant>.

    Authentication:
    - If `token` is provided, it is decoded to extract tenant_id and user identity.
    - If only `tenant_id` is provided (legacy), a deprecation warning is logged
      and the stream proceeds without authentication.
    - If neither is provided, returns 401.

    Features:
    - Sends heartbeat every 30s to keep connection alive
    - Closes connection after 5 minutes of inactivity
    - Returns HTTP 503 if max concurrent connections exceeded
    """
    # Resolve user identity and tenant from token or legacy query param
    user_id = "anonymous"
    resolved_tenant_id = tenant_id

    if token:
        user = decode_token_string(token)
        resolved_tenant_id = user.tenant_id or tenant_id
        user_id = user.username
    elif tenant_id:
        logger.warning(
            "SSE /stream/alarms called with tenant_id only (no token). "
            "This is deprecated — pass ?token=<jwt> for authenticated streams."
        )
    else:
        raise HTTPException(
            status_code=401,
            detail="Missing authentication token. Pass ?token=<jwt> query parameter.",
        )

    if not resolved_tenant_id:
        raise HTTPException(
            status_code=400,
            detail="Could not determine tenant_id from token or query parameter.",
        )

    # Check connection limit before setting up the stream
    if len(_active_connections) >= settings.sse_max_connections:
        raise HTTPException(
            status_code=503,
            detail=f"SSE service at capacity (max {settings.sse_max_connections} connections)",
        )

    return StreamingResponse(
        alarm_event_generator(request, db, resolved_tenant_id, user_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )
