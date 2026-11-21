from __future__ import annotations

import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from playwright.async_api import BrowserContext

sys.path.insert(0, str(Path(__file__).parent))

from webscraper.browser import browser_context
from webscraper.config import ScraperSettings


@pytest.fixture
def settings() -> ScraperSettings:
    # _env_file=None: tests must not depend on a developer's local .env
    return ScraperSettings(
        _env_file=None,  # type: ignore[call-arg]
        concurrency=3,
        max_retries=2,
        retry_base_delay_s=0,
        navigation_timeout_ms=10_000,
        respect_robots_txt=False,
    )


@pytest.fixture
async def context(settings: ScraperSettings) -> AsyncIterator[BrowserContext]:
    async with browser_context(settings) as ctx:
        yield ctx
