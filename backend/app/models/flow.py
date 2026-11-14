"""Flow models (C20): a versioned flow definition owned by one organization.

There is deliberately NO current_version foreign key on Flow — "latest" is
always ``max(flow_versions.version)`` per flow, which avoids a circular FK
and makes history the single source of truth.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Flow(Base):
    """A named, enable-able flow owned by one organization.

    Attributes:
        id: Primary key, generated uuid4 when the row is inserted.
        organization_id: The owning organization (isolation boundary).
        name: Human-readable flow name.
        enabled: Whether the flow may be triggered (default on).
        next_run_at: When a schedule-triggered flow is due next (NULL = never
            scheduled or not yet initialized by a tick).
        created_at: Row creation timestamp (timezone-aware, server default).
    """

    __tablename__ = "flows"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    next_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class FlowVersion(Base):
    """One immutable version of a flow's JSON definition.

    Attributes:
        id: Primary key, generated uuid4 when the row is inserted.
        flow_id: The flow this version belongs to.
        version: Monotonic version number, starting at 1.
        definition: The validated flow definition (JSON object).
        created_at: Row creation timestamp (timezone-aware, server default).
    """

    __tablename__ = "flow_versions"

    __table_args__ = (
        UniqueConstraint("flow_id", "version", name="uq_flow_versions_flow_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    flow_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("flows.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    definition: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
