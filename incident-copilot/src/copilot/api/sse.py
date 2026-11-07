"""Server-sent events. The worker is another process, so the database is the only channel."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable

from copilot.db import Repository, StoredEvent
from copilot.db.models import TERMINAL_STATUSES
from copilot.domain.models import IncidentStatus

_BATCH_SIZE = 200
_HEARTBEAT_SECONDS = 15.0
# The stream stops here too: the next change needs a human, which can take hours, so there is
# no reason to hold a connection and poll. Clients reconnect with Last-Event-ID after deciding.
_END_STATUSES = (*TERMINAL_STATUSES, IncidentStatus.AWAITING_APPROVAL)

KEEPALIVE = ": keepalive\n\n"


def parse_last_event_id(value: str | None) -> int:
    """A cursor we can't read means replaying from the start, which is always safe."""
    if value is None or not value.isascii() or not value.isdecimal():
        return 0
    return int(value)


def format_event(stored: StoredEvent) -> str:
    # model_dump_json never emits a raw newline, so untrusted text can't forge an SSE frame.
    return (
        f"id: {stored.id}\n"
        f"event: {stored.event.type.value}\n"
        f"data: {stored.event.model_dump_json()}\n\n"
    )


def format_end(status: IncidentStatus | None) -> str:
    value = status.value if status else None
    return f"event: end\ndata: {json.dumps({'status': value})}\n\n"


async def event_stream(
    repository: Repository,
    incident_id: str,
    after_id: int,
    is_disconnected: Callable[[], Awaitable[bool]],
    poll_seconds: float,
) -> AsyncIterator[str]:
    cursor = after_id
    idle_seconds = 0.0
    while not await is_disconnected():
        # Status first. It commits together with its final status event, so if the status
        # read here is an ending one, the event read below is sure to include everything.
        status = await repository.get_status(incident_id)
        batch = await repository.list_events(incident_id, cursor, _BATCH_SIZE)
        for stored in batch:
            yield format_event(stored)
            cursor = stored.id
        if len(batch) == _BATCH_SIZE:
            continue
        if status is None or status in _END_STATUSES:
            yield format_end(status)
            return

        idle_seconds = 0.0 if batch else idle_seconds + poll_seconds
        if idle_seconds >= _HEARTBEAT_SECONDS:
            idle_seconds = 0.0
            yield KEEPALIVE
        await asyncio.sleep(poll_seconds)
