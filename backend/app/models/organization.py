"""Organization (tenant) model (C10)."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Organization(Base):
    """A tenant organization — the isolation boundary of the whole app.

    Attributes:
        id: Primary key, generated uuid4 when the row is inserted.
        name: Human-readable organization name (required).
        slug: URL-safe unique identifier (required, unique, indexed).
        plan: Subscription plan, ``"free"`` unless specified otherwise.
        created_at: Row creation timestamp (timezone-aware, server default).
    """

    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(nullable=False)
    slug: Mapped[str] = mapped_column(nullable=False, unique=True, index=True)
    plan: Mapped[str] = mapped_column(nullable=False, default="free")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
