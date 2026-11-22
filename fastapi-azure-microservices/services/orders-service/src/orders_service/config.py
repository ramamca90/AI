from functools import lru_cache

from orderflow_common.config import ServiceSettings


class OrdersSettings(ServiceSettings):
    service_name: str = "orders-service"
    database_url: str = "postgresql+asyncpg://orderflow:orderflow@localhost:5432/orders"
    outbox_relay_enabled: bool = True
    outbox_poll_interval_seconds: float = 1.0
    outbox_batch_size: int = 50


@lru_cache
def get_settings() -> OrdersSettings:
    return OrdersSettings()
