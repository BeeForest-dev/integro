"""Telegram trigger endpoint (C25) — public ingress guarded by the bot secret.

Mounted in ``create_app`` WITHOUT auth: trust comes from the
``X-Telegram-Bot-Api-Secret-Token`` header, which must equal the connection
secret (C18). The check runs ``isascii()`` BEFORE ``hmac.compare_digest``
(the C22 lesson: a non-ASCII header must be a 401, never a TypeError).
Unknown/inactive/secret-less connections answer the same uniform 404.

Dedupe is two-layered: the C22 idempotency index kills exact replays
(``telegram:{connection_id}:{update_id}``), and ``config["last_update_id"]``
rejects updates older than the last seen one — an old id never seen by this
connection must not create an event. Non-text updates are acknowledged with
``ignored: true`` and a structlog entry, without an event or idempotency row.
"""

import hmac
import uuid
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.db.engine import get_session
from app.models import Connection
from app.repositories.connections import read_secret
from app.repositories.org_scope import OrgScope
from app.services.events import store_event

router = APIRouter(tags=["telegram"])

logger = structlog.get_logger(__name__)

_SECRET_HEADER = "x-telegram-bot-api-secret-token"


def get_settings() -> Settings:
    """Per-request settings (env-backed); the secret is wired down explicitly."""
    return Settings()  # type: ignore[call-arg]


def _enqueue(event_id: str) -> None:
    """Dispatch the event to the worker pipeline (lazy Celery import)."""
    from app.workers.celery_app import app as celery_app

    celery_app.send_task(
        "app.workers.tasks.process_event",
        args=[event_id],
    )


def _not_found() -> AppError:
    """The single uniform 404 for unknown/inactive/secret-less connections."""
    return AppError("not found", status_code=404, title="Not Found")


def _unauthorized() -> AppError:
    return AppError("invalid secret token", status_code=401, title="Unauthorized")


def _extract_message(update: dict[str, Any]) -> dict[str, Any] | None:
    """Return the message dict when the update carries one, else None."""
    message = update.get("message")
    return message if isinstance(message, dict) else None


def _ignored(update_id: int, reason: str) -> dict[str, Any]:
    """Acknowledge an update without an event; log why it was ignored."""
    logger.info("telegram_update_ignored", update_id=update_id, reason=reason)
    return {"ok": True, "ignored": True}


@router.post("/hooks/telegram/{connection_id}", status_code=200)
async def receive_telegram_update(
    connection_id: uuid.UUID,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    """Verify, dedupe, normalize and store one Telegram update."""
    connection = await session.get(Connection, connection_id)
    if connection is None or connection.status != "active":
        raise _not_found()

    scope = OrgScope(session, connection.organization_id)
    secret = await read_secret(session, scope, connection.id, settings.SECRET_KEY)
    if not secret:
        raise _not_found()

    presented = request.headers.get(_SECRET_HEADER)
    if (
        presented is None
        or not presented.isascii()
        or not hmac.compare_digest(secret, presented)
    ):
        raise _unauthorized()

    try:
        update = await request.json()
    except Exception as exc:  # malformed JSON -> 400, never 500
        raise AppError(
            "body: must be a JSON object",
            status_code=400,
            title="Bad Request",
        ) from exc
    if not isinstance(update, dict) or not isinstance(update.get("update_id"), int):
        raise AppError(
            "body: update_id is required and must be an integer",
            status_code=400,
            title="Bad Request",
        )
    update_id = update["update_id"]

    config = connection.config or {}
    last_update_id = config.get("last_update_id")
    if isinstance(last_update_id, int) and update_id <= last_update_id:
        return _ignored(update_id, "older_than_last")

    message = _extract_message(update)
    if message is None:
        return _ignored(update_id, "no_message")
    text = message.get("text")
    if not isinstance(text, str):
        return _ignored(update_id, "non_text_message")
    chat = message.get("chat") or {}
    sender = message.get("from") or {}
    if not isinstance(message.get("message_id"), int) or not isinstance(
        chat.get("id"), int
    ):
        raise AppError(
            "body: message.chat.id and message.message_id are required",
            status_code=400,
            title="Bad Request",
        )

    event, created = await store_event(
        session,
        organization_id=connection.organization_id,
        connection_id=connection.id,
        event_type="telegram.message",
        payload={
            "update_id": update_id,
            "chat_id": chat["id"],
            "user_id": sender.get("id"),
            "text": text,
            "message_id": message["message_id"],
        },
        idempotency_key=f"telegram:{connection.id}:{update_id}",
    )
    config["last_update_id"] = update_id
    connection.config = config
    await session.commit()

    if created:
        _enqueue(str(event.id))
        return {"ok": True, "ignored": False}
    return {"ok": True, "ignored": True}
