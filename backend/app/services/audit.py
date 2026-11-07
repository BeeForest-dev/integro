"""Audit recording (C19 full): strict writer + failure-isolated wrapper.

``record_audit`` stays strict (flush-not-commit; a failure aborts the
caller's transaction on purpose). ``try_record_audit`` wraps it in a
SAVEPOINT so an audit failure is logged and swallowed: the business
operation must survive a broken audit write (C15 registers and logins use
this path). Failure logs carry action/entity/org identifiers only — audit
payloads may contain secrets and are never logged.
"""

import uuid
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog

logger = structlog.get_logger(__name__)


async def record_audit(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    action: str,
    actor_user_id: uuid.UUID | None = None,
    entity: str | None = None,
    entity_id: uuid.UUID | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    ip: str | None = None,
) -> AuditLog:
    """Record one audit row (flushed, not committed — the caller commits).

    Strict by design: callers that must survive an audit failure use
    :func:`try_record_audit` instead. Before/after dicts are built by the
    caller — there is no diff magic here.

    Args:
        session: The session to insert through.
        organization_id: The organization the action happened in.
        action: Short action identifier (e.g. ``"user.registered"``).
        actor_user_id: The acting user, if any.
        entity: The affected entity type, if any.
        entity_id: The affected entity id, if any.
        before: Entity state before the action (JSON-serializable dict).
        after: Entity state after the action (JSON-serializable dict).
        ip: The caller's IP address, if known.

    Returns:
        The persisted ``AuditLog`` row.
    """
    entry = AuditLog(
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        action=action,
        entity=entity,
        entity_id=entity_id,
        before_json=before,
        after_json=after,
        ip=ip,
    )
    session.add(entry)
    await session.flush()
    return entry


async def try_record_audit(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    action: str,
    actor_user_id: uuid.UUID | None = None,
    entity: str | None = None,
    entity_id: uuid.UUID | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    ip: str | None = None,
    log: Any = None,
) -> AuditLog | None:
    """Record an audit row, never breaking the caller's transaction.

    The insert runs inside a SAVEPOINT; on any failure the savepoint is
    rolled back, a structlog ``audit_write_failed`` event is emitted with
    action/entity/org identifiers ONLY (payloads may contain secrets), and
    ``None`` is returned.

    Args:
        session: The caller's session (its transaction survives failures).
        organization_id: The organization the action happened in.
        action: Short action identifier.
        actor_user_id: The acting user, if any.
        entity: The affected entity type, if any.
        entity_id: The affected entity id, if any.
        before: Entity state before the action.
        after: Entity state after the action.
        ip: The caller's IP address, if known.
        log: Logger override (defaults to the module structlog logger).

    Returns:
        The persisted ``AuditLog`` row, or ``None`` when the write failed.
    """
    audit_logger = log if log is not None else logger
    try:
        async with session.begin_nested():
            return await record_audit(
                session,
                organization_id=organization_id,
                action=action,
                actor_user_id=actor_user_id,
                entity=entity,
                entity_id=entity_id,
                before=before,
                after=after,
                ip=ip,
            )
    except Exception:  # noqa: BLE001 — audit failure must never break the business op
        audit_logger.warning(
            "audit_write_failed",
            action=action,
            entity=entity,
            organization_id=str(organization_id),
            entity_id=str(entity_id) if entity_id else None,
        )
        return None
