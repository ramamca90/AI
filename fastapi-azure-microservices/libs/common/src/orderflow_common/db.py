"""Async SQLAlchemy 2.0 engine, session dependency and model helpers."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

from fastapi import Request
from sqlalchemy import DateTime, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(UTC)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Database:
    def __init__(
        self, url: str, *, echo: bool = False, pool_size: int = 10, max_overflow: int = 10
    ) -> None:
        kwargs: dict[str, object] = {"echo": echo, "pool_pre_ping": True}
        if not url.startswith("sqlite"):
            # Azure Database for PostgreSQL closes idle connections; recycle first.
            kwargs.update(pool_size=pool_size, max_overflow=max_overflow, pool_recycle=1800)
        self.engine: AsyncEngine = create_async_engine(url, **kwargs)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

    @property
    def is_postgres(self) -> bool:
        return self.engine.dialect.name == "postgresql"

    async def ping(self) -> None:
        async with self.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    async def dispose(self) -> None:
        await self.engine.dispose()


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request, rolled back on error.

    Services own the transaction boundary and call `commit()` explicitly.
    """
    database: Database = request.app.state.db
    async with database.session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
