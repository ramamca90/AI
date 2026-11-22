"""In-process bus for unit tests and single-process demos."""

import asyncio

from orderflow_common.events.base import Event, EventBus, EventHandler, dispatch
from orderflow_common.logging import get_logger

logger = get_logger(__name__)


class InMemoryEventBus(EventBus):
    def __init__(self) -> None:
        self.published: list[Event] = []
        self._queue: asyncio.Queue[Event] = asyncio.Queue()

    async def publish(self, event: Event) -> None:
        self.published.append(event)
        await self._queue.put(event)

    async def consume(self, handler: EventHandler, *, subscription: str) -> None:
        while True:
            event = await self._queue.get()
            try:
                await dispatch(handler, event)
            except Exception:
                logger.exception("event_handler_failed", event_id=str(event.id), type=event.type)
            finally:
                self._queue.task_done()
