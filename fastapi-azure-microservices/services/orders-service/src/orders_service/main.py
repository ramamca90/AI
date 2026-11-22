"""ASGI entrypoint: `uvicorn orders_service.main:create_app --factory`."""

import asyncio
import contextlib
from collections.abc import AsyncIterator

from fastapi import FastAPI

from orderflow_common.app_factory import create_service_app
from orders_service.api import router
from orders_service.config import OrdersSettings, get_settings
from orders_service.outbox import OutboxRelay


def create_app(settings: OrdersSettings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @contextlib.asynccontextmanager
    async def background(app: FastAPI) -> AsyncIterator[None]:
        app.state.outbox_relay = OutboxRelay(
            app.state.db,
            app.state.event_bus,
            batch_size=settings.outbox_batch_size,
            interval=settings.outbox_poll_interval_seconds,
        )
        task = None
        if settings.outbox_relay_enabled:
            task = asyncio.create_task(app.state.outbox_relay.run_forever(), name="outbox-relay")
        try:
            yield
        finally:
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    return create_service_app(
        settings,
        title="OrderFlow Orders Service",
        description="Order lifecycle. Emits domain events via a transactional outbox.",
        routers=[router],
        background=background,
    )
