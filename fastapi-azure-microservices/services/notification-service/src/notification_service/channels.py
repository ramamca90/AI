"""Outbound delivery channels.

The demo ships a logging channel. In production you would add e.g. an
Azure Communication Services email/SMS channel implementing the same
protocol - the processor does not change.
"""

from typing import Protocol

from notification_service.models import Notification
from orderflow_common.logging import get_logger

logger = get_logger(__name__)


class NotificationChannel(Protocol):
    async def send(self, notification: Notification) -> None: ...


class LogChannel:
    async def send(self, notification: Notification) -> None:
        logger.info(
            "notification_sent",
            channel="log",
            user_id=str(notification.user_id),
            title=notification.title,
        )
