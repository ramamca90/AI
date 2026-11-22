import uuid

from sqlalchemy import JSON, Boolean, String, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from orderflow_common.db import TimestampMixin


class Base(DeclarativeBase):
    pass


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(255))
    roles: Mapped[list[str]] = mapped_column(JSON, default=lambda: ["customer"])
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
