"""Domain exceptions.

The split between *retryable* and *non-retryable* errors drives the retry policy:
a 503 or a timeout is worth another attempt, a 404 or a changed page layout is not.
"""

from __future__ import annotations


class ScraperError(Exception):
    """Base class for all scraper errors."""

    retryable: bool = False


class HttpStatusError(ScraperError):
    """The server answered with a non-2xx/3xx status."""

    RETRYABLE_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})

    def __init__(self, url: str, status: int) -> None:
        super().__init__(f"HTTP {status} for {url}")
        self.url = url
        self.status = status
        self.retryable = status in self.RETRYABLE_STATUSES


class NavigationError(ScraperError):
    """Navigation produced no response (e.g. aborted, about:blank)."""

    retryable = True


class ParseError(ScraperError):
    """Expected element/data missing - usually the site layout changed."""

    retryable = False


class RobotsDisallowedError(ScraperError):
    """robots.txt forbids fetching the start URL."""
