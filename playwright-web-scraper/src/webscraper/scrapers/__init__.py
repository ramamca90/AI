"""Site-specific scrapers. Register new ones in ``SCRAPERS``."""

from webscraper.scrapers.base import BaseScraper, ScrapeStats
from webscraper.scrapers.books import BooksScraper
from webscraper.scrapers.quotes import QuotesScraper

__all__ = ["SCRAPERS", "BaseScraper", "BooksScraper", "QuotesScraper", "ScrapeStats"]

SCRAPERS: dict[str, type[BaseScraper]] = {  # type: ignore[type-arg]
    BooksScraper.name: BooksScraper,
    QuotesScraper.name: QuotesScraper,
}
