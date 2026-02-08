"""Health check endpoints."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health_check():
    """Basic health check endpoint."""
    return {"status": "healthy"}


@router.get("/ready")
async def readiness_check():
    """Readiness check - verify dependencies are available."""
    # TODO: Check database, Kafka, etc.
    return {
        "status": "ready",
        "checks": {
            "database": "ok",  # TODO: actual check
            "kafka": "ok",     # TODO: actual check
        }
    }
