"""User model (C11)."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class User(Base):
    """An application user.

    Attributes:
        id: Primary key, generated uuid4 when the row is inserted.
        email: Login identifier, unique across all users.
        password_hash: Argon2id hash of the password (C13); NULL until set,
            e.g. for users created by fixtures before auth exists.
        created_at: Row creation timestamp (timezone-aware, server default).
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(nullable=False, unique=True, index=True)
    password_hash: Mapped[str | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
