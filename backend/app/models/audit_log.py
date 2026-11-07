"""Audit log model (C15, minimal) — C19 extends this table."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AuditLog(Base):
    """One recorded action inside one organization.

    C15 ships the minimal shape the auth flow needs; C19 owns the full
    contract (diffs, ip, entity, failure isolation).

    Attributes:
        id: Primary key, generated uuid4 when the row is inserted.
        organization_id: The organization the action happened in.
        actor_user_id: The acting user, NULL when no user is responsible.
        action: Short action identifier (e.g. ``"user.registered"``).
        created_at: Row creation timestamp (timezone-aware, server default).
    """

    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"), nullable=False
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    action: Mapped[str] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
