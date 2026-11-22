import uuid
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from orders_service.config import OrdersSettings
from orders_service.main import create_app
from orders_service.models import Base


@pytest.fixture
def settings(tmp_path: Path) -> OrdersSettings:
    return OrdersSettings(
        environment="test",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'orders.db'}",
        event_bus_backend="memory",
        jwt_secret="orders-test-secret-0123456789abcdef",
        outbox_relay_enabled=False,  # tests drive the relay explicitly
        log_json=False,
        applicationinsights_connection_string=None,
    )


@pytest.fixture
async def app(settings: OrdersSettings) -> AsyncIterator[FastAPI]:
    application = create_app(settings)
    async with LifespanManager(application):
        async with application.state.db.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
def auth_for(app: FastAPI) -> Callable[..., dict[str, str]]:
    def _make(user_id: uuid.UUID | None = None, roles: list[str] | None = None) -> dict[str, str]:
        token, _ = app.state.token_service.issue(
            subject=str(user_id or uuid.uuid4()), email="t@example.com", roles=roles or ["customer"]
        )
        return {"Authorization": f"Bearer {token}"}

    return _make
