"""ASGI entrypoint: `uvicorn notification_service.main:create_app --factory`.

The event consumer runs inside the API process for simplicity. At scale it
can be split into its own Container App (same image, CONSUMER_ENABLED=true,
API traffic disabled) and scaled by KEDA on subscription queue length.
"""

import asyncio
import contextlib
from collections.abc import AsyncIterator

from fastapi import FastAPI

from notification_service.api import router
from notification_service.config import NotificationSettings, get_settings
from notification_service.processor import NotificationProcessor
from orderflow_common.app_factory import create_service_app
from orderflow_common.events import run_consumer_forever


def create_app(settings: NotificationSettings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @contextlib.asynccontextmanager
    async def background(app: FastAPI) -> AsyncIterator[None]:
        app.state.processor = NotificationProcessor(app.state.db)
        task = None
        if settings.consumer_enabled:
            task = asyncio.create_task(
                run_consumer_forever(
                    app.state.event_bus,
                    app.state.processor.handle,
                    subscription=settings.event_subscription or settings.service_name,
                ),
                name="event-consumer",
            )
        try:
            yield
        finally:
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    return create_service_app(
        settings,
        title="OrderFlow Notification Service",
        description="Consumes domain events and exposes per-user notifications.",
        routers=[router],
        background=background,
    )
