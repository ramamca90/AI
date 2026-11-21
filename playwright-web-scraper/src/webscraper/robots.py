"""robots.txt compliance check."""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

logger = logging.getLogger(__name__)


async def is_allowed(url: str, user_agent: str) -> bool:
    """Return True if robots.txt permits ``user_agent`` to fetch ``url``.

    An unreachable robots.txt is treated as "allowed" (the common crawler convention),
    but logged so it's visible.
    """
    parts = urlsplit(url)
    robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
    parser = RobotFileParser(robots_url)
    try:
        await asyncio.to_thread(parser.read)
    except OSError as exc:
        logger.warning("Could not read %s (%s); assuming allowed", robots_url, exc)
        return True
    return parser.can_fetch(user_agent, url)
