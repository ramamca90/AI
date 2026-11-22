import asyncio

from orderflow_common.context import correlation_id_var
from orderflow_common.events import Event, InMemoryEventBus


async def test_consumer_receives_event_with_producer_correlation_id() -> None:
    bus = InMemoryEventBus()
    seen: list[tuple[str, str | None]] = []

    async def handler(event: Event) -> None:
        seen.append((event.type, correlation_id_var.get()))

    token = correlation_id_var.set("corr-12345678")
    try:
        await bus.publish(Event(type="test.happened", source="tests", data={"x": 1}))
    finally:
        correlation_id_var.reset(token)

    consumer = asyncio.create_task(bus.consume(handler, subscription="tests"))
    await asyncio.wait_for(bus._queue.join(), timeout=2)
    consumer.cancel()

    assert seen == [("test.happened", "corr-12345678")]


async def test_failing_handler_does_not_kill_consumer() -> None:
    bus = InMemoryEventBus()
    handled: list[int] = []

    async def handler(event: Event) -> None:
        if event.data["n"] == 1:
            raise RuntimeError("boom")
        handled.append(event.data["n"])

    for n in (1, 2):
        await bus.publish(Event(type="t", source="tests", data={"n": n}))

    consumer = asyncio.create_task(bus.consume(handler, subscription="tests"))
    await asyncio.wait_for(bus._queue.join(), timeout=2)
    consumer.cancel()

    assert handled == [2]
