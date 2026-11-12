"""Tests for C22 api.webhooks — PG-backed, via httpx.ASGITransport.

ASGITransport does not run the lifespan; the engine is initialised per
request inside one event loop, exactly like the other api suites.
"""

import asyncio
import hashlib
import hmac as hmac_mod
import json
import os
import uuid
from pathlib import Path

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import delete, select

os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:1/0")
os.environ.setdefault("SECRET_KEY", "c22-test-secret")

from app.db import engine as engine_module
from app.db.engine import create_engine, create_session_factory
from app.main import create_app
from app.models import Connection, Event, Organization
from app.repositories.connections import create_connection
from app.repositories.org_scope import OrgScope

BACKEND_DIR = Path(__file__).resolve().parents[2]
SECRET = "c22-test-secret"
BODY = json.dumps({"amount": 100, "lead": {"email": "a@example.com"}}).encode("utf-8")


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set - these tests require a real PostgreSQL")
    return url


def _alembic_cfg() -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", _database_url())
    return cfg


def _sign(raw_body: bytes, secret: str) -> str:
    return hmac_mod.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()


@pytest.fixture(autouse=True)
def environment(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", _database_url())
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    monkeypatch.setenv("SECRET_KEY", SECRET)


@pytest.fixture(autouse=True)
def database():
    """Schema at head and empty tables per test."""
    command.upgrade(_alembic_cfg(), "head")
    asyncio.run(_clean_all())
    yield
    asyncio.run(_clean_all())


@pytest.fixture
def send_task_spy(monkeypatch):
    """Record enqueue calls without touching a broker.

    Celery 5.6's ``Celery.send_task`` ignores ``task_always_eager``
    (AlwaysEagerIgnored), so tests spy on the endpoint's enqueue seam and
    run the task body explicitly via ``apply`` where an execution result
    is asserted.
    """
    from app.api import webhooks

    sent: list[str] = []
    monkeypatch.setattr(webhooks, "_enqueue_process_event", sent.append)
    return sent


async def _clean_all():
    engine = create_engine(_database_url())
    factory = create_session_factory(engine)
    try:
        for model in (Event, Connection, Organization):
            async with factory() as session:
                await session.execute(delete(model))
                await session.commit()
    finally:
        await engine.dispose()


async def _seed_connection(status: str = "active", with_secret: bool = True):
    """Create an organization with one webhook_in connection; return ids."""
    engine = create_engine(_database_url())
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            organization = Organization(name="Org", slug=f"hook-{os.urandom(4).hex()}")
            session.add(organization)
            await session.commit()
            scope = OrgScope(session, organization.id)
            connection = await create_connection(
                session,
                scope,
                name="Hook",
                connection_type="webhook_in",
                plaintext_secret="hook-secret" if with_secret else None,
                secret=SECRET,
            )
            if status != "active":
                connection.status = status
            await session.commit()
            return organization.id, connection.id
    finally:
        await engine.dispose()


def _post(connection_id, raw_body=BODY, headers=None, signer_secret="hook-secret"):
    """One in-process request with a fresh engine inside a single loop."""

    async def _do():
        engine_module.init_engine(_database_url())
        try:
            transport = httpx.ASGITransport(app=create_app())
            all_headers = {"content-type": "application/json"}
            all_headers.update(headers or {})
            if signer_secret is not None:
                all_headers["X-Webhook-Signature"] = _sign(raw_body, signer_secret)
            base_url = "http://testserver"
            async with httpx.AsyncClient(transport=transport, base_url=base_url) as client:
                return await client.post(
                    f"/hooks/{connection_id}", content=raw_body, headers=all_headers
                )
        finally:
            await engine_module.dispose_engine()

    return asyncio.run(_do())


def _event_count():
    async def _count():
        engine = create_engine(_database_url())
        factory = create_session_factory(engine)
        try:
            async with factory() as session:
                return len((await session.scalars(select(Event))).all())
        finally:
            await engine.dispose()

    return asyncio.run(_count())


def test_happy_path_stores_event_and_enqueues_task(send_task_spy):
    """202 + stored row + the placeholder task returns the event id when run."""
    from app.workers.tasks import process_event

    _, connection_id = asyncio.run(_seed_connection())

    response = _post(connection_id)

    assert response.status_code == 202
    body = response.json()
    assert set(body) == {"event_id", "received_at", "duplicate"}
    assert body["duplicate"] is False
    assert _event_count() == 1
    assert send_task_spy == [body["event_id"]]
    eager = process_event.apply(args=[body["event_id"]])
    assert eager.result == body["event_id"]


def test_bad_signature_returns_401():
    """A signature computed with the wrong secret is rejected."""
    _, connection_id = asyncio.run(_seed_connection())

    response = _post(connection_id, signer_secret="wrong-secret")

    assert response.status_code == 401


def test_tampered_body_returns_401():
    """Body changed after signing -> the raw-body HMAC no longer matches."""
    _, connection_id = asyncio.run(_seed_connection())
    signed = _sign(BODY, "hook-secret")

    response = _post(
        connection_id,
        raw_body=BODY + b" ",
        headers={"X-Webhook-Signature": signed},
        signer_secret=None,
    )

    assert response.status_code == 401


def test_unknown_connection_returns_404():
    """A random connection id answers the uniform 404."""
    response = _post(uuid.uuid4())
    assert response.status_code == 404


def test_inactive_connection_returns_404():
    """A disabled (secret_error) connection answers the uniform 404."""
    _, connection_id = asyncio.run(_seed_connection(status="secret_error"))

    response = _post(connection_id)

    assert response.status_code == 404


def test_connection_without_secret_returns_404():
    """No stored secret -> nothing to verify against -> uniform 404."""
    _, connection_id = asyncio.run(_seed_connection(with_secret=False))

    response = _post(connection_id, signer_secret=None, headers={})

    assert response.status_code == 404


def test_malformed_json_returns_400_with_decoder_detail():
    """Undecodable JSON -> 400 carrying the decoder message and position."""
    _, connection_id = asyncio.run(_seed_connection())
    raw = b'{"amount": '

    response = _post(connection_id, raw_body=raw)

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "body:" in detail
    assert "line" in detail and "column" in detail


def test_json_array_body_returns_400():
    """A well-formed non-object JSON body -> 400."""
    _, connection_id = asyncio.run(_seed_connection())

    response = _post(connection_id, raw_body=b"[1, 2, 3]")

    assert response.status_code == 400
    assert "must be a JSON object" in response.json()["detail"]


def test_replayed_body_is_a_duplicate_without_second_enqueue(send_task_spy):
    """Same body twice -> duplicate:true, one row, the task is sent once."""
    _, connection_id = asyncio.run(_seed_connection())

    first = _post(connection_id)
    second = _post(connection_id)

    assert first.status_code == 202 and first.json()["duplicate"] is False
    assert second.status_code == 202 and second.json()["duplicate"] is True
    assert second.json()["event_id"] == first.json()["event_id"]
    assert _event_count() == 1
    assert len(send_task_spy) == 1


def test_idempotency_header_is_honored(send_task_spy):
    """Two different bodies under one X-Idempotency-Key dedupe to the first."""
    _, connection_id = asyncio.run(_seed_connection())
    headers = {"X-Idempotency-Key": "fixed-key-123"}

    first = _post(connection_id, headers=headers)
    second = _post(connection_id, raw_body=b'{"other": true}', headers=headers)

    assert first.json()["duplicate"] is False
    assert second.json()["duplicate"] is True
    assert second.json()["event_id"] == first.json()["event_id"]
    assert _event_count() == 1
    assert len(send_task_spy) == 1


def test_reserialized_body_with_reordered_keys_verifies(send_task_spy):
    """Signing is over raw bytes: a re-serialized body MUST verify when re-signed."""
    _, connection_id = asyncio.run(_seed_connection())
    reordered = json.dumps({"lead": {"email": "a@example.com"}, "amount": 100}).encode("utf-8")
    assert reordered != BODY

    response = _post(connection_id, raw_body=reordered)

    assert response.status_code == 202
    assert response.json()["duplicate"] is False
    assert len(send_task_spy) == 1


def test_eager_task_returns_event_id():
    """The placeholder process_event task runs eagerly and returns the event id."""
    from app.workers.tasks import process_event

    assert process_event("evt-123") == "evt-123"
