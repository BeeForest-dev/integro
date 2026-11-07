"""User persistence (C15) — the C10 pattern applied to users."""

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models import User


async def create_user(session: AsyncSession, *, email: str, password_hash: str) -> User:
    """Persist a new user and return the flushed row.

    The session is flushed but not committed — the caller owns the
    transaction boundary. On an email collision the session is rolled back
    and the error maps to a domain error.

    Args:
        session: The session to insert through.
        email: Unique login identifier.
        password_hash: Argon2id hash from ``services.auth.password``.

    Returns:
        The persisted ``User`` with ``id`` set.

    Raises:
        app.core.errors.AppError: 409 when the email already exists.
    """
    user = User(email=email, password_hash=password_hash)
    session.add(user)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise AppError(
            f"user email '{email}' already exists",
            status_code=409,
            title="Conflict",
        ) from exc
    await session.refresh(user)
    return user
