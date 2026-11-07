"""Engine construction. All dialect-specific connection setup lives here."""

from __future__ import annotations

from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from copilot.db.models import Base

# How long a SQLite writer queues for the single write lock before giving up, in seconds.
_SQLITE_BUSY_TIMEOUT = 30


def _configure_sqlite(dbapi_connection: Any, _record: Any) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


def create_engine(database_url: str) -> AsyncEngine:
    if database_url.startswith("sqlite"):
        engine = create_async_engine(database_url, connect_args={"timeout": _SQLITE_BUSY_TIMEOUT})
        event.listen(engine.sync_engine, "connect", _configure_sqlite)
        return engine
    return create_async_engine(database_url, pool_pre_ping=True)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def init_schema(engine: AsyncEngine) -> None:
    """Create tables on SQLite so a bare local checkout runs without a migration step.

    Postgres is left alone on purpose: its schema is owned by `alembic upgrade head`.
    """
    if engine.dialect.name == "sqlite":
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
