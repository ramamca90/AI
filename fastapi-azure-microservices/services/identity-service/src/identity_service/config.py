from functools import lru_cache

from orderflow_common.config import ServiceSettings


class IdentitySettings(ServiceSettings):
    service_name: str = "identity-service"
    database_url: str = "postgresql+asyncpg://orderflow:orderflow@localhost:5432/identity"


@lru_cache
def get_settings() -> IdentitySettings:
    return IdentitySettings()
