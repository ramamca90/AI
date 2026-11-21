"""Runtime configuration.

Values are resolved in this order (highest priority first):
CLI flags -> environment variables (``SCRAPER_*``) -> ``.env`` file -> defaults below.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BrowserName = Literal["chromium", "firefox", "webkit"]


class ScraperSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SCRAPER_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Browser
    browser: BrowserName = "chromium"
    headless: bool = True
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0 Safari/537.36 webscraper/1.0"
    )
    navigation_timeout_ms: int = Field(default=30_000, ge=1_000)
    block_resources: bool = Field(
        default=True, description="Abort image/font/media requests to save bandwidth."
    )

    # Throughput & resilience
    concurrency: int = Field(default=5, ge=1, le=32, description="Parallel pages (tabs).")
    max_retries: int = Field(default=3, ge=0, le=10)
    retry_base_delay_s: float = Field(default=1.0, ge=0)
    retry_max_delay_s: float = Field(default=20.0, ge=0)
    request_delay_s: float = Field(
        default=0.0, ge=0, description="Politeness delay after each page load, per worker."
    )

    # Compliance
    respect_robots_txt: bool = True

    # Logging
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_json: bool = False
