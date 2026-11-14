"""Connection model (C18) — an integration connection owned by one org."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# The connector families of M2/M4 plus the schedule trigger;
# validated at the repository choke point.
SUPPORTED_TYPES = frozenset({"webhook_in", "telegram", "imap_mailbox", "http_api", "schedule"})


class Connection(Base):
    """An integration connection owned by one organization.

    Attributes:
        id: Primary key, generated uuid4 when the row is inserted.
        organization_id: The owning organization (isolation boundary).
        name: Human-readable connection name.
        type: One of :data:`SUPPORTED_TYPES` (enforced on create).
        config: Connector-specific settings as a JSON object.
        secret_ciphertext: Fernet token of the connection secret (C17), or NULL.
        status: ``"active"``, ``"secret_error"`` (set by read_secret) or
            ``"auth_failed"`` (set by the IMAP poller on rejected credentials);
            the column is a plain String — new values are contract-level, not
            schema-level.
        created_at: Row creation timestamp (timezone-aware, server default).
    """

    __tablename__ = "connections"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(nullable=False)
    type: Mapped[str] = mapped_column(nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    secret_ciphertext: Mapped[str | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
