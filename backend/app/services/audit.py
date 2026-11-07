"""Audit recording (C15, minimal).

Records one row per action inside the caller's transaction. C19 owns the
full contract (diffs, ip, entity columns, failure isolation) and will
extend both the table and this function.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog


async def record_audit(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    action: str,
    actor_user_id: uuid.UUID | None = None,
) -> AuditLog:
    """Record one audit row (flushed, not committed — the caller commits).

    Args:
        session: The session to insert through.
        organization_id: The organization the action happened in.
        action: Short action identifier (e.g. ``"user.registered"``).
        actor_user_id: The acting user, if any.

    Returns:
        The persisted ``AuditLog`` row.
    """
    entry = AuditLog(
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        action=action,
    )
    session.add(entry)
    await session.flush()
    return entry
