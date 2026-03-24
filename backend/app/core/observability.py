"""
OpenTelemetry Observability Module.
Provides distributed tracing for Pedkai services.

NOTE: ConsoleSpanExporter was removed — it flooded stdout with JSON for
every span including /health healthchecks, drowning out application logs.
When a real collector (Jaeger / OTLP) is available, add its exporter here.
"""
import logging
from typing import Optional

try:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    OPENTELEMETRY_AVAILABLE = True
except ImportError:
    OPENTELEMETRY_AVAILABLE = False

logger = logging.getLogger(__name__)

# Endpoints to exclude from tracing (healthchecks, readiness probes, etc.)
_EXCLUDED_URLS = "health,healthz,ready,readyz"


def setup_tracing(app=None):
    """Initializes OpenTelemetry tracing."""
    if not OPENTELEMETRY_AVAILABLE:
        logger.warning("OpenTelemetry SDK not installed. Tracing is disabled.")
        return

    from opentelemetry.sdk.resources import Resource

    resource = Resource.create({"service.name": "pedkai-backend"})
    provider = TracerProvider(resource=resource)
    # No exporter — spans are created for context propagation only.
    # Add BatchSpanProcessor(OTLPSpanExporter(...)) when a collector is available.
    trace.set_tracer_provider(provider)

    if app:
        FastAPIInstrumentor.instrument_app(
            app,
            excluded_urls=_EXCLUDED_URLS,
        )
        logger.info("OpenTelemetry FastAPI instrumentation enabled (console export disabled).")

def get_tracer(name: str):
    """Returns a tracer instance."""
    if OPENTELEMETRY_AVAILABLE:
        return trace.get_tracer(name)
    return None
