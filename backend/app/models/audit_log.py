"""Audit log model (C15 minimal, C19 full shape).

One recorded action inside one organization. The C19 migration adds the
entity/diff/ip columns; C15 rows (created before the migration) stay valid
with NULLs in the new columns.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AuditLog(Base):
    """One recorded action inside one organization.

    Attributes:
        id: Primary key, generated uuid4 when the row is inserted.
        organization_id: The organization the action happened in.
        actor_user_id: The acting user, NULL when no user is responsible.
        action: Short action identifier (e.g. ``"user.registered"``).
        entity: The affected entity type (e.g. ``"connection"``), if any.
        entity_id: The affected entity id, if any.
        before_json: Entity state before the action (caller-built dict).
        after_json: Entity state after the action (caller-built dict).
        ip: The caller's IP address, if known.
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
    entity: Mapped[str | None] = mapped_column(nullable=True)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    before_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    after_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    ip: Mapped[str | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
