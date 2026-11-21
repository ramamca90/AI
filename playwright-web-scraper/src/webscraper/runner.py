"""Orchestrates one scrape: compliance check -> browser -> scraper -> storage -> summary."""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from playwright.async_api import BrowserContext
from pydantic import BaseModel

from webscraper.browser import browser_context
from webscraper.config import ScraperSettings
from webscraper.exceptions import RobotsDisallowedError
from webscraper.robots import is_allowed
from webscraper.scrapers.base import BaseScraper
from webscraper.storage import OutputFormat, open_writer

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RunSummary:
    scraper: str
    output: Path
    items_written: int
    items_failed: int
    pages_visited: int
    duration_s: float

    @property
    def ok(self) -> bool:
        return self.items_failed == 0


async def run_scraper(
    scraper: BaseScraper[BaseModel],
    settings: ScraperSettings,
    output: Path,
    fmt: OutputFormat,
    *,
    setup_context: Callable[[BrowserContext], Awaitable[None]] | None = None,
) -> RunSummary:
    """Run ``scraper`` end to end.

    ``setup_context`` is an optional hook run on the fresh browser context - e.g. to load
    auth cookies, start tracing, or (in tests) install a mock network.
    """
    if settings.respect_robots_txt and not await is_allowed(scraper.start_url, settings.user_agent):
        raise RobotsDisallowedError(f"robots.txt disallows {scraper.start_url}")

    started = time.perf_counter()
    logger.info("Starting '%s' scraper at %s", scraper.name, scraper.start_url)
    async with browser_context(settings) as context:
        if setup_context is not None:
            await setup_context(context)
        with open_writer(output, fmt) as writer:
            async for record in scraper.scrape(context):
                writer.write(record)

    summary = RunSummary(
        scraper=scraper.name,
        output=output,
        items_written=writer.count,
        items_failed=scraper.stats.items_failed,
        pages_visited=scraper.stats.pages_visited,
        duration_s=round(time.perf_counter() - started, 2),
    )
    logger.info(
        "Done: %d written, %d failed, %d listing pages in %.2fs",
        summary.items_written,
        summary.items_failed,
        summary.pages_visited,
        summary.duration_s,
        extra={"summary": summary.__dict__ | {"output": str(output)}},
    )
    if scraper.stats.failed_urls:
        logger.warning("Failed URLs: %s", ", ".join(scraper.stats.failed_urls))
    return summary
