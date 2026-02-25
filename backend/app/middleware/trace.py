import time
import uuid
import logging
from typing import Optional
from contextvars import ContextVar

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from backend.app.core.logging import correlation_id_ctx, tenant_id_ctx

# Additional context var for request-specific event ID
event_id_ctx: ContextVar[Optional[str]] = ContextVar("event_id", default=None)

logger = logging.getLogger(__name__)

class TracingMiddleware(BaseHTTPMiddleware):
    """
    Middleware to manage Trace ID (Correlation ID) and Event ID for every request.
    Ensures observability across service boundaries.
    """
    async def dispatch(self, request: Request, call_next):
        # 1. Extract or generate Correlation ID (Trace ID)
        correlation_id = request.headers.get("X-Correlation-ID") or \
                         request.headers.get("X-Trace-ID") or \
                         str(uuid.uuid4())
        
        # 2. Generate unique Event ID for this specific execution
        event_id = str(uuid.uuid4())
        
        # 3. Set context variables for the logger
        correlation_id_ctx.set(correlation_id)
        event_id_ctx.set(event_id)
        
        # 4. Optional: extract tenant_id from header as a hint before full auth
        tenant_id = request.headers.get("X-Tenant-ID")
        if tenant_id:
            tenant_id_ctx.set(tenant_id)
        
        start_time = time.time()
        
        try:
            response = await call_next(request)
            process_time = time.time() - start_time
            
            # Log successful request with metadata
            logger.info(
                f"{request.method} {request.url.path} completed",
                extra={
                    "extra_data": {
                        "method": request.method,
                        "path": request.url.path,
                        "status_code": response.status_code,
                        "duration_ms": round(process_time * 1000, 2),
                        "event_id": event_id,
                        "client_ip": request.client.host if request.client else None
                    }
                }
            )
            
            # Add IDs back to response headers for client-side tracing
            response.headers["X-Correlation-ID"] = correlation_id
            response.headers["X-Event-ID"] = event_id
            response.headers["X-Trace-ID"] = correlation_id # Alias for compliance
            
            return response
            
        except Exception as e:
            process_time = time.time() - start_time
            logger.error(
                f"Request failed: {request.method} {request.url.path}",
                extra={
                    "extra_data": {
                        "method": request.method,
                        "path": request.url.path,
                        "status_code": 500,
                        "duration_ms": round(process_time * 1000, 2),
                        "event_id": event_id,
                        "error": str(e)
                    }
                },
                exc_info=True
            )
            # Re-raise to let FastAPI handle the error response or another middleware catch it
            raise e
