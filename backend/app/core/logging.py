"""
Structured JSON Logging Module.

Provides a production-ready logger that outputs JSON formatted logs
with correlation IDs, timestamps, and log levels.
"""

import logging
import json
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from contextvars import ContextVar

# Context vars to store correlation ID and tenant ID for the current request context
correlation_id_ctx: ContextVar[Optional[str]] = ContextVar("correlation_id", default=None)
tenant_id_ctx: ContextVar[Optional[str]] = ContextVar("tenant_id", default=None)


class JSONFormatter(logging.Formatter):
    """
    Formatter that dumps records as JSON.
    """
    
    def format(self, record: logging.LogRecord) -> str:
        log_data: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "module": record.module,
            "func": record.funcName,
            "line": record.lineno,
            "service": "pedkai-backend",
        }
        
        # Inject correlation ID if available in context
        cid = correlation_id_ctx.get()
        if cid:
            log_data["correlation_id"] = cid

        # Inject event ID if available in context
        from backend.app.middleware.trace import event_id_ctx
        eid = event_id_ctx.get()
        if eid:
            log_data["event_id"] = eid

        # Inject tenant ID if available in context
        tid = tenant_id_ctx.get()
        if tid:
            log_data["tenant_id"] = tid

        # Inject Trace ID from OpenTelemetry if available
        try:
            from opentelemetry import trace
            current_span = trace.get_current_span()
            if current_span and current_span.get_span_context().is_valid:
                log_data["trace_id"] = format(current_span.get_span_context().trace_id, '032x')
                log_data["span_id"] = format(current_span.get_span_context().span_id, '016x')
        except (ImportError, Exception):
            pass
            
        # Add extra fields if passed
        if hasattr(record, "extra_data"):
            log_data.update(record.extra_data)
            
        # Special handling for PII breadcrumbs
        if hasattr(record, "pii_breadcrumb"):
            log_data["pii_scoured"] = True
            log_data["breadcrumb_id"] = getattr(record, "pii_breadcrumb")
            
        # Handle exceptions
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
            
        return json.dumps(log_data)


def setup_logging(level: str = "INFO"):
    """
    Configures the root logger to use JSON formatting.
    """
    logger = logging.getLogger()
    logger.setLevel(level)
    
    # Clear existing handlers
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    logger.addHandler(handler)
    
    # Silence noisy libraries
    logging.getLogger("uvicorn.access").disabled = True # We will handle access logs manually if needed
    logging.getLogger("httpx").setLevel("WARNING")


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
