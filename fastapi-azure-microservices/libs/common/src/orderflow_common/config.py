"""12-factor configuration.

All settings come from environment variables (or a local `.env`). In Azure
Container Apps, secrets such as DATABASE_URL and JWT_SECRET are injected from
Key Vault references, so no secret ever lives in the image or the repo.
"""

from enum import StrEnum

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    LOCAL = "local"
    TEST = "test"
    DEV = "dev"
    STAGING = "staging"
    PROD = "prod"


class EventBusBackend(StrEnum):
    MEMORY = "memory"
    REDIS = "redis"
    AZURE_SERVICE_BUS = "azure_servicebus"


class ServiceSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- identity of the running service
    service_name: str = "orderflow-service"
    service_version: str = "0.1.0"
    environment: Environment = Environment.LOCAL

    # --- logging / telemetry
    log_level: str = "INFO"
    log_json: bool = True
    applicationinsights_connection_string: SecretStr | None = None

    # --- HTTP
    docs_enabled: bool = True
    cors_allow_origins: list[str] = []

    # --- persistence
    database_url: str = "sqlite+aiosqlite:///./local.db"
    db_pool_size: int = 10
    db_max_overflow: int = 10
    db_echo: bool = False

    # --- auth (tokens are issued by identity-service, verified everywhere)
    jwt_secret: SecretStr = SecretStr("local-dev-secret-change-me")
    jwt_algorithm: str = "HS256"
    jwt_issuer: str = "orderflow-identity"
    jwt_audience: str = "orderflow-api"
    jwt_access_token_ttl_minutes: int = 30

    # --- messaging
    event_bus_backend: EventBusBackend = EventBusBackend.MEMORY
    event_topic: str = "domain-events"
    event_subscription: str | None = None
    redis_url: str = "redis://localhost:6379/0"
    servicebus_connection_string: SecretStr | None = None
    # Preferred in Azure: managed identity, no connection string at all.
    servicebus_fully_qualified_namespace: str | None = None

    @property
    def is_deployed(self) -> bool:
        return self.environment in {Environment.DEV, Environment.STAGING, Environment.PROD}

    @model_validator(mode="after")
    def _validate_for_environment(self) -> "ServiceSettings":
        if self.is_deployed and len(self.jwt_secret.get_secret_value()) < 32:
            raise ValueError("JWT_SECRET must be at least 32 characters in deployed environments")
        if self.event_bus_backend is EventBusBackend.AZURE_SERVICE_BUS and not (
            self.servicebus_connection_string or self.servicebus_fully_qualified_namespace
        ):
            raise ValueError(
                "azure_servicebus backend needs SERVICEBUS_FULLY_QUALIFIED_NAMESPACE "
                "(managed identity) or SERVICEBUS_CONNECTION_STRING"
            )
        return self
