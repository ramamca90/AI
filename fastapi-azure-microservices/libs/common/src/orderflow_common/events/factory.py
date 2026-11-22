from orderflow_common.config import EventBusBackend, ServiceSettings
from orderflow_common.events.base import EventBus
from orderflow_common.events.memory import InMemoryEventBus


def build_event_bus(settings: ServiceSettings) -> EventBus:
    match settings.event_bus_backend:
        case EventBusBackend.MEMORY:
            return InMemoryEventBus()
        case EventBusBackend.REDIS:
            from orderflow_common.events.redis_streams import RedisStreamsEventBus

            return RedisStreamsEventBus(settings.redis_url, stream=settings.event_topic)
        case EventBusBackend.AZURE_SERVICE_BUS:
            from orderflow_common.events.azure_service_bus import AzureServiceBusEventBus

            conn = settings.servicebus_connection_string
            return AzureServiceBusEventBus(
                topic=settings.event_topic,
                connection_string=conn.get_secret_value() if conn else None,
                fully_qualified_namespace=settings.servicebus_fully_qualified_namespace,
            )
    raise ValueError(f"Unsupported event bus backend: {settings.event_bus_backend}")
