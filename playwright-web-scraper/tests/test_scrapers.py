"""Browser-level tests against the offline mock site (real Chromium, fake network)."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from playwright.async_api import BrowserContext

from mock_site import BOOKS_BASE, build_books_site, build_quotes_site
from webscraper.config import ScraperSettings
from webscraper.exceptions import ParseError
from webscraper.models import Book
from webscraper.runner import run_scraper
from webscraper.scrapers import BooksScraper, QuotesScraper
from webscraper.scrapers.books import parse_book, parse_listing, parse_next_page


async def test_parse_listing_resolves_absolute_urls(context: BrowserContext) -> None:
    await build_books_site().install(context)
    page = await context.new_page()
    await page.goto(BOOKS_BASE)
    assert await parse_listing(page) == [
        BOOKS_BASE + "catalogue/book-a_1/index.html",
        BOOKS_BASE + "catalogue/book-b_2/index.html",
    ]
    assert await parse_next_page(page) == BOOKS_BASE + "catalogue/page-2.html"


async def test_parse_book(context: BrowserContext) -> None:
    await build_books_site().install(context)
    page = await context.new_page()
    await page.goto(BOOKS_BASE + "catalogue/book-a_1/index.html")
    book = await parse_book(page)
    assert book.title == "Book A"
    assert book.price_gbp == Decimal("51.77")
    assert (book.rating, book.in_stock, book.stock_count) == (3, True, 22)
    assert book.category == "Poetry"
    assert book.upc == "A1"
    assert book.description == "A description of Book A."
    assert str(book.image_url) == BOOKS_BASE + "media/cover.jpg"


async def test_parse_book_raises_on_layout_change(context: BrowserContext) -> None:
    page = await context.new_page()
    await page.set_content("<html><body><h1>Redesigned!</h1></body></html>")
    with pytest.raises(ParseError):
        await parse_book(page)


async def test_books_scraper_end_to_end(context: BrowserContext, settings: ScraperSettings) -> None:
    site = build_books_site()
    await site.install(context)
    scraper = BooksScraper(settings)

    books = [b async for b in scraper.scrape(context)]

    assert sorted(b.title for b in books) == ["Book A", "Book B", "Book C"]
    assert scraper.stats.pages_visited == 2
    # 500 once then success -> retried exactly once
    assert site.hits[BOOKS_BASE + "catalogue/book-b_2/index.html"] == 2
    # 404 is not retryable -> one hit, recorded as failure, run continues
    missing = BOOKS_BASE + "catalogue/book-missing_4/index.html"
    assert site.hits[missing] == 1
    assert scraper.stats.failed_urls == [missing]


async def test_books_scraper_respects_max_pages(
    context: BrowserContext, settings: ScraperSettings
) -> None:
    await build_books_site().install(context)
    scraper = BooksScraper(settings, max_pages=1)
    books = [b async for b in scraper.scrape(context)]
    assert {b.title for b in books} == {"Book A", "Book B"}


async def test_quotes_scraper_handles_js_and_infinite_scroll(
    context: BrowserContext, settings: ScraperSettings
) -> None:
    await build_quotes_site().install(context)
    scraper = QuotesScraper(settings, max_scrolls=10)
    quotes = [q async for q in scraper.scrape(context)]
    assert [q.author for q in quotes] == ["Ada", "Linus", "Grace", "Alan"]
    assert quotes[0].text == "First quote"
    assert quotes[0].tags == ["a", "b"]


async def test_runner_writes_output(tmp_path: Path, settings: ScraperSettings) -> None:
    out = tmp_path / "books.jsonl"
    summary = await run_scraper(
        BooksScraper(settings),  # type: ignore[arg-type]
        settings,
        out,
        "jsonl",
        setup_context=build_books_site().install,
    )

    assert (summary.items_written, summary.items_failed) == (3, 1)
    assert not summary.ok
    rows = [Book.model_validate_json(line) for line in out.read_text("utf-8").splitlines()]
    assert len(rows) == 3
