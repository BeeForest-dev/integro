"""Event persistence (C22)."""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event


async def insert_event(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    connection_id: uuid.UUID | None,
    event_type: str,
    payload: dict[str, Any],
    idempotency_key: str,
) -> Event:
    """Insert one event row (flushed; uniqueness violations propagate).

    Args:
        session: The session to insert through.
        organization_id: The owning organization.
        connection_id: The accepting connection, if any.
        event_type: The event/connector type.
        payload: The normalized payload (JSON object).
        idempotency_key: The dedupe key, unique per organization.

    Returns:
        The flushed ``Event`` row.

    Raises:
        sqlalchemy.exc.IntegrityError: On an (organization_id,
            idempotency_key) collision — callers turn this into a duplicate.
    """
    event = Event(
        organization_id=organization_id,
        connection_id=connection_id,
        type=event_type,
        payload=payload,
        idempotency_key=idempotency_key,
    )
    session.add(event)
    await session.flush()
    return event


async def get_by_org_key(
    session: AsyncSession, organization_id: uuid.UUID, idempotency_key: str
) -> Event | None:
    """Fetch the event stored under this organization + idempotency key."""
    statement = select(Event).where(
        Event.organization_id == organization_id,
        Event.idempotency_key == idempotency_key,
    )
    return await session.scalar(statement)
