"""
Structured JSON Logging Module.

Provides a production-ready logger that outputs JSON formatted logs
with correlation IDs, timestamps, and log levels.
"""

import logging
import json
import sys
from datetime import datetime
from typing import Any, Dict, Optional
from contextvars import ContextVar

# Context var to store correlation ID for the current request context
correlation_id_ctx: ContextVar[Optional[str]] = ContextVar("correlation_id", default=None)


class JSONFormatter(logging.Formatter):
    """
    Formatter that dumps records as JSON.
    """
    
    def format(self, record: logging.LogRecord) -> str:
        log_data: Dict[str, Any] = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
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
            
        # Add extra fields if passed
        if hasattr(record, "extra_data"):
            log_data.update(record.extra_data)
            
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
