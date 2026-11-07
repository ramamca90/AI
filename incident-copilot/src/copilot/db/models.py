"""Table definitions. Keep migrations/ in step: tests/platform/test_migrations.py enforces it."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    Dialect,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from copilot.domain.models import IncidentStatus, ProposalStatus

TERMINAL_STATUSES = (
    IncidentStatus.RESOLVED,
    IncidentStatus.CLOSED_NO_ACTION,
    IncidentStatus.FAILED,
)


def _sql_list(values: list[str]) -> str:
    return ", ".join(f"'{value}'" for value in values)


# The predicate of the partial unique index below. Both engines evaluate it inside the
# index, so "at most one active incident per fingerprint" holds under any concurrency and
# needs no application lock. A terminal row drops out of the index, which frees the
# fingerprint for the next occurrence. Status never leaves a terminal state.
ACTIVE_INCIDENT_PREDICATE = f"status NOT IN ({_sql_list(list(TERMINAL_STATUSES))})"
INCIDENT_STATUS_CHECK = f"status IN ({_sql_list(list(IncidentStatus))})"
PROPOSAL_STATUS_CHECK = f"status IN ({_sql_list(list(ProposalStatus))})"

# SQLite only treats a plain INTEGER primary key as a rowid alias, so BIGINT is Postgres-only.
EventId = BigInteger().with_variant(Integer(), "sqlite")
JsonDocument = JSON().with_variant(JSONB(), "postgresql")


class UTCDateTime(TypeDecorator[datetime]):
    """Timezone-aware UTC on the Python side of both engines. SQLite stores no offset."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime passed to a UTC column")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(table_name)s_%(column_0_N_name)s",
            "uq": "uq_%(table_name)s_%(column_0_N_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


class IncidentRow(Base):
    __tablename__ = "incidents"
    __table_args__ = (
        CheckConstraint(INCIDENT_STATUS_CHECK, name="status_valid"),
        Index(
            "uq_incidents_active_fingerprint",
            "fingerprint",
            unique=True,
            sqlite_where=text(ACTIVE_INCIDENT_PREDICATE),
            postgresql_where=text(ACTIVE_INCIDENT_PREDICATE),
        ),
        Index("ix_incidents_created_at_id", "created_at", "id"),
        Index("ix_incidents_status_updated_at", "status", "updated_at"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(128))
    service: Mapped[str] = mapped_column(String(128))
    alert: Mapped[dict[str, Any]] = mapped_column(JsonDocument)
    status: Mapped[str] = mapped_column(String(32))
    triage: Mapped[dict[str, Any] | None] = mapped_column(JsonDocument)
    findings: Mapped[dict[str, Any]] = mapped_column(JsonDocument)
    report: Mapped[dict[str, Any] | None] = mapped_column(JsonDocument)
    usage: Mapped[dict[str, Any]] = mapped_column(JsonDocument)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    # Bumped by every event, so it doubles as the heartbeat the stale-job sweep reads.
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class ProposalRow(Base):
    __tablename__ = "proposals"
    __table_args__ = (CheckConstraint(PROPOSAL_STATUS_CHECK, name="status_valid"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    incident_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("incidents.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    draft: Mapped[dict[str, Any]] = mapped_column(JsonDocument)
    status: Mapped[str] = mapped_column(String(32))
    decided_by: Mapped[str | None] = mapped_column(String(128))
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    # Set by the claim that gates execution. ProposalStatus has no "executing" state, so this
    # is what stops a redelivered job from running an approved action a second time.
    execution_started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    result: Mapped[str | None] = mapped_column(Text)


class EventRow(Base):
    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_incident_id_id", "incident_id", "id"),
        {"sqlite_autoincrement": True},
    )

    # AUTOINCREMENT on SQLite and a sequence on Postgres: ids only ever go up. See
    # Repository._insert_event for why commit order matches id order within an incident.
    id: Mapped[int] = mapped_column(EventId, primary_key=True, autoincrement=True)
    incident_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("incidents.id", ondelete="CASCADE")
    )
    type: Mapped[str] = mapped_column(String(32))
    agent: Mapped[str | None] = mapped_column(String(128))
    data: Mapped[dict[str, Any]] = mapped_column(JsonDocument)
    at: Mapped[datetime] = mapped_column(UTCDateTime)
