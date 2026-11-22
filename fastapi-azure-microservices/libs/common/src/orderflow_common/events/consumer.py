"""Self-healing consumer loop: reconnects with exponential backoff."""

import asyncio

from orderflow_common.events.base import EventBus, EventHandler
from orderflow_common.logging import get_logger

logger = get_logger(__name__)


async def run_consumer_forever(
    bus: EventBus, handler: EventHandler, *, subscription: str, max_backoff: float = 30.0
) -> None:
    delay = 1.0
    while True:
        try:
            await bus.consume(handler, subscription=subscription)
            delay = 1.0
        except asyncio.CancelledError:
            logger.info("consumer_stopped", subscription=subscription)
            raise
        except Exception:
            logger.exception("consumer_crashed", subscription=subscription, retry_in_s=delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, max_backoff)
