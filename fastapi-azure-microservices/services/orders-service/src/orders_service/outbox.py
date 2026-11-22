"""Transactional outbox relay.

Polls unpublished rows and pushes them to the event bus. `FOR UPDATE SKIP
LOCKED` lets every replica run a relay concurrently without double-sending
the same row. Delivery is at-least-once; Service Bus duplicate detection
(message_id = event id) and idempotent consumers handle the rare re-send.
"""

import asyncio

from sqlalchemy import select

from orderflow_common.db import Database, utcnow
from orderflow_common.events import Event, EventBus
from orderflow_common.logging import get_logger
from orders_service.models import OutboxMessage

logger = get_logger(__name__)


class OutboxRelay:
    def __init__(
        self, db: Database, bus: EventBus, *, batch_size: int = 50, interval: float = 1.0
    ) -> None:
        self._db = db
        self._bus = bus
        self._batch_size = batch_size
        self._interval = interval

    async def relay_once(self) -> int:
        """Publish one batch. Returns how many events were published."""
        published = 0
        async with self._db.session_factory() as session:
            rows = (
                await session.scalars(
                    select(OutboxMessage)
                    .where(OutboxMessage.published_at.is_(None))
                    .order_by(OutboxMessage.created_at)
                    .limit(self._batch_size)
                    .with_for_update(skip_locked=True)
                )
            ).all()
            for row in rows:
                try:
                    await self._bus.publish(Event.model_validate(row.payload))
                except Exception as exc:
                    row.attempts += 1
                    row.last_error = str(exc)[:1000]
                    logger.warning("outbox_publish_failed", event_id=str(row.id), error=str(exc))
                    break  # keep ordering; retry this row on the next tick
                row.published_at = utcnow()
                published += 1
            await session.commit()
        if published:
            logger.info("outbox_relayed", count=published)
        return published

    async def run_forever(self) -> None:
        logger.info("outbox_relay_started")
        while True:
            try:
                published = await self.relay_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("outbox_relay_error")
                published = 0
            if published < self._batch_size:
                await asyncio.sleep(self._interval)
