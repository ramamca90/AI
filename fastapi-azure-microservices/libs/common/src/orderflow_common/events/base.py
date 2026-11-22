"""Event envelope (CloudEvents-inspired) and the transport-agnostic bus interface.

Business code only ever sees `Event` and `EventBus`. Whether events travel
over Redis Streams (local) or Azure Service Bus topics (cloud) is a
configuration switch, not a code change.
"""

import uuid
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from orderflow_common.context import correlation_id_var, get_correlation_id


class Event(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    type: str
    source: str
    subject: str | None = None
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    correlation_id: str | None = Field(default_factory=get_correlation_id)
    schema_version: int = 1
    data: dict[str, Any] = Field(default_factory=dict)


EventHandler = Callable[[Event], Awaitable[None]]


class EventBus(ABC):
    """At-least-once publish/subscribe. Consumers must be idempotent."""

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def ping(self) -> None:
        return None

    @abstractmethod
    async def publish(self, event: Event) -> None: ...

    @abstractmethod
    async def consume(self, handler: EventHandler, *, subscription: str) -> None:
        """Deliver events to `handler` until cancelled."""


async def dispatch(handler: EventHandler, event: Event) -> None:
    """Invoke a handler with the producer's correlation id restored, so logs
    and traces from the consumer line up with the original HTTP request."""
    token = correlation_id_var.set(event.correlation_id)
    try:
        await handler(event)
    finally:
        correlation_id_var.reset(token)
