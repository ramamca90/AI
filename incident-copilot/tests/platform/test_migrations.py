"""The migration, not `create_all`, is what production runs, so it must match the models."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine as create_sync_engine

from copilot.db import Base
from copilot.db.models import ACTIVE_INCIDENT_PREDICATE, EventRow

ROOT = Path(__file__).resolve().parents[2]


def alembic_config(database_url: str) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["database_url"] = database_url
    return config


@pytest.fixture
def upgraded(tmp_path: Path) -> Path:
    path = tmp_path / "migrated.db"
    command.upgrade(alembic_config(f"sqlite+aiosqlite:///{path.as_posix()}"), "head")
    return path


def test_migration_matches_the_models(upgraded: Path) -> None:
    engine = create_sync_engine(f"sqlite:///{upgraded.as_posix()}")
    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        differences = compare_metadata(context, Base.metadata)
    engine.dispose()
    assert differences == []


def test_migration_creates_the_partial_unique_index(upgraded: Path) -> None:
    # Autogenerate doesn't compare index predicates, so check the dedupe guarantee directly.
    with sqlite3.connect(upgraded) as connection:
        sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'uq_incidents_active_fingerprint'"
        ).fetchone()[0]
    connection.close()
    assert "UNIQUE" in sql
    assert ACTIVE_INCIDENT_PREDICATE in sql


def test_migration_keeps_event_ids_autoincrementing(upgraded: Path) -> None:
    with sqlite3.connect(upgraded) as connection:
        sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name = ?", (EventRow.__tablename__,)
        ).fetchone()[0]
    connection.close()
    assert "AUTOINCREMENT" in sql


def test_migration_downgrades_cleanly(upgraded: Path) -> None:
    command.downgrade(alembic_config(f"sqlite+aiosqlite:///{upgraded.as_posix()}"), "base")
    with sqlite3.connect(upgraded) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    connection.close()
    assert tables.isdisjoint({"incidents", "proposals", "events"})


def test_the_postgres_migration_renders_jsonb_and_the_partial_index() -> None:
    """Offline SQL generation. It proves the DDL compiles for Postgres, not that it runs."""
    from contextlib import redirect_stdout
    from io import StringIO

    output = StringIO()
    with redirect_stdout(output):
        command.upgrade(alembic_config("postgresql+asyncpg://u:p@h/db"), "head", sql=True)
    sql = output.getvalue()
    assert "JSONB" in sql
    assert "BIGSERIAL" in sql
    assert f"WHERE {ACTIVE_INCIDENT_PREDICATE}" in sql
