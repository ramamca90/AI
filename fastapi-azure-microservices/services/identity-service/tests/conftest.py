from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from identity_service.config import IdentitySettings
from identity_service.main import create_app
from identity_service.models import Base


@pytest.fixture
def settings(tmp_path: Path) -> IdentitySettings:
    return IdentitySettings(
        environment="test",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'identity.db'}",
        event_bus_backend="memory",
        jwt_secret="identity-test-secret-0123456789abcdef",
        log_json=False,
        applicationinsights_connection_string=None,
    )


@pytest.fixture
async def app(settings: IdentitySettings) -> AsyncIterator[FastAPI]:
    application = create_app(settings)
    async with LifespanManager(application):
        async with application.state.db.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
