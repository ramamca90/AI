"""Redis Streams transport (local development / docker-compose).

Uses consumer groups so each subscribing service gets every event once and
replicas of the same service share the load - the same semantics as an
Azure Service Bus topic + subscription.
"""

import asyncio
import socket

from pydantic import ValidationError
from redis.asyncio import Redis
from redis.exceptions import ResponseError

from orderflow_common.events.base import Event, EventBus, EventHandler, dispatch
from orderflow_common.logging import get_logger

logger = get_logger(__name__)

_BLOCK_MS = 5000


class RedisStreamsEventBus(EventBus):
    def __init__(
        self,
        url: str,
        *,
        stream: str,
        max_len: int = 100_000,
        max_attempts: int = 3,
        consumer_name: str | None = None,
    ) -> None:
        self._url = url
        self._stream = stream
        self._dead_letter_stream = f"{stream}.dlq"
        self._max_len = max_len
        self._max_attempts = max_attempts
        self._consumer = consumer_name or socket.gethostname()
        self._redis: Redis | None = None

    @property
    def redis(self) -> Redis:
        if self._redis is None:
            raise RuntimeError("RedisStreamsEventBus.start() was not called")
        return self._redis

    async def start(self) -> None:
        # The socket timeout must exceed the XREADGROUP block time, otherwise an
        # idle blocking read is reported as a TimeoutError (redis-py >= 8
        # defaults socket_timeout to 5s).
        self._redis = Redis.from_url(
            self._url,
            decode_responses=True,
            socket_timeout=_BLOCK_MS / 1000 + 10,
            socket_connect_timeout=5,
            health_check_interval=30,
        )

    async def close(self) -> None:
        if self._redis is not None:
            await self._redis.aclose()

    async def ping(self) -> None:
        await self.redis.ping()

    async def publish(self, event: Event) -> None:
        await self.redis.xadd(
            self._stream,
            {"event": event.model_dump_json(), "type": event.type},
            maxlen=self._max_len,
            approximate=True,
        )

    async def consume(self, handler: EventHandler, *, subscription: str) -> None:
        await self._ensure_group(subscription)
        logger.info("consumer_started", transport="redis", stream=self._stream, group=subscription)
        # 1) Messages delivered to this consumer before a crash but never acked.
        while await self._read_batch(subscription, handler, start_id="0") > 0:
            pass
        # 2) New messages.
        while True:
            await self._read_batch(subscription, handler, start_id=">", block_ms=_BLOCK_MS)

    async def _read_batch(
        self, group: str, handler: EventHandler, *, start_id: str, block_ms: int | None = None
    ) -> int:
        response = await self.redis.xreadgroup(
            groupname=group,
            consumername=self._consumer,
            streams={self._stream: start_id},
            count=20,
            block=block_ms,
        )
        handled = 0
        for _stream, messages in response or []:
            for message_id, fields in messages:
                await self._handle(group, message_id, fields, handler)
                handled += 1
        return handled

    async def _ensure_group(self, group: str) -> None:
        try:
            await self.redis.xgroup_create(self._stream, group, id="0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def _handle(
        self, group: str, message_id: str, fields: dict[str, str], handler: EventHandler
    ) -> None:
        try:
            event = Event.model_validate_json(fields["event"])
        except (KeyError, ValidationError) as exc:
            await self._dead_letter(group, message_id, fields, f"deserialization: {exc}")
            return

        for attempt in range(1, self._max_attempts + 1):
            try:
                await dispatch(handler, event)
                break
            except Exception as exc:
                logger.warning(
                    "event_handler_failed",
                    event_id=str(event.id),
                    type=event.type,
                    attempt=attempt,
                    error=str(exc),
                )
                if attempt == self._max_attempts:
                    await self._dead_letter(group, message_id, fields, str(exc))
                    return
                await asyncio.sleep(0.5 * 2 ** (attempt - 1))
        await self.redis.xack(self._stream, group, message_id)

    async def _dead_letter(
        self, group: str, message_id: str, fields: dict[str, str], reason: str
    ) -> None:
        logger.error("event_dead_lettered", message_id=message_id, group=group, reason=reason)
        await self.redis.xadd(
            self._dead_letter_stream, {**fields, "group": group, "reason": reason[:500]}
        )
        await self.redis.xack(self._stream, group, message_id)
