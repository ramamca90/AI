"""Turns domain events into user notifications - idempotently."""

import uuid
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from notification_service.channels import LogChannel, NotificationChannel
from notification_service.models import Notification
from orderflow_common.db import Database
from orderflow_common.events import Event
from orderflow_common.events.contracts import (
    EventTypes,
    OrderCancelledData,
    OrderCreatedData,
    UserRegisteredData,
)
from orderflow_common.logging import get_logger

logger = get_logger(__name__)

Rendered = tuple[uuid.UUID, str, str]  # (user_id, title, message)


def _user_registered(event: Event) -> Rendered:
    data = UserRegisteredData.model_validate(event.data)
    return data.user_id, "Welcome to OrderFlow", f"Hi {data.full_name}, your account is ready."


def _order_created(event: Event) -> Rendered:
    data = OrderCreatedData.model_validate(event.data)
    return (
        data.customer_id,
        "Order received",
        f"Order {str(data.order_id)[:8]} for {data.total_amount} {data.currency} "
        f"({data.item_count} items) has been placed.",
    )


def _order_cancelled(event: Event) -> Rendered:
    data = OrderCancelledData.model_validate(event.data)
    reason = f" Reason: {data.reason}" if data.reason else ""
    return (
        data.customer_id,
        "Order cancelled",
        f"Order {str(data.order_id)[:8]} was cancelled.{reason}",
    )


RENDERERS: dict[str, Callable[[Event], Rendered]] = {
    EventTypes.USER_REGISTERED: _user_registered,
    EventTypes.ORDER_CREATED: _order_created,
    EventTypes.ORDER_CANCELLED: _order_cancelled,
}


class NotificationProcessor:
    def __init__(self, db: Database, channel: NotificationChannel | None = None) -> None:
        self._db = db
        self._channel = channel or LogChannel()

    async def handle(self, event: Event) -> None:
        renderer = RENDERERS.get(event.type)
        if renderer is None:
            logger.debug("event_ignored", type=event.type)
            return  # ack: not every event concerns us

        user_id, title, message = renderer(event)
        async with self._db.session_factory() as session:
            if await session.scalar(
                select(Notification.id).where(Notification.event_id == event.id)
            ):
                logger.info("event_duplicate_skipped", event_id=str(event.id))
                return
            notification = Notification(
                user_id=user_id,
                event_id=event.id,
                event_type=event.type,
                title=title,
                message=message,
            )
            session.add(notification)
            try:
                await session.commit()
            except IntegrityError:
                # Lost a race with another replica processing the same event.
                await session.rollback()
                logger.info("event_duplicate_skipped", event_id=str(event.id))
                return

        await self._channel.send(notification)
        logger.info("event_processed", event_id=str(event.id), type=event.type)
