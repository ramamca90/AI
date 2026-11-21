"""books.toscrape.com - paginated catalogue + concurrent detail-page crawl.

Demonstrates: following pagination, fan-out over many URLs with bounded concurrency
(one tab per worker), per-item retry & failure isolation, and DOM extraction with
Playwright locators.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from functools import partial
from typing import Any, ClassVar

from playwright.async_api import BrowserContext, Locator, Page
from pydantic import ValidationError

from webscraper.browser import goto
from webscraper.config import ScraperSettings
from webscraper.exceptions import ParseError
from webscraper.models import Book
from webscraper.parsing import parse_availability, parse_price, parse_rating
from webscraper.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------- page parsers
# Kept as module-level functions so they can be tested against fixture HTML.


async def _text(locator: Locator, what: str) -> str:
    """Text of the first match, or ParseError (instead of waiting for a timeout)."""
    if await locator.count() == 0:
        raise ParseError(f"Missing element: {what}")
    return (await locator.first.text_content() or "").strip()


async def parse_listing(page: Page) -> list[str]:
    """Absolute URLs of every book on a catalogue page."""
    links: list[str] = await page.locator("article.product_pod h3 a").evaluate_all(
        "els => els.map(e => e.href)"  # .href is already resolved to an absolute URL
    )
    return links


async def parse_next_page(page: Page) -> str | None:
    nxt = page.locator("li.next > a")
    if await nxt.count() == 0:
        return None
    href: str = await nxt.first.evaluate("e => e.href")
    return href


async def parse_book(page: Page) -> Book:
    main = page.locator("div.product_main")
    if await main.count() == 0:
        raise ParseError(f"Not a product page: {page.url}")

    info: dict[str, str] = await page.locator("table.table-striped tr").evaluate_all(
        """rows => Object.fromEntries(rows.map(r => [
            r.querySelector('th')?.textContent.trim(),
            r.querySelector('td')?.textContent.trim(),
        ]))"""
    )
    in_stock, stock_count = parse_availability(await _text(main.locator("p.availability"), "stock"))
    rating_class = await main.locator("p.star-rating").first.get_attribute("class") or ""

    description_el = page.locator("#product_description + p")
    description = await _text(description_el, "desc") if await description_el.count() else None

    image = page.locator("#product_gallery img, div.item.active img")
    image_url = await image.first.evaluate("e => e.src") if await image.count() else None

    data: dict[str, Any] = {
        "url": page.url,
        "title": await _text(main.locator("h1"), "title"),
        "category": await _text(page.locator("ul.breadcrumb li").nth(2), "category"),
        "upc": info.get("UPC", ""),
        "price_gbp": parse_price(await _text(main.locator("p.price_color"), "price")),
        "rating": parse_rating(rating_class),
        "in_stock": in_stock,
        "stock_count": stock_count,
        "description": description,
        "image_url": image_url,
    }
    try:
        return Book.model_validate(data)
    except ValidationError as exc:
        raise ParseError(f"Invalid book data at {page.url}: {exc}") from exc


# ---------------------------------------------------------------- scraper


class BooksScraper(BaseScraper[Book]):
    name: ClassVar[str] = "books"
    start_url: ClassVar[str] = "https://books.toscrape.com/"

    def __init__(
        self,
        settings: ScraperSettings,
        *,
        max_pages: int | None = None,
        start_url: str | None = None,
    ) -> None:
        super().__init__(settings)
        self.max_pages = max_pages
        if start_url:
            self.start_url = start_url  # type: ignore[misc]

    async def scrape(self, context: BrowserContext) -> AsyncIterator[Book]:
        book_urls = await self._collect_book_urls(context)
        logger.info("Discovered %d books; fetching details", len(book_urls))

        semaphore = asyncio.Semaphore(self.settings.concurrency)
        tasks = [
            asyncio.create_task(self._scrape_book_safely(context, url, semaphore))
            for url in book_urls
        ]
        try:
            for finished in asyncio.as_completed(tasks):
                book = await finished
                if book is not None:
                    yield book
        finally:
            # If the consumer stops early (or we're cancelled) don't leak tasks.
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _collect_book_urls(self, context: BrowserContext) -> list[str]:
        page = await context.new_page()
        urls: list[str] = []
        next_url: str | None = self.start_url
        try:
            while next_url and (
                self.max_pages is None or self.stats.pages_visited < self.max_pages
            ):
                current = next_url
                await self.with_retry(partial(goto, page, current), f"listing {current}")
                self.stats.pages_visited += 1
                found = await parse_listing(page)
                logger.info("Listing page %d: %d books", self.stats.pages_visited, len(found))
                urls.extend(found)
                next_url = await parse_next_page(page)
                await self.polite_pause()
        finally:
            await page.close()
        # Preserve order but drop duplicates.
        return list(dict.fromkeys(urls))

    async def _scrape_book_safely(
        self, context: BrowserContext, url: str, semaphore: asyncio.Semaphore
    ) -> Book | None:
        async with semaphore:
            try:
                return await self.with_retry(lambda: self._scrape_book(context, url), url)
            except Exception as exc:  # isolate failures: one bad page never kills the run
                logger.error("Giving up on %s: %s", url, exc)
                self.stats.record_failure(url)
                return None
            finally:
                await self.polite_pause()

    async def _scrape_book(self, context: BrowserContext, url: str) -> Book:
        page = await context.new_page()
        try:
            await goto(page, url)
            book = await parse_book(page)
            logger.debug("Parsed %s", book.title)
            return book
        finally:
            await page.close()
