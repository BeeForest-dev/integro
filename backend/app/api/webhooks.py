"""Inbound webhook endpoint (C22) — public ingress guarded by HMAC.

The route is mounted WITHOUT auth: trust comes from the signature, which
is computed over the RAW request body bytes, so a re-serialized JSON with
reordered keys still verifies. The connection is resolved on the raw
session (the request cannot know the org yet); from then on the stored
organization drives scoping. Unknown/inactive/secret-less connections all
answer the same 404 to prevent existence probing.
"""

import hashlib
import hmac
import json
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.db.engine import get_session
from app.models import Connection
from app.repositories.connections import read_secret
from app.repositories.org_scope import OrgScope
from app.services.events import store_event

router = APIRouter(tags=["webhooks"])

_SIGNATURE_HEADER = "x-webhook-signature"
_IDEMPOTENCY_HEADER = "x-idempotency-key"


def get_settings() -> Settings:
    """Per-request settings (env-backed); the secret is wired down explicitly."""
    return Settings()  # type: ignore[call-arg]


def _signature(raw_body: bytes, secret: str) -> str:
    """hex(hmac-sha256(raw_body, secret)) — over the raw bytes, never re-serialized."""
    return hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()


def _not_found() -> AppError:
    """The single uniform 404 for unknown/inactive/secret-less connections."""
    return AppError("not found", status_code=404, title="Not Found")


def _unauthorized() -> AppError:
    return AppError("invalid signature", status_code=401, title="Unauthorized")


def _idempotency_key(request: Request, raw_body: bytes) -> str:
    """Caller-provided key, or the body hash so a replay dedupes naturally."""
    presented = request.headers.get(_IDEMPOTENCY_HEADER)
    if presented:
        return presented
    return hashlib.sha256(raw_body).hexdigest()


def _parse_body(raw_body: bytes) -> dict[str, Any]:
    """Parse the raw body as a JSON object, raising 400s with decoder details."""
    try:
        parsed = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise AppError(
            f"body: {exc.msg} (line {exc.lineno} column {exc.colno})",
            status_code=400,
            title="Bad Request",
        ) from exc
    if not isinstance(parsed, dict):
        raise AppError(
            "body: must be a JSON object",
            status_code=400,
            title="Bad Request",
        )
    return parsed


def _enqueue_process_event(event_id: str) -> None:
    """Dispatch the event to the worker pipeline.

    Imported lazily: the Celery app reads REDIS_URL at import time, which
    must not happen while merely importing the web module (tests, lint).
    """
    from app.workers.celery_app import app as celery_app

    celery_app.send_task(
        "app.workers.tasks.process_event",
        args=[event_id],
    )


@router.post("/hooks/{connection_id}", status_code=202)
async def receive_webhook(
    connection_id: uuid.UUID,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    """Verify, normalize, store and enqueue one inbound webhook event."""
    raw_body = await request.body()

    connection = await session.get(Connection, connection_id)
    if connection is None or connection.status != "active":
        raise _not_found()

    scope = OrgScope(session, connection.organization_id)
    secret = await read_secret(session, scope, connection.id, settings.SECRET_KEY)
    if not secret:
        raise _not_found()

    presented = request.headers.get(_SIGNATURE_HEADER)
    if (
        presented is None
        or not presented.isascii()
        or not hmac.compare_digest(_signature(raw_body, secret), presented)
    ):
        raise _unauthorized()

    payload = _parse_body(raw_body)
    event, created = await store_event(
        session,
        organization_id=connection.organization_id,
        connection_id=connection.id,
        event_type=connection.type,
        payload=payload,
        idempotency_key=_idempotency_key(request, raw_body),
    )
    await session.commit()

    if created:
        _enqueue_process_event(str(event.id))
    return {
        "event_id": str(event.id),
        "received_at": event.received_at.isoformat() if event.received_at else None,
        "duplicate": not created,
    }
