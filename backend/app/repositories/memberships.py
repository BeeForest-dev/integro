"""Membership persistence (C15)."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Membership, MembershipRole


async def create_membership(
    session: AsyncSession,
    *,
    user_id,
    organization_id,
    role: MembershipRole,
) -> Membership:
    """Persist a new membership and return the flushed row.

    Args:
        session: The session to insert through.
        user_id: The member user.
        organization_id: The organization.
        role: The membership role.

    Returns:
        The persisted ``Membership`` with ``id`` set.
    """
    membership = Membership(user_id=user_id, organization_id=organization_id, role=role)
    session.add(membership)
    await session.flush()
    await session.refresh(membership)
    return membership
