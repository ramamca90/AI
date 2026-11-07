"""Composition root for the API process."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from copilot.api.deps import Services
from copilot.api.errors import install_error_handlers
from copilot.api.middleware import RequestIdMiddleware
from copilot.api.routes import router
from copilot.api.ui import load_index_page
from copilot.config import Settings, get_settings
from copilot.db import Repository, create_engine, create_session_factory, init_schema
from copilot.domain.ports import JobQueue
from copilot.queue import build_queue
from copilot.worker.handlers import JobHandlers
from copilot.worker.runtime import (
    RuntimeFactory,
    default_rejection_errors,
    default_runtime_factory,
)
from copilot.worker.sweeper import run_sweeper

log = structlog.get_logger(__name__)

_DEFAULT_API_KEY = Settings.model_fields["api_key"].default.get_secret_value()
_SSE_POLL_SECONDS = 0.5


def warn_on_default_api_key(settings: Settings) -> None:
    """Settings has no mode to tell production from dev, so this can only warn, not refuse."""
    if settings.api_key.get_secret_value() == _DEFAULT_API_KEY:
        log.warning(
            "SECURITY WARNING: API_KEY is still the public default. Anyone can create alerts "
            "and approve remediations. Set API_KEY before exposing this service."
        )


def create_app(
    settings: Settings | None = None,
    *,
    queue: JobQueue | None = None,
    runtime_factory: RuntimeFactory = default_runtime_factory,
    rejection_errors: tuple[type[Exception], ...] | None = None,
    sse_poll_seconds: float = _SSE_POLL_SECONDS,
) -> FastAPI:
    resolved = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        warn_on_default_api_key(resolved)
        engine = create_engine(resolved.database_url)
        await init_schema(engine)
        repository = Repository(create_session_factory(engine))
        job_queue = queue or build_queue(resolved)
        app.state.services = Services(resolved, repository, job_queue, sse_poll_seconds)

        background: list[asyncio.Task[None]] = []
        if resolved.queue_backend == "local":
            errors = default_rejection_errors() if rejection_errors is None else rejection_errors
            handlers = JobHandlers(repository, resolved, runtime_factory, errors)
            background.append(asyncio.create_task(job_queue.consume(handlers.handle)))
            background.append(asyncio.create_task(run_sweeper(repository, job_queue)))
            log.info("api.embedded_worker_started")
        try:
            yield
        finally:
            for task in background:
                task.cancel()  # consume() drains in-flight jobs before it finishes.
            await asyncio.gather(*background, return_exceptions=True)
            await engine.dispose()

    app = FastAPI(title="Incident Copilot", version="0.1.0", lifespan=lifespan)
    app.state.index_page = load_index_page()
    app.add_middleware(RequestIdMiddleware)
    install_error_handlers(app)
    app.include_router(router)
    return app
