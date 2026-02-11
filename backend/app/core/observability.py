"""
OpenTelemetry Observability Module.
Provides distributed tracing for Pedkai services.
"""
import logging
from typing import Optional

try:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    OPENTELEMETRY_AVAILABLE = True
except ImportError:
    OPENTELEMETRY_AVAILABLE = False

logger = logging.getLogger(__name__)

def setup_tracing(app=None):
    """Initializes OpenTelemetry tracing."""
    if not OPENTELEMETRY_AVAILABLE:
        logger.warning("OpenTelemetry SDK not installed. Tracing is disabled.")
        return

    # Initialize spans to console for now (standard production uses Jaeger/OTLP)
    provider = TracerProvider()
    processor = BatchSpanProcessor(ConsoleSpanExporter())
    provider.add_span_processor(processor)
    trace.set_tracer_provider(provider)

    if app:
        FastAPIInstrumentor.instrument_app(app)
        logger.info("OpenTelemetry FastAPI instrumentation enabled.")

def get_tracer(name: str):
    """Returns a tracer instance."""
    if OPENTELEMETRY_AVAILABLE:
        return trace.get_tracer(name)
    return None
