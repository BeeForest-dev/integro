"""Membership model (C11) — links a user to an organization with a role."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, UniqueConstraint, Uuid, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, validates

from app.db.base import Base


class MembershipRole(enum.StrEnum):
    """The role a user holds inside one organization (values are persisted)."""

    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


class Membership(Base):
    """A user's membership in one organization.

    Attributes:
        id: Primary key, generated uuid4 when the row is inserted.
        user_id: The member user (references ``users.id``).
        organization_id: The organization (references ``organizations.id``).
        role: One of :class:`MembershipRole`.
        created_at: Row creation timestamp (timezone-aware, server default).
    """

    __tablename__ = "memberships"

    __table_args__ = (
        UniqueConstraint(
            "user_id", "organization_id", name="uq_memberships_user_organization"
        ),
        CheckConstraint(
            "role IN ('owner', 'admin', 'member', 'viewer')", name="ck_memberships_role"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"), nullable=False
    )
    role: Mapped[MembershipRole] = mapped_column(
        SAEnum(
            MembershipRole,
            native_enum=False,
            validate_strings=True,
            # The database CHECK (see __table_args__) is the constraint of
            # record; the enum type must not create a second one.
            create_constraint=False,
            # Persist the lowercase values ("owner"), not the member names.
            values_callable=lambda role_enum: [member.value for member in role_enum],
        ),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    @validates("role")
    def _validate_role(self, _key: str, role: MembershipRole | str) -> MembershipRole:
        """Coerce a string to the enum; anything unknown is a validation error."""
        if isinstance(role, MembershipRole):
            return role
        try:
            return MembershipRole(role)
        except ValueError:
            allowed = [member.value for member in MembershipRole]
            raise ValueError(
                f"invalid membership role: {role!r} (expected one of {allowed})"
            ) from None
