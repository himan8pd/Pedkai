"""
Resilience Patterns Module.

Implements Circuit Breaker and Retry logic for external dependencies.
"""

import time
from typing import Callable, Any, Optional
from functools import wraps
import asyncio

from backend.app.core.logging import get_logger

logger = get_logger(__name__)


class CircuitBreakerOpenException(Exception):
    """Raised when the circuit is open and calls are blocked."""
    pass


class CircuitBreaker:
    """
    Simple Circuit Breaker implementation.
    
    States:
    - CLOSED: Normal operation, calls function.
    - OPEN: Fails fast, raises CircuitBreakerOpenException.
    - HALF-OPEN: Allows one trial call to check if service recovered.
    """
    
    def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 30):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        
        self.failure_count = 0
        self.last_failure_time = 0
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
        
    async def call(self, func: Callable, *args, **kwargs) -> Any:
        if self.state == "OPEN":
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = "HALF-OPEN"
                logger.info("Circuit State changed to HALF-OPEN. Attempting recovery.")
            else:
                raise CircuitBreakerOpenException(f"Circuit is OPEN. Failures: {self.failure_count}")
                
        try:
            result = await func(*args, **kwargs)
            if self.state == "HALF-OPEN":
                self.state = "CLOSED"
                self.failure_count = 0
                logger.info("Circuit State changed to CLOSED. Recovery successful.")
            return result
            
        except Exception as e:
            self.failure_count += 1
            self.last_failure_time = time.time()
            logger.error(f"Circuit Breaker failure ({self.failure_count}/{self.failure_threshold}): {str(e)}")
            
            if self.failure_count >= self.failure_threshold:
                self.state = "OPEN"
                logger.warning(f"Circuit State changed to OPEN. Blocking calls for {self.recovery_timeout}s.")
            
            raise e


# Singleton breakers for key services
llm_circuit_breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=60)
