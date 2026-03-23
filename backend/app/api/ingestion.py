import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator, Optional

from fastapi import APIRouter, HTTPException, Request, Depends, Security
from fastapi.responses import StreamingResponse
from jose import JWTError, jwt
from pydantic import BaseModel

from backend.app.core.security import oauth2_scheme, get_current_user, User
from backend.app.core.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter()

# Global state for ingestion
# (in a real prod environment this would be in Redis/Celery)
_ingestion_running = False
_ingestion_progress = 0
_ingestion_logs: list[str] = []
_ingestion_subscribers: set[asyncio.Queue] = set()
_ingestion_lock = asyncio.Lock()

class IngestionParams(BaseModel):
    dry_run: bool = False
    skip_kpi_sample: bool = False
    step: int | None = None

async def _publish(event: str, data: dict):
    payload = {"event": event, "data": data, "timestamp": datetime.now(timezone.utc).isoformat()}
    for q in _ingestion_subscribers:
        await q.put(payload)

async def run_ingestion_subprocess(params: IngestionParams, tenant_id: str):
    global _ingestion_running, _ingestion_progress
    _ingestion_progress = 0
    _ingestion_logs.clear()

    import os
    data_store_root = os.environ.get("PEDKAI_DATA_STORE_ROOT", "")
    output_dir = str(Path(data_store_root) / tenant_id / "output") if data_store_root else None

    cmd = [sys.executable, "-m", "backend.app.scripts.load_tenant", "--tenant-id", tenant_id]
    if output_dir:
        cmd.extend(["--output-dir", output_dir])
    if params.dry_run:
        cmd.append("--dry-run")
    # skip_kpi_sample: kpi-sample-hours defaults to 0 (skip) in load_tenant, so no flag needed.
    # Only pass --kpi-sample-hours if explicitly loading KPI data (not exposed via UI yet).
    if params.step is not None:
        cmd.extend(["--step", str(params.step)])

    await _publish("ingestion_started", {"cmd": cmd})

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(Path(__file__).resolve().parents[3]),  # repo root
            env=env
        )

        while True:
            if process.stdout is None:
                break
            line = await process.stdout.readline()
            if not line:
                break
            line_str = line.decode().rstrip()
            _ingestion_logs.append(line_str)

            # Naive progress estimation based on "Step X" log lines
            if "Step 0" in line_str: _ingestion_progress = 5
            elif "Step 1" in line_str: _ingestion_progress = 15
            elif "Step 2" in line_str: _ingestion_progress = 30
            elif "Step 3" in line_str: _ingestion_progress = 45
            elif "Step 4" in line_str: _ingestion_progress = 60
            elif "Step 12" in line_str: _ingestion_progress = 85
            elif "Loaded" in line_str and "entities" in line_str:
                _ingestion_progress = min(95, _ingestion_progress + 2)

            await _publish("ingestion_log", {"line": line_str, "progress": _ingestion_progress})

        await process.wait()
        _ingestion_progress = 100
        await _publish("ingestion_completed", {"code": process.returncode, "progress": 100})
    except Exception as e:
        logger.error(f"Ingestion subprocess error: {e}")
        await _publish("ingestion_error", {"error": str(e), "progress": _ingestion_progress})
    finally:
        _ingestion_running = False
        # One last update to ensure UI knows we're done
        await asyncio.sleep(0.5)
        await _publish("ingestion_completed", {"status": "stopped", "progress": _ingestion_progress})

@router.post("/start")
async def start_ingestion(
    params: IngestionParams,
    current_user: User = Security(get_current_user, scopes=["admin:all"]),
):
    global _ingestion_running

    tenant_id = current_user.tenant_id
    if not tenant_id:
        raise HTTPException(status_code=400, detail="No tenant_id in token")

    async with _ingestion_lock:
        if _ingestion_running:
            raise HTTPException(status_code=400, detail="Ingestion is already running")
        _ingestion_running = True

    asyncio.create_task(run_ingestion_subprocess(params, tenant_id))
    return {"message": "Ingestion started", "status": "running"}

@router.get("/status", dependencies=[Depends(oauth2_scheme)])
async def get_ingestion_status():
    return {
        "running": _ingestion_running,
        "progress": _ingestion_progress,
        "logs_count": len(_ingestion_logs)
    }

@router.get("/stream")
async def stream_ingestion(request: Request, token: Optional[str] = None):
    """SSE endpoint for ingestion progress. Requires ?token=<jwt>."""
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")
    settings = get_settings()
    try:
        jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    async def event_generator() -> AsyncGenerator[str, None]:
        q = asyncio.Queue()
        _ingestion_subscribers.add(q)
        try:
            # Send initial state
            yield f"data: {json.dumps({'event': 'init', 'data': {'running': _ingestion_running, 'progress': _ingestion_progress}, 'timestamp': datetime.now(timezone.utc).isoformat()})}\n\n"

            # Replay recent logs for quick catch up
            for log_line in _ingestion_logs[-50:]:
                yield f"data: {json.dumps({'event': 'ingestion_log', 'data': {'line': log_line, 'progress': _ingestion_progress}})}\n\n"

            while True:
                if await request.is_disconnected():
                    break

                try:
                    payload = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield f"data: {json.dumps(payload)}\n\n"
                except asyncio.TimeoutError:
                    # Heartbeat
                    yield ": heartbeat\n\n"
        finally:
            _ingestion_subscribers.discard(q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )
