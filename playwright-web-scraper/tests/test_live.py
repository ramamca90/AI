"""Smoke tests against the real sites. Deselected by default: ``pytest -m live``.

Useful as a scheduled canary that alerts when the target site's layout changes.
"""

import pytest
from playwright.async_api import BrowserContext

from webscraper.config import ScraperSettings
from webscraper.scrapers import BooksScraper, QuotesScraper

pytestmark = pytest.mark.live


async def test_live_books_first_page(context: BrowserContext, settings: ScraperSettings) -> None:
    scraper = BooksScraper(settings, max_pages=1)
    books = [b async for b in scraper.scrape(context)]
    assert len(books) == 20
    assert scraper.stats.items_failed == 0


async def test_live_quotes(context: BrowserContext, settings: ScraperSettings) -> None:
    quotes = [q async for q in QuotesScraper(settings, max_scrolls=2).scrape(context)]
    assert len(quotes) >= 20
