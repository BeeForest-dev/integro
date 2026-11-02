"""Organization persistence (C10) — the repositories layer starts here.

Repositories never accept an organization id from callers to scope by —
that choke point arrives with C12. This module only creates rows.
"""

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models import Organization


async def create_organization(
    session: AsyncSession, name: str, slug: str, plan: str = "free"
) -> Organization:
    """Persist a new organization and return the flushed row.

    The session is flushed but not committed — the caller owns the
    transaction boundary. On a slug collision the session is rolled back
    (an aborted transaction cannot continue) and the error is mapped to a
    domain error.

    Args:
        session: The session to insert through.
        name: Human-readable organization name.
        slug: Unique URL-safe identifier.
        plan: Subscription plan (defaults to ``"free"``).

    Returns:
        The persisted ``Organization`` with ``id`` and ``created_at`` set.

    Raises:
        app.core.errors.AppError: 409 when the slug already exists.
    """
    organization = Organization(name=name, slug=slug, plan=plan)
    session.add(organization)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise AppError(
            f"organization slug '{slug}' already exists",
            status_code=409,
            title="Conflict",
        ) from exc
    await session.refresh(organization)
    return organization
