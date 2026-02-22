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
from fastapi import Depends

settings = get_settings()

# Initialize logging
setup_logging(level=settings.log_level)
logger = get_logger(__name__)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """
    Middleware to generate correlation IDs and log requests.
    """
    async def dispatch(self, request: Request, call_next):
        correlation_id = request.headers.get("X-Correlation-ID") or str(uuid.uuid4())
        correlation_id_ctx.set(correlation_id)
        
        start_time = time.time()
        response = await call_next(request)
        process_time = time.time() - start_time
        
        # Log the request completion
        logger.info(
            f"{request.method} {request.url.path} - {response.status_code}",
            extra={
                "extra_data": {
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": round(process_time * 1000, 2),
                    "user_agent": request.headers.get("user-agent"),
                }
            }
        )
        
        response.headers["X-Correlation-ID"] = correlation_id
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    # Startup
    logger.info(f"🚀 Starting {settings.app_name} v{settings.app_version}")
    yield
    # Shutdown
    logger.info(f"👋 Shutting down {settings.app_name}")


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
app.add_middleware(RequestContextMiddleware)

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

# Real-time SSE push (Task 4.1 — replaces 10s polling)
from backend.app.api import sse
app.include_router(sse.router, prefix=f"{settings.api_prefix}", tags=["Real-time SSE"])


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "description": "AI-Native Telco Operating System",
        "docs": "/docs",
    }
