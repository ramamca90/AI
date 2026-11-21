"""quotes.toscrape.com/scroll - JavaScript-rendered, infinite-scroll page.

This is the case where ``requests`` + BeautifulSoup fails: the initial HTML contains no
quotes at all. Playwright runs the page's JavaScript, and we drive the scroll the way a
user would until no new content appears.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any, ClassVar

from playwright.async_api import BrowserContext, Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from pydantic import ValidationError

from webscraper.browser import goto
from webscraper.config import ScraperSettings
from webscraper.models import Quote
from webscraper.parsing import clean_quote
from webscraper.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

QUOTE_SELECTOR = "div.quote"

_EXTRACT_JS = """els => els.map(e => ({
    text: e.querySelector('.text')?.textContent ?? '',
    author: e.querySelector('.author')?.textContent ?? '',
    tags: [...e.querySelectorAll('.tags .tag')].map(t => t.textContent.trim()),
}))"""


async def scroll_until_exhausted(
    page: Page, *, max_scrolls: int, settle_timeout_ms: int = 5_000
) -> int:
    """Scroll to the bottom repeatedly until the item count stops growing."""
    items = page.locator(QUOTE_SELECTOR)
    count = await items.count()
    for i in range(max_scrolls):
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        try:
            await page.wait_for_function(
                "([sel, n]) => document.querySelectorAll(sel).length > n",
                arg=[QUOTE_SELECTOR, count],
                timeout=settle_timeout_ms,
            )
        except PlaywrightTimeoutError:
            logger.info("No new items after scroll %d; reached the end", i + 1)
            break
        count = await items.count()
        logger.info("Scroll %d: %d items loaded", i + 1, count)
    return count


async def parse_quotes(page: Page) -> list[dict[str, Any]]:
    raw: list[dict[str, Any]] = await page.locator(QUOTE_SELECTOR).evaluate_all(_EXTRACT_JS)
    return raw


class QuotesScraper(BaseScraper[Quote]):
    name: ClassVar[str] = "quotes"
    start_url: ClassVar[str] = "https://quotes.toscrape.com/scroll"

    def __init__(
        self,
        settings: ScraperSettings,
        *,
        max_scrolls: int = 50,
        start_url: str | None = None,
    ) -> None:
        super().__init__(settings)
        self.max_scrolls = max_scrolls
        if start_url:
            self.start_url = start_url  # type: ignore[misc]

    async def scrape(self, context: BrowserContext) -> AsyncIterator[Quote]:
        page = await context.new_page()
        try:
            await self.with_retry(lambda: self._load_first_batch(page), self.start_url)
            self.stats.pages_visited += 1
            await scroll_until_exhausted(page, max_scrolls=self.max_scrolls)
            for raw in await parse_quotes(page):
                try:
                    yield Quote(
                        text=clean_quote(raw["text"]),
                        author=raw["author"],
                        tags=raw["tags"],
                    )
                except ValidationError as exc:
                    logger.error("Skipping invalid quote %r: %s", raw, exc)
                    self.stats.record_failure(self.start_url)
        finally:
            await page.close()

    async def _load_first_batch(self, page: Page) -> None:
        await goto(page, self.start_url)
        # Content is injected by JS after DOMContentLoaded - wait for it explicitly.
        await page.locator(QUOTE_SELECTOR).first.wait_for(state="attached")
