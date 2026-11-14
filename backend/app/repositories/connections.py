"""Connection persistence (C18) — OrgScope-first, secrets encrypted at rest.

Every read goes through :class:`OrgScope` (C12); the scope stamps new rows
with its organization id, so repository methods never accept an org id from
the caller. Secrets are Fernet-encrypted via C17 before they touch the
database, and never leave this module as plaintext except through
:func:`read_secret`.
"""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import CryptoError, decrypt, encrypt
from app.models import SUPPORTED_TYPES, Connection
from app.repositories.org_scope import OrgScope


def _validate_type(connection_type: str) -> None:
    """Reject an unknown connection type, naming the supported list."""
    if connection_type not in SUPPORTED_TYPES:
        supported = ", ".join(sorted(SUPPORTED_TYPES))
        raise ValueError(
            f"unknown connection type '{connection_type}' (supported: {supported})"
        )


def _validate_config(connection_type: str, config: dict[str, Any]) -> None:
    """Type-specific config requirements, enforced before any insert (C26)."""
    if connection_type != "imap_mailbox":
        return
    host = config.get("host")
    if not isinstance(host, str) or not host:
        raise ValueError("config.host: imap_mailbox requires a non-empty string")
    username = config.get("username")
    if not isinstance(username, str) or not username:
        raise ValueError("config.username: imap_mailbox requires a non-empty string")
    port = config.get("port")
    if port is not None and (isinstance(port, bool) or not isinstance(port, int)):
        raise ValueError("config.port: must be an integer when present")


async def create_connection(
    session: AsyncSession,
    scope: OrgScope,
    *,
    name: str,
    connection_type: str,
    config: dict[str, Any] | None = None,
    plaintext_secret: str | None = None,
    secret: str,
) -> Connection:
    """Persist a new connection for the scope's organization.

    The plaintext secret is encrypted at rest (C17) before the insert; the
    ciphertext is the only form that reaches the database.

    Args:
        session: The session to insert through.
        scope: The organization scope (C12) — its org id stamps the row.
        name: Human-readable connection name.
        connection_type: One of ``SUPPORTED_TYPES``.
        config: Connector-specific settings (defaults to ``{}``).
        plaintext_secret: Optional secret to encrypt and store.
        secret: The application secret for encryption (explicit parameter).

    Returns:
        The persisted ``Connection`` row.

    Raises:
        ValueError: If the type is not supported.
    """
    _validate_type(connection_type)
    _validate_config(connection_type, config or {})
    connection = Connection(
        organization_id=scope.organization_id,
        name=name,
        type=connection_type,
        config=config or {},
        secret_ciphertext=(
            encrypt(plaintext_secret, secret) if plaintext_secret is not None else None
        ),
    )
    session.add(connection)
    await session.flush()
    await session.refresh(connection)
    return connection


async def list_connections(session: AsyncSession, scope: OrgScope) -> list[Connection]:
    """Return all connections of the scope's organization."""
    return await scope.all(scope.query(Connection))


async def get_connection(
    session: AsyncSession, scope: OrgScope, connection_id: uuid.UUID
) -> Connection | None:
    """Fetch one connection by id, only inside the scope's organization."""
    return await scope.get(Connection, connection_id)


async def read_secret(
    session: AsyncSession,
    scope: OrgScope,
    connection_id: uuid.UUID,
    secret: str,
) -> str | None:
    """Decrypt a connection's stored secret.

    A decryption failure marks the connection ``secret_error`` (persisted)
    and returns ``None`` — it never raises, so a wrong key degrades the
    connection instead of crashing the request. A successful read on a
    ``secret_error`` row self-heals the status back to ``active``.

    Args:
        session: The session to work in.
        scope: The organization scope (C12).
        connection_id: The connection to read.
        secret: The application secret the ciphertext was encrypted with.

    Returns:
        The plaintext secret, or ``None`` when the row is missing, has no
        stored secret, or decryption failed.
    """
    connection = await get_connection(session, scope, connection_id)
    if connection is None or not connection.secret_ciphertext:
        return None
    try:
        plaintext = decrypt(connection.secret_ciphertext, secret)
    except CryptoError:
        connection.status = "secret_error"
        await session.flush()
        return None
    if connection.status == "secret_error":
        connection.status = "active"
        await session.flush()
    return plaintext


def to_api_dict(connection: Connection) -> dict[str, Any]:
    """Serialize a connection for API responses.

    Exposes only whether a secret exists — never the ciphertext, never the
    plaintext.
    """
    return {
        "id": str(connection.id),
        "organization_id": str(connection.organization_id),
        "name": connection.name,
        "type": connection.type,
        "config": connection.config,
        "has_secret": connection.secret_ciphertext is not None,
        "status": connection.status,
        "created_at": connection.created_at.isoformat() if connection.created_at else None,
    }
