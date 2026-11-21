"""Common machinery shared by every site scraper."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import ClassVar, Generic, TypeVar

from playwright.async_api import BrowserContext
from pydantic import BaseModel

from webscraper.config import ScraperSettings
from webscraper.retry import retry_async

T = TypeVar("T", bound=BaseModel)
R = TypeVar("R")


@dataclass
class ScrapeStats:
    pages_visited: int = 0
    items_failed: int = 0
    failed_urls: list[str] = field(default_factory=list)

    def record_failure(self, url: str) -> None:
        self.items_failed += 1
        self.failed_urls.append(url)


class BaseScraper(ABC, Generic[T]):
    """A scraper turns a browser context into an async stream of validated records."""

    name: ClassVar[str]
    start_url: ClassVar[str]

    def __init__(self, settings: ScraperSettings) -> None:
        self.settings = settings
        self.stats = ScrapeStats()

    @abstractmethod
    def scrape(self, context: BrowserContext) -> AsyncIterator[T]:
        """Yield records as soon as they are available."""

    async def with_retry(self, operation: Callable[[], Awaitable[R]], description: str) -> R:
        return await retry_async(
            operation,
            max_retries=self.settings.max_retries,
            base_delay=self.settings.retry_base_delay_s,
            max_delay=self.settings.retry_max_delay_s,
            description=description,
        )

    async def polite_pause(self) -> None:
        if self.settings.request_delay_s:
            await asyncio.sleep(self.settings.request_delay_s)
