"""Minimal OpenTelemetry setup.

Spans are always created, so the code paths are the same everywhere. They go nowhere unless
OTEL_TRACES_EXPORTER=console is set, or OTEL_EXPORTER_OTLP_ENDPOINT is set and the optional
opentelemetry-exporter-otlp package is installed.
"""

from __future__ import annotations

import importlib
import os

import structlog
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SpanExporter,
)

log = structlog.get_logger(__name__)

_TRACER_NAME = "copilot"
_OTLP_EXPORTER_MODULE = "opentelemetry.exporter.otlp.proto.http.trace_exporter"


def _exporter() -> SpanExporter | None:
    if os.environ.get("OTEL_TRACES_EXPORTER") == "console":
        return ConsoleSpanExporter()
    if not os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        return None
    try:
        module = importlib.import_module(_OTLP_EXPORTER_MODULE)
    except ImportError:
        log.warning("tracing.otlp_exporter_not_installed")
        return None
    exporter: SpanExporter = module.OTLPSpanExporter()
    return exporter


def configure_tracing(service_name: str) -> None:
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    exporter = _exporter()
    if exporter is not None:
        provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)


def get_tracer() -> trace.Tracer:
    return trace.get_tracer(_TRACER_NAME)
