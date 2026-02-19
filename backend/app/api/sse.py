"""
Server-Sent Events (SSE) endpoint for real-time alarm and incident push.
Replaces the 10-second polling loop in the frontend.
"""
import asyncio
import json
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text

from backend.app.core.database import get_db
from backend.app.core.security import get_current_user, User

logger = logging.getLogger(__name__)
router = APIRouter()


async def alarm_event_generator(request: Request, db: AsyncSession, tenant_id: str):
    """Generate SSE events for new alarms. Polls DB every 2s (server-side, not client-side)."""
    last_seen_id = None
    while True:
        if await request.is_disconnected():
            logger.info(f"SSE client disconnected for tenant {tenant_id}")
            break
        try:
            query = text("""
                SELECT id, specific_problem, perceived_severity, alarmed_object_id, event_time
                FROM alarms
                WHERE tenant_id = :tid
                ORDER BY event_time DESC
                LIMIT 20
            """)
            result = await db.execute(query, {"tid": tenant_id})
            rows = result.fetchall()
            if rows:
                newest_id = str(rows[0][0])
                if newest_id != last_seen_id:
                    last_seen_id = newest_id
                    payload = {
                        "event": "alarms_updated",
                        "tenant_id": tenant_id,
                        "count": len(rows),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                    yield f"data: {json.dumps(payload)}\n\n"
        except Exception as e:
            logger.error(f"SSE generator error: {e}")
            yield f"data: {json.dumps({'event': 'error', 'message': str(e)})}\n\n"
        await asyncio.sleep(2)  # Server polls every 2s — client stays connected


@router.get("/stream/alarms")
async def stream_alarms(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """SSE endpoint: streams alarm update notifications to connected clients."""
    return StreamingResponse(
        alarm_event_generator(request, db, current_user.tenant_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )
