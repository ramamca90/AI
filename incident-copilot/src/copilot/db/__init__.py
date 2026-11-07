"""Persistence adapter: SQLAlchemy models and the repository the entry points use."""

from copilot.db.engine import create_engine, create_session_factory, init_schema
from copilot.db.models import Base
from copilot.db.repository import (
    DecisionConflictError,
    NotFoundError,
    Repository,
    StoredEvent,
)

__all__ = [
    "Base",
    "DecisionConflictError",
    "NotFoundError",
    "Repository",
    "StoredEvent",
    "create_engine",
    "create_session_factory",
    "init_schema",
]
