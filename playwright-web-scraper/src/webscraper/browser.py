"""Browser lifecycle and navigation helpers."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from playwright.async_api import (
    BrowserContext,
    Page,
    Response,
    Route,
    async_playwright,
)

from webscraper.config import ScraperSettings
from webscraper.exceptions import HttpStatusError, NavigationError

logger = logging.getLogger(__name__)

BLOCKED_RESOURCE_TYPES = frozenset({"image", "media", "font"})


async def _block_heavy_resources(route: Route) -> None:
    if route.request.resource_type in BLOCKED_RESOURCE_TYPES:
        await route.abort()
    else:
        await route.continue_()


@asynccontextmanager
async def browser_context(settings: ScraperSettings) -> AsyncIterator[BrowserContext]:
    """Launch a browser and yield an isolated context; always tears both down."""
    async with async_playwright() as pw:
        browser_type = getattr(pw, settings.browser)
        logger.debug("Launching %s (headless=%s)", settings.browser, settings.headless)
        browser = await browser_type.launch(headless=settings.headless)
        try:
            context = await browser.new_context(
                user_agent=settings.user_agent,
                viewport={"width": 1366, "height": 900},
                locale="en-US",
                java_script_enabled=True,
            )
            context.set_default_navigation_timeout(settings.navigation_timeout_ms)
            context.set_default_timeout(settings.navigation_timeout_ms)
            if settings.block_resources:
                await context.route("**/*", _block_heavy_resources)
            try:
                yield context
            finally:
                await context.close()
        finally:
            await browser.close()


async def goto(page: Page, url: str, *, wait_until: str = "domcontentloaded") -> Response:
    """Navigate and turn bad HTTP statuses into typed exceptions."""
    response = await page.goto(url, wait_until=wait_until)  # type: ignore[arg-type]
    if response is None:
        raise NavigationError(f"No response for {url}")
    if response.status >= 400:
        raise HttpStatusError(url, response.status)
    return response
