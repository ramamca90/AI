"""Integration tests against a real Redis (skipped unless TEST_REDIS_URL is set).

docker compose up -d redis
$env:TEST_REDIS_URL = "redis://localhost:6379/15"; uv run pytest libs/common/tests
"""

import asyncio
import contextlib
import os
import uuid

import pytest

from orderflow_common.events import Event
from orderflow_common.events.redis_streams import RedisStreamsEventBus

REDIS_URL = os.environ.get("TEST_REDIS_URL")
pytestmark = pytest.mark.skipif(not REDIS_URL, reason="TEST_REDIS_URL not set")


async def _wait_for(predicate, timeout: float = 15.0) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.1)


async def test_idle_consumer_survives_block_timeout_then_receives() -> None:
    stream = f"it-{uuid.uuid4().hex}"
    bus = RedisStreamsEventBus(REDIS_URL, stream=stream)
    await bus.start()
    received: list[Event] = []

    async def handler(event: Event) -> None:
        received.append(event)

    consumer = asyncio.create_task(bus.consume(handler, subscription="it"))
    try:
        await asyncio.sleep(6.5)  # longer than one XREADGROUP block period
        assert not consumer.done(), consumer.exception() if consumer.done() else None

        sent = Event(type="it.happened", source="tests")
        await bus.publish(sent)
        await _wait_for(lambda: len(received) == 1)
        assert received[0].id == sent.id
    finally:
        consumer.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await consumer
        await bus.redis.delete(stream)
        await bus.close()


async def test_unacked_messages_are_redelivered_after_restart() -> None:
    stream = f"it-{uuid.uuid4().hex}"
    bus = RedisStreamsEventBus(REDIS_URL, stream=stream, consumer_name="worker-1")
    await bus.start()
    try:
        await bus.publish(Event(type="it.happened", source="tests"))
        # Simulate a crash: message delivered to worker-1, never acked.
        await bus._ensure_group("it")
        await bus.redis.xreadgroup("it", "worker-1", {stream: ">"}, count=10)

        received: list[Event] = []

        async def handler(event: Event) -> None:
            received.append(event)

        consumer = asyncio.create_task(bus.consume(handler, subscription="it"))
        try:
            await _wait_for(lambda: len(received) == 1)
        finally:
            consumer.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await consumer
        pending = await bus.redis.xpending(stream, "it")
        assert pending["pending"] == 0
    finally:
        await bus.redis.delete(stream)
        await bus.close()
