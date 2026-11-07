"""Shared fixtures. Tests use a temporary SQLite file, a fake runtime and no network."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from tests.platform.support import API_KEY, FakeRuntime, Platform, RejectedError

from copilot.api.app import create_app
from copilot.config import Settings
from copilot.db import Base, Repository, create_engine, create_session_factory
from copilot.queue import LocalQueue
from copilot.worker.handlers import JobHandlers


@pytest.fixture
def database_url(tmp_path: Path) -> str:
    return f"sqlite+aiosqlite:///{(tmp_path / 'test.db').as_posix()}"


@pytest.fixture
async def repository(database_url: str) -> AsyncIterator[Repository]:
    engine = create_engine(database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield Repository(create_session_factory(engine))
    await engine.dispose()


@pytest.fixture
def settings(database_url: str) -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_url=database_url,
        queue_backend="local",
        api_key=API_KEY,  # type: ignore[arg-type]
    )


@pytest.fixture
def runtime() -> FakeRuntime:
    return FakeRuntime()


@pytest.fixture
def handlers(repository: Repository, settings: Settings, runtime: FakeRuntime) -> JobHandlers:
    return JobHandlers(repository, settings, runtime.factory, (RejectedError,))


@pytest.fixture
def queue() -> LocalQueue:
    return LocalQueue(max_attempts=1, retry_delay_seconds=0, grace_seconds=5)


@pytest.fixture
async def platform(
    settings: Settings, queue: LocalQueue, runtime: FakeRuntime
) -> AsyncIterator[Platform]:
    app = create_app(
        settings,
        queue=queue,
        runtime_factory=runtime.factory,
        rejection_errors=(RejectedError,),
        sse_poll_seconds=0,
    )
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield Platform(app, client, queue, runtime)
