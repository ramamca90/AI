"""Async retry with exponential backoff and jitter."""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from typing import TypeVar

from playwright.async_api import Error as PlaywrightError

from webscraper.exceptions import ScraperError

logger = logging.getLogger(__name__)

T = TypeVar("T")


def is_retryable(exc: BaseException) -> bool:
    """Default policy: Playwright errors (timeouts, net::ERR_*) and retryable ScraperErrors."""
    if isinstance(exc, ScraperError):
        return exc.retryable
    return isinstance(exc, PlaywrightError)


def backoff_delay(attempt: int, base: float, cap: float) -> float:
    """Full-jitter exponential backoff (AWS style): uniform(0, min(cap, base * 2^attempt))."""
    return random.uniform(0, min(cap, base * (2 ** (attempt - 1))))


async def retry_async(
    operation: Callable[[], Awaitable[T]],
    *,
    max_retries: int,
    base_delay: float = 1.0,
    max_delay: float = 20.0,
    should_retry: Callable[[BaseException], bool] = is_retryable,
    description: str = "operation",
) -> T:
    """Run ``operation`` up to ``max_retries + 1`` times.

    Non-retryable errors propagate immediately; the last retryable error propagates
    once the budget is exhausted.
    """
    attempt = 0
    while True:
        attempt += 1
        try:
            return await operation()
        except Exception as exc:
            if attempt > max_retries or not should_retry(exc):
                raise
            delay = backoff_delay(attempt, base_delay, max_delay)
            logger.warning(
                "%s failed (attempt %d/%d): %s - retrying in %.2fs",
                description,
                attempt,
                max_retries + 1,
                exc,
                delay,
            )
            await asyncio.sleep(delay)
