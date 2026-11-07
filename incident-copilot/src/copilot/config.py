"""Typed application settings, loaded from the environment or a local .env file."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_provider: Literal["scripted", "anthropic"] = "scripted"
    anthropic_api_key: SecretStr | None = None
    llm_model: str = "claude-opus-5-5"
    incident_budget_usd: float = Field(default=2.00, gt=0)
    agent_max_iterations: int = Field(default=8, ge=1, le=30)

    database_url: str = "sqlite+aiosqlite:///./copilot.db"
    queue_backend: Literal["local", "sqs"] = "local"
    sqs_queue_url: str | None = None
    aws_region: str = "us-east-1"

    api_key: SecretStr = SecretStr("dev-only-change-me")
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
