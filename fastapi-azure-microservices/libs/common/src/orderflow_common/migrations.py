"""Shared Alembic runner used by every service's `migrations/env.py`.

Migrations run at container start (RUN_MIGRATIONS=true). A Postgres
advisory lock makes that safe when several replicas start at once: one
replica migrates, the others wait and then find nothing to do.
"""

import asyncio

from alembic import context
from sqlalchemy import MetaData, pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine


def run_alembic_migrations(target_metadata: MetaData, database_url: str, *, lock_id: int) -> None:
    def _run(connection: Connection) -> None:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            if connection.dialect.name == "postgresql":
                connection.execute(text("SELECT pg_advisory_xact_lock(:id)"), {"id": lock_id})
            context.run_migrations()

    async def _online() -> None:
        engine = create_async_engine(database_url, poolclass=pool.NullPool)
        async with engine.connect() as connection:
            await connection.run_sync(_run)
        await engine.dispose()

    if context.is_offline_mode():
        context.configure(
            url=database_url,
            target_metadata=target_metadata,
            literal_binds=True,
            dialect_opts={"paramstyle": "named"},
        )
        with context.begin_transaction():
            context.run_migrations()
    else:
        asyncio.run(_online())
