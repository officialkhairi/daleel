"""OpenTelemetry tracing, on when OTEL_EXPORTER_OTLP_ENDPOINT is set (the compose `obs` profile
points it at the collector, which forwards to Tempo and Langfuse). The browser's traceparent
header continues its trace here, so one trace spans SPA → API → model server and database."""

import logging

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from sqlalchemy.ext.asyncio import AsyncEngine

log = logging.getLogger(__name__)
tracer = trace.get_tracer("daleel")
_configured = False


def configure_tracing(endpoint: str | None, service: str) -> bool:
    """Installs the exporter once per process. Returns whether tracing is on."""
    global _configured
    if not endpoint:
        return False
    if not _configured:
        provider = TracerProvider(resource=Resource.create({"service.name": service}))
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint.rstrip('/')}/v1/traces"))
        )
        trace.set_tracer_provider(provider)
        HTTPXClientInstrumentor().instrument()
        RedisInstrumentor().instrument()
        _configured = True
        log.info("tracing to %s", endpoint)
    return True


def instrument_app(app: FastAPI) -> None:
    """Before the app starts: this adds middleware."""
    FastAPIInstrumentor.instrument_app(app, excluded_urls="healthz,readyz,metrics")


def instrument_engine(engine: AsyncEngine) -> None:
    SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)


def current_trace_id() -> str | None:
    context = trace.get_current_span().get_span_context()
    return f"{context.trace_id:032x}" if context.is_valid else None
