"""IMAP mailbox poller (C26) — beat-driven polling, read-only.

Celery beat runs ``poll_mailboxes`` every 60 s. Each ACTIVE ``imap_mailbox``
connection is polled when its ``config.poll_every_seconds`` interval
(default 300) has elapsed since ``config.last_poll_at``. The beat tick is
the backoff mechanism: a timed-out poll simply leaves the status untouched
and tries again on the next tick. An auth failure persists
``status="auth_failed"`` — subsequent ticks skip the connection (the
column is a plain String; "auth_failed" is a new value, not a schema
change). Only the mailbox is read; nothing is ever flagged or deleted.
"""

import asyncio
import os
from datetime import UTC, datetime, timedelta

import structlog
from celery import shared_task  # type: ignore[import-untyped]
from sqlalchemy import select

from app.db.engine import create_engine, create_session_factory
from app.models import Connection
from app.repositories.connections import read_secret
from app.repositories.org_scope import OrgScope
from app.services.events import store_event
from app.services.imap import (
    ImapAuthError,
    ImapError,
    ImapTimeoutError,
    fetch_new_messages,
)

logger = structlog.get_logger(__name__)

DEFAULT_POLL_EVERY_SECONDS = 300
DEFAULT_FOLDER = "INBOX"


def _enqueue(event_id: str) -> None:
    """Dispatch the event to the worker pipeline (lazy Celery import)."""
    from app.workers.celery_app import app as celery_app

    celery_app.send_task(
        "app.workers.tasks.process_event",
        args=[event_id],
    )


def _due(connection: Connection, now: datetime) -> bool:
    """True when the poll interval since last_poll_at has elapsed (or never ran)."""
    config = connection.config or {}
    interval = config.get("poll_every_seconds", DEFAULT_POLL_EVERY_SECONDS)
    last_poll = config.get("last_poll_at")
    if not last_poll:
        return True
    last_poll_at = datetime.fromisoformat(last_poll)
    return now >= last_poll_at + timedelta(seconds=interval)


async def _poll_mailboxes() -> int:
    """Poll every due IMAP connection; returns the number of events created."""
    database_url = os.environ["DATABASE_URL"]
    secret = os.environ["SECRET_KEY"]
    engine = create_engine(database_url)
    factory = create_session_factory(engine)
    try:
        created_total = 0
        now = datetime.now(UTC)
        async with factory() as session:
            candidates = (
                await session.scalars(
                    select(Connection).where(
                        Connection.type == "imap_mailbox",
                        Connection.status == "active",
                    )
                )
            ).all()
            for connection in candidates:
                if not _due(connection, now):
                    continue
                config = dict(connection.config or {})
                scope = OrgScope(session, connection.organization_id)
                password = await read_secret(session, scope, connection.id, secret)
                if not password:
                    continue
                host = config["host"]
                port = int(config.get("port", 993))
                folder = config.get("folder", DEFAULT_FOLDER)
                last_uid = int(config.get("last_uid") or 0)

                try:
                    new_last_uid, messages = await asyncio.to_thread(
                        fetch_new_messages,
                        host,
                        port,
                        config["username"],
                        password,
                        folder,
                        last_uid,
                    )
                except ImapAuthError:
                    connection.status = "auth_failed"
                    await session.commit()
                    logger.warning(
                        "imap_auth_failed", connection_id=str(connection.id)
                    )
                    continue
                except ImapTimeoutError:
                    logger.warning(
                        "imap_poll_timeout", connection_id=str(connection.id)
                    )
                    continue
                except ImapError:
                    logger.warning(
                        "imap_poll_failed", connection_id=str(connection.id)
                    )
                    continue

                for message in messages:
                    event, created = await store_event(
                        session,
                        organization_id=connection.organization_id,
                        connection_id=connection.id,
                        event_type="imap.message",
                        payload=message,
                        idempotency_key=f"imap:{connection.id}:{message['uid']}",
                    )
                    if created:
                        created_total += 1
                        _enqueue(str(event.id))
                config["last_uid"] = new_last_uid
                config["last_poll_at"] = now.isoformat()
                connection.config = config
                await session.commit()
        return created_total
    finally:
        await engine.dispose()


@shared_task(name="app.workers.mail_poller.poll_mailboxes")
def poll_mailboxes() -> int:
    """Beat entry point: poll due IMAP mailboxes (called every 60 s)."""
    return asyncio.run(_poll_mailboxes())
