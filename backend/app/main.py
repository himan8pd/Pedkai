"""
Pedkai - AI-Native Telco Operating System

Adding a comment to commit the file again.

FastAPI application entry point.
"""

import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

# Load .env so os.getenv() works for modules that read env vars directly
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from backend.app.api import auth, capacity, cx_router, decisions, health, tmf628, tmf642, users
from backend.app.core.config import get_settings
from backend.app.core.database import async_session_maker
from backend.app.core.logging import correlation_id_ctx, get_logger, setup_logging
from backend.app.core.security import oauth2_scheme
from backend.app.middleware.trace import TracingMiddleware

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

    # Seed default users and tenants (idempotent)
    try:
        async with async_session_maker() as session:
            from backend.app.services import auth_service
            await auth_service.seed_default_users(session)
            logger.info("✓ Default users and tenants seeded")
    except Exception as e:
        logger.error(f"Failed to seed default users: {e}")

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
            """Run sleeping cell scan. Uses data-driven reference time for historic mode."""
            try:
                # Determine reference time from actual data so that historic
                # datasets (e.g. timestamped Jan 2024) produce meaningful
                # results instead of comparing against datetime.now().
                from sqlalchemy import text as sa_text

                from backend.app.core.database import metrics_session_maker

                ref_time = None
                try:
                    async with metrics_session_maker() as msession:
                        result = await msession.execute(
                            sa_text(
                                "SELECT MAX(timestamp) FROM kpi_metrics WHERE tenant_id = :tid"
                            ),
                            {"tid": settings.default_tenant_id},
                        )
                        max_ts = result.scalar()
                    ref_time = max_ts if max_ts else None
                except Exception as e:
                    logger.warning(f"Could not determine KPI reference time: {e}")

                await detector.scan(settings.default_tenant_id, reference_time=ref_time)
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

    # Start telemetry Kafka consumers (if enabled)
    telemetry_consumer_task = None
    fragment_bridge_task = None
    if settings.telemetry_consumers_enabled:
        try:
            from backend.app.telemetry.kafka_consumers import start_telemetry_consumer

            telemetry_consumer_task, fragment_bridge_task = await start_telemetry_consumer()
            logger.info("Telemetry Kafka consumers started")
            if fragment_bridge_task:
                logger.info("Abeyance Memory fragment bridge started")
        except Exception as e:
            logger.error(f"Failed to start telemetry consumers: {e}", exc_info=True)

    yield
    # Shutdown
    logger.info(f"👋 Shutting down {settings.app_name}")

    # Cancel telemetry consumer
    if telemetry_consumer_task and not telemetry_consumer_task.done():
        telemetry_consumer_task.cancel()
        try:
            await telemetry_consumer_task
        except Exception:
            pass

    # Cancel fragment bridge
    if fragment_bridge_task and not fragment_bridge_task.done():
        fragment_bridge_task.cancel()
        try:
            await fragment_bridge_task
        except Exception:
            pass

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
    description=(
        "Decision intelligence and automation for large-scale telcos.\n\n"
        "**Authentication:** Click the **Authorize** button (🔒) above, enter "
        "username & password (e.g. `admin`/`admin` or `operator`/`operator`), "
        "leave Client credentials blank, then click **Authorize**."
    ),
    version=settings.app_version,
    lifespan=lifespan,
    swagger_ui_parameters={
        "persistAuthorization": True,
        "tryItOutEnabled": True,
    },
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
    auth.router, prefix=f"{settings.api_prefix}/auth", tags=["Authentication"]
)
app.include_router(
    users.router, prefix=f"{settings.api_prefix}/users", tags=["User Management"]
)
app.include_router(
    decisions.router, prefix=f"{settings.api_prefix}/decisions", tags=["Decisions"]
)

# TMF642 Alarm Management (Phase 3 - Revised with Security GAP 3)
app.include_router(
    tmf642.router,
    prefix="/tmf-api/alarmManagement/v4",
    tags=["TMF642 Alarm Management"],
    dependencies=[Depends(oauth2_scheme)],  # Enforce auth on all standard TMF endpoints
)

app.include_router(
    tmf628.router,
    prefix="/tmf-api/performanceManagement/v4",
    tags=["TMF628 Performance Management"],
    dependencies=[Depends(oauth2_scheme)],
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
    dependencies=[Depends(oauth2_scheme)],
)

# Topology API (WS1)
from backend.app.api import topology

app.include_router(
    topology.router,
    prefix=f"{settings.api_prefix}/topology",
    tags=["Topology & Impact Analysis"],
    dependencies=[Depends(oauth2_scheme)],
)

# Incident Lifecycle API (WS2)
from backend.app.api import incidents

app.include_router(
    incidents.router,
    prefix=f"{settings.api_prefix}/incidents",
    tags=["Incident Lifecycle"],
    dependencies=[Depends(oauth2_scheme)],
)

# Service Impact API (WS4)
from backend.app.api import service_impact

app.include_router(
    service_impact.router,
    prefix=f"{settings.api_prefix}/service-impact",
    tags=["Service Impact & Alarm Correlation"],
    dependencies=[Depends(oauth2_scheme)],
)

# Autonomous Shield API (WS5)
from backend.app.api import autonomous

app.include_router(
    autonomous.router,
    prefix=f"{settings.api_prefix}/autonomous",
    tags=["Autonomous Shield"],
    dependencies=[Depends(oauth2_scheme)],
)

# Policies API (P5.1)
from backend.app.api import policies

app.include_router(
    policies.router,
    prefix=f"{settings.api_prefix}/policies",
    tags=["Policies"],
    dependencies=[Depends(oauth2_scheme)],
)

# Real-time SSE push (Task 4.1 — replaces 10s polling)
from backend.app.api import sse

app.include_router(sse.router, prefix=f"{settings.api_prefix}", tags=["Real-time SSE"])

# Ingestion API
from backend.app.api import ingestion

app.include_router(
    ingestion.router,
    prefix=f"{settings.api_prefix}/ingestion",
    tags=["Ingestion"],
)

# Reports API
from backend.app.api import reports

app.include_router(
    reports.router,
    prefix=f"{settings.api_prefix}/reports",
    tags=["Reports"],
    dependencies=[Depends(oauth2_scheme)],
)

# Adapters (Netconf/YANG PoC) — P5.4
from backend.app.api import adapters

app.include_router(
    adapters.router,
    prefix=f"{settings.api_prefix}/adapters",
    tags=["Adapters"],
    dependencies=[Depends(oauth2_scheme)],
)

# Operator feedback API (P2.8)
from backend.app.api import operator_feedback

app.include_router(
    operator_feedback.router,
    prefix=f"{settings.api_prefix}",
    tags=["Operator Feedback"],
    dependencies=[Depends(oauth2_scheme)],
)

# Alarm Ingestion Webhook (P1.6)
from backend.app.api import alarm_ingestion

app.include_router(
    alarm_ingestion.router,
    tags=["Alarm Ingestion"],
)


# Abeyance Memory API
from backend.app.api import abeyance as abeyance_router

app.include_router(
    abeyance_router.router,
    prefix=f"{settings.api_prefix}/abeyance",
    tags=["Abeyance Memory"],
    dependencies=[Depends(oauth2_scheme)],
)

# Shadow Topology API
from backend.app.api import shadow_topology

app.include_router(
    shadow_topology.router,
    prefix=f"{settings.api_prefix}/shadow-topology",
    tags=["Shadow Topology"],
    dependencies=[Depends(oauth2_scheme)],
)

# Sleeping Cells API (P2.4)
from backend.app.api import sleeping_cells

app.include_router(
    sleeping_cells.router,
    prefix=f"{settings.api_prefix}/sleeping-cells",
    tags=["Sleeping Cells"],
    dependencies=[Depends(oauth2_scheme)],
)

# Value Attribution API
from backend.app.api import value

app.include_router(
    value.router,
    prefix=f"{settings.api_prefix}/value",
    tags=["Value Attribution"],
    dependencies=[Depends(oauth2_scheme)],
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
