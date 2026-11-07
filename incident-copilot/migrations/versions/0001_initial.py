"""Create incidents, proposals and events.

Revision ID: 0001
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Literal copies, not imports: a migration records the schema as it was at this revision.
ACTIVE_INCIDENT_PREDICATE = "status NOT IN ('resolved', 'closed_no_action', 'failed')"
JSON_DOCUMENT = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
UTC_DATETIME = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "incidents",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("fingerprint", sa.String(128), nullable=False),
        sa.Column("service", sa.String(128), nullable=False),
        sa.Column("alert", JSON_DOCUMENT, nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("triage", JSON_DOCUMENT, nullable=True),
        sa.Column("findings", JSON_DOCUMENT, nullable=False),
        sa.Column("report", JSON_DOCUMENT, nullable=True),
        sa.Column("usage", JSON_DOCUMENT, nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", UTC_DATETIME, nullable=False),
        sa.Column("updated_at", UTC_DATETIME, nullable=False),
        sa.CheckConstraint(
            "status IN ('queued', 'investigating', 'awaiting_approval', 'remediating', "
            "'resolved', 'closed_no_action', 'failed')",
            name=op.f("ck_incidents_status_valid"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_incidents")),
    )
    op.create_index(
        "uq_incidents_active_fingerprint",
        "incidents",
        ["fingerprint"],
        unique=True,
        sqlite_where=sa.text(ACTIVE_INCIDENT_PREDICATE),
        postgresql_where=sa.text(ACTIVE_INCIDENT_PREDICATE),
    )
    op.create_index("ix_incidents_created_at_id", "incidents", ["created_at", "id"])
    op.create_index("ix_incidents_status_updated_at", "incidents", ["status", "updated_at"])

    op.create_table(
        "proposals",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("incident_id", sa.String(32), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("draft", JSON_DOCUMENT, nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("decided_by", sa.String(128), nullable=True),
        sa.Column("decided_at", UTC_DATETIME, nullable=True),
        sa.Column("execution_started_at", UTC_DATETIME, nullable=True),
        sa.Column("result", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'executed', 'failed')",
            name=op.f("ck_proposals_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["incidents.id"],
            name=op.f("fk_proposals_incident_id_incidents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_proposals")),
    )
    op.create_index("ix_proposals_incident_id", "proposals", ["incident_id"])

    op.create_table(
        "events",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("incident_id", sa.String(32), nullable=False),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("agent", sa.String(128), nullable=True),
        sa.Column("data", JSON_DOCUMENT, nullable=False),
        sa.Column("at", UTC_DATETIME, nullable=False),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["incidents.id"],
            name=op.f("fk_events_incident_id_incidents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_events")),
        sqlite_autoincrement=True,
    )
    op.create_index("ix_events_incident_id_id", "events", ["incident_id", "id"])


def downgrade() -> None:
    op.drop_table("events")
    op.drop_table("proposals")
    op.drop_table("incidents")
