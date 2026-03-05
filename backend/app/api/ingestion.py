import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.app.core.security import oauth2_scheme

logger = logging.getLogger(__name__)
router = APIRouter()

# Global state for ingestion 
# (in a real prod environment this would be in Redis/Celery)
_ingestion_running = False
_ingestion_progress = 0
_ingestion_logs: list[str] = []
_ingestion_subscribers: set[asyncio.Queue] = set()

class IngestionParams(BaseModel):
    dry_run: bool = False
    skip_kpi_sample: bool = False
    step: int | None = None

async def _publish(event: str, data: dict):
    payload = {"event": event, "data": data, "timestamp": datetime.now(timezone.utc).isoformat()}
    for q in _ingestion_subscribers:
        await q.put(payload)

async def run_ingestion_subprocess(params: IngestionParams):
    global _ingestion_running, _ingestion_progress
    _ingestion_running = True
    _ingestion_progress = 0
    _ingestion_logs.clear()
    
    cmd = [sys.executable, "-m", "backend.app.scripts.load_telco2_tenant"]
    if params.dry_run:
        cmd.append("--dry-run")
    if params.skip_kpi_sample:
        cmd.append("--skip-kpi-sample")
    if params.step is not None:
        cmd.extend(["--step", str(params.step)])
        
    await _publish("ingestion_started", {"cmd": cmd})
    
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd="/Users/himanshu/Projects/Pedkai"
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

@router.post("/start", dependencies=[Depends(oauth2_scheme)])
async def start_ingestion(params: IngestionParams):
    global _ingestion_running
    if _ingestion_running:
        raise HTTPException(status_code=400, detail="Ingestion is already running")
    
    asyncio.create_task(run_ingestion_subprocess(params))
    return {"message": "Ingestion started", "status": "running"}

@router.get("/status", dependencies=[Depends(oauth2_scheme)])
async def get_ingestion_status():
    return {
        "running": _ingestion_running,
        "progress": _ingestion_progress,
        "logs_count": len(_ingestion_logs)
    }

@router.get("/stream")
async def stream_ingestion(request: Request):
    """SSE endpoint for ingestion progress"""
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
            _ingestion_subscribers.remove(q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )
