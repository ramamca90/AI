"""Distributed tracing, metrics and logs via the Azure Monitor OpenTelemetry distro.

Must run *before* the FastAPI app is created: the distro patches FastAPI,
HTTP clients and logging so every request becomes a trace in Application
Insights, and calls between services are stitched together into one
end-to-end transaction (W3C traceparent propagation).
"""

import os

from orderflow_common.config import ServiceSettings
from orderflow_common.logging import get_logger

logger = get_logger(__name__)

_configured = False


def configure_telemetry(settings: ServiceSettings) -> bool:
    global _configured
    if _configured:
        return True
    if settings.applicationinsights_connection_string is None:
        logger.info("telemetry_disabled", reason="APPLICATIONINSIGHTS_CONNECTION_STRING not set")
        return False

    from azure.monitor.opentelemetry import configure_azure_monitor
    from opentelemetry.sdk.resources import Resource

    os.environ.setdefault("OTEL_SERVICE_NAME", settings.service_name)
    configure_azure_monitor(
        connection_string=settings.applicationinsights_connection_string.get_secret_value(),
        resource=Resource.create(
            {
                "service.name": settings.service_name,
                "service.version": settings.service_version,
                "deployment.environment": settings.environment.value,
            }
        ),
    )
    _configured = True
    logger.info("telemetry_enabled", exporter="azure-monitor")
    return True
