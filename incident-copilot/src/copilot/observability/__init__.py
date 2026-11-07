"""Logging, metrics and tracing setup."""

from copilot.observability.logging import configure_logging
from copilot.observability.tracing import configure_tracing, get_tracer

__all__ = ["configure_logging", "configure_tracing", "get_tracer"]
