"""
Pedkai - AI-Native Telco Operating System

FastAPI application entry point.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
import uuid
import time

from backend.app.core.config import get_settings
from backend.app.core.logging import setup_logging, get_logger, correlation_id_ctx
from backend.app.api import decisions, health, tmf642, tmf628, auth, capacity, cx_router
from backend.app.core.security import oauth2_scheme
from backend.app.middleware.trace import TracingMiddleware
from fastapi import Depends

settings = get_settings()

# Initialize logging
setup_logging(level=settings.log_level)
logger = get_logger(__name__)


# TracingMiddleware (imported above) handles correlation IDs and request logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    # Startup
    logger.info(f"🚀 Starting {settings.app_name} v{settings.app_version}")
    
    # Initialize event bus (P1.6)
    from backend.app.events.bus import initialize_event_bus
    initialize_event_bus(maxsize=10000)
    
    # Start background event consumer (P1.7)
    from backend.app.workers.consumer import start_event_consumer
    consumer_task = await start_event_consumer()
    
    # Start autonomous action executor (P5.3)
    from backend.app.services.autonomous_action_executor import AutonomousActionExecutor
    executor = AutonomousActionExecutor(async_session_maker)
    await executor.start()

    # Start sleeping cell detector scheduler (P2.4)
    sleeping_cell_task = None
    if settings.sleeping_cell_enabled:
        from backend.app.services.sleeping_cell_detector import SleepingCellDetector
        from backend.app.workers.scheduled import start_scheduler
        detector = SleepingCellDetector()

        async def _scan_sleeping_cells():
            """Run sleeping cell scan for the default tenant."""
            try:
                await detector.scan(settings.default_tenant_id)
            except Exception as e:
                logger.error(f"Sleeping cell scan error: {e}", exc_info=True)

        sleeping_cell_task = start_scheduler(
            settings.sleeping_cell_scan_interval_seconds,
            _scan_sleeping_cells,
        )
        logger.info(
            f"Sleeping cell scheduler started "
            f"(interval={settings.sleeping_cell_scan_interval_seconds}s, "
            f"tenant={settings.default_tenant_id})"
        )
    
    yield
    # Shutdown
    logger.info(f"👋 Shutting down {settings.app_name}")
    
    # Cancel sleeping cell scheduler
    if sleeping_cell_task and not sleeping_cell_task.done():
        sleeping_cell_task.cancel()
        try:
            await sleeping_cell_task
        except Exception:
            pass

    # Cancel consumer task
    if not consumer_task.done():
        consumer_task.cancel()
        try:
            await consumer_task
        except Exception:
            pass
    
    # Stop autonomous executor
    try:
        await executor.stop()
    except Exception:
        pass


from backend.app.core.observability import setup_tracing

app = FastAPI(
    title=settings.app_name,
    description="Decision intelligence and automation for large-scale telcos",
    version=settings.app_version,
    lifespan=lifespan,
)

# Initialize Tracing
setup_tracing(app)

# Add Middleware
app.add_middleware(TracingMiddleware)

# CORS middleware for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Correlation-ID"],
)

# Include routers
app.include_router(health.router, tags=["Health"])
app.include_router(
    auth.router,
    prefix=f"{settings.api_prefix}/auth",
    tags=["Authentication"]
)
app.include_router(
    decisions.router, 
    prefix=f"{settings.api_prefix}/decisions",
    tags=["Decisions"]
)

# TMF642 Alarm Management (Phase 3 - Revised with Security GAP 3)
app.include_router(
    tmf642.router,
    prefix="/tmf-api/alarmManagement/v4",
    tags=["TMF642 Alarm Management"],
    dependencies=[Depends(oauth2_scheme)] # Enforce auth on all standard TMF endpoints
)

app.include_router(
    tmf628.router,
    prefix="/tmf-api/performanceManagement/v4",
    tags=["TMF628 Performance Management"],
    dependencies=[Depends(oauth2_scheme)]
)

# AI-Driven Capacity Planning (Wedge 2)
app.include_router(
    capacity.router,
    prefix=f"{settings.api_prefix}/capacity",
    tags=["Capacity Planning"],
)

# Customer Experience Intelligence (Wedge 3)
app.include_router(
    cx_router.router,
    prefix=f"{settings.api_prefix}/cx",
    tags=["Customer Experience"],
    dependencies=[Depends(oauth2_scheme)]
)

# Topology API (WS1)
from backend.app.api import topology
app.include_router(
    topology.router,
    prefix=f"{settings.api_prefix}/topology",
    tags=["Topology & Impact Analysis"],
    dependencies=[Depends(oauth2_scheme)]
)

# Incident Lifecycle API (WS2)
from backend.app.api import incidents
app.include_router(
    incidents.router,
    prefix=f"{settings.api_prefix}/incidents",
    tags=["Incident Lifecycle"],
    dependencies=[Depends(oauth2_scheme)]
)

# Service Impact API (WS4)
from backend.app.api import service_impact
app.include_router(
    service_impact.router,
    prefix=f"{settings.api_prefix}/service-impact",
    tags=["Service Impact & Alarm Correlation"],
    dependencies=[Depends(oauth2_scheme)]
)

# Autonomous Shield API (WS5)
from backend.app.api import autonomous
app.include_router(
    autonomous.router,
    prefix=f"{settings.api_prefix}/autonomous",
    tags=["Autonomous Shield"],
    dependencies=[Depends(oauth2_scheme)]
)

# Policies API (P5.1)
from backend.app.api import policies
app.include_router(
    policies.router,
    prefix=f"{settings.api_prefix}/policies",
    tags=["Policies"],
    dependencies=[Depends(oauth2_scheme)]
)

# Real-time SSE push (Task 4.1 — replaces 10s polling)
from backend.app.api import sse
app.include_router(sse.router, prefix=f"{settings.api_prefix}", tags=["Real-time SSE"])

# Adapters (Netconf/YANG PoC) — P5.4
from backend.app.api import adapters
app.include_router(
    adapters.router,
    prefix=f"{settings.api_prefix}/adapters",
    tags=["Adapters"],
    dependencies=[Depends(oauth2_scheme)]
)

# Operator feedback API (P2.8)
from backend.app.api import operator_feedback
app.include_router(operator_feedback.router, prefix=f"{settings.api_prefix}", tags=["Operator Feedback"], dependencies=[Depends(oauth2_scheme)])

# Alarm Ingestion Webhook (P1.6)
from backend.app.api import alarm_ingestion
app.include_router(
    alarm_ingestion.router,
    tags=["Alarm Ingestion"],
)


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "description": "AI-Native Telco Operating System",
        "docs": "/docs",
    }
