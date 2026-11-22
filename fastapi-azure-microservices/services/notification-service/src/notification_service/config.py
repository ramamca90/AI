from functools import lru_cache

from orderflow_common.config import ServiceSettings


class NotificationSettings(ServiceSettings):
    service_name: str = "notification-service"
    database_url: str = "postgresql+asyncpg://orderflow:orderflow@localhost:5432/notifications"
    event_subscription: str | None = "notification-service"
    consumer_enabled: bool = True


@lru_cache
def get_settings() -> NotificationSettings:
    return NotificationSettings()
