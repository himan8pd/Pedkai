"""Health check endpoints."""

from fastapi import APIRouter

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
        }
    }
    
    # Check Primary Graph DB
    try:
        from backend.app.core.database import engine
        from sqlalchemy import text
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        health_status["checks"]["database"] = "ok"
    except Exception as e:
        health_status["checks"]["database"] = f"failed: {str(e)}"
        health_status["status"] = "not_ready"

    # Check Metrics DB
    try:
        from backend.app.core.database import metrics_engine
        async with metrics_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
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
            media_type="application/json"
        )
        
    return health_status
