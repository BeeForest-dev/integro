"""Event model (C22) — one stored inbound event, deduplicated per org by key."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Event(Base):
    """One inbound event stored for a flow run.

    Attributes:
        id: Primary key, generated uuid4 when the row is inserted.
        organization_id: The owning organization (isolation boundary).
        connection_id: The connection that accepted the event, if any.
        type: The event/connector type (e.g. ``"webhook_in"``).
        payload: The normalized event payload (JSON object).
        idempotency_key: Caller-provided or body-hash dedupe key; unique
            per organization — a duplicate never creates a second row.
        received_at: Receipt timestamp (timezone-aware, server default).
    """

    __tablename__ = "events"

    __table_args__ = (
        UniqueConstraint(
            "organization_id", "idempotency_key", name="uq_events_org_idempotency_key"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"), nullable=False
    )
    connection_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("connections.id"), nullable=True
    )
    type: Mapped[str] = mapped_column(nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
