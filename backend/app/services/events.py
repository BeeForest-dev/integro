"""Event storage service (C22) — idempotent by (organization, idempotency key)."""

import uuid
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event
from app.repositories.events import get_by_org_key, insert_event


async def store_event(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    connection_id: uuid.UUID | None,
    event_type: str,
    payload: dict[str, Any],
    idempotency_key: str,
) -> tuple[Event, bool]:
    """Store an event, deduplicating on the unique org/key index.

    Args:
        session: The session to work in (survives duplicates).
        organization_id: The owning organization.
        connection_id: The accepting connection, if any.
        event_type: The event/connector type.
        payload: The normalized payload.
        idempotency_key: The dedupe key.

    Returns:
        ``(event, created)`` — ``created`` is False when the key already
        existed, in which case the EXISTING row is returned and no second
        row (or second run) is created.
    """
    try:
        event = await insert_event(
            session,
            organization_id=organization_id,
            connection_id=connection_id,
            event_type=event_type,
            payload=payload,
            idempotency_key=idempotency_key,
        )
        await session.refresh(event)
        return event, True
    except IntegrityError:
        await session.rollback()
        existing = await get_by_org_key(session, organization_id, idempotency_key)
        if existing is None:
            raise
        return existing, False
