"""Tests for C25 api.telegram_webhook — PG-backed, no real Telegram.

The enqueue seam is spied like in the C22/C24 suites; the structlog output
for ignored updates is captured via the C02 setup.
"""

import asyncio
import json
import os
import uuid
from pathlib import Path

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import delete, select

from app.api import telegram_webhook
from app.core.logging import setup_logging
from app.db import engine as engine_module
from app.db.engine import create_engine, create_session_factory
from app.main import create_app
from app.models import Connection, Event, Organization
from app.repositories.connections import create_connection
from app.repositories.org_scope import OrgScope

BACKEND_DIR = Path(__file__).resolve().parents[2]
SECRET = "c25-test-secret"

TEXT_UPDATE = {
    "update_id": 5,
    "message": {
        "message_id": 42,
        "from": {"id": 1001},
        "chat": {"id": 2002},
        "text": "hello bot",
    },
}


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


@pytest.fixture(autouse=True)
def environment(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", _database_url())
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    monkeypatch.setenv("SECRET_KEY", SECRET)


@pytest.fixture(autouse=True)
def database(monkeypatch):
    """Schema at head, empty tables, spied enqueue seam, captured logs."""
    command.upgrade(_alembic_cfg(), "head")
    asyncio.run(_clean_all())
    sent: list[str] = []
    monkeypatch.setattr(telegram_webhook, "_enqueue", sent.append)
    yield sent
    asyncio.run(_clean_all())


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


async def _seed_connection(connection_type: str = "telegram", status: str = "active"):
    """Create an organization with one telegram connection; return ids."""
    engine = create_engine(_database_url())
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            organization = Organization(name="Org", slug=f"tg-{os.urandom(4).hex()}")
            session.add(organization)
            await session.commit()
            scope = OrgScope(session, organization.id)
            connection = await create_connection(
                session,
                scope,
                name="Bot",
                connection_type=connection_type,
                plaintext_secret="tg-secret",
                secret=SECRET,
            )
            if status != "active":
                connection.status = status
            await session.commit()
            return organization.id, connection.id
    finally:
        await engine.dispose()


async def _read_connection(connection_id):
    engine = create_engine(_database_url())
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            return await session.get(Connection, connection_id)
    finally:
        await engine.dispose()


async def _events():
    engine = create_engine(_database_url())
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            return (await session.scalars(select(Event))).all()
    finally:
        await engine.dispose()


def _post(connection_id, update=None, secret_header="tg-secret"):
    """One in-process request with a fresh engine inside a single loop."""

    async def _do():
        engine_module.init_engine(_database_url())
        try:
            transport = httpx.ASGITransport(app=create_app())
            headers = {"Content-Type": "application/json"}
            if secret_header is not None:
                headers["X-Telegram-Bot-Api-Secret-Token"] = secret_header
            base_url = "http://testserver"
            async with httpx.AsyncClient(transport=transport, base_url=base_url) as client:
                return await client.post(
                    f"/hooks/telegram/{connection_id}",
                    content=json.dumps(update if update is not None else TEXT_UPDATE).encode(),
                    headers=headers,
                )
        finally:
            await engine_module.dispose_engine()

    return asyncio.run(_do())


def test_happy_text_message_stores_event(database):
    """A text update -> event row with all payload fields, enqueue, last_update_id."""
    _, connection_id = asyncio.run(_seed_connection())

    response = _post(connection_id)

    assert response.status_code == 200
    assert response.json() == {"ok": True, "ignored": False}
    events = asyncio.run(_events())
    assert len(events) == 1
    event = events[0]
    assert event.type == "telegram.message"
    assert event.payload == {
        "update_id": 5,
        "chat_id": 2002,
        "user_id": 1001,
        "text": "hello bot",
        "message_id": 42,
    }
    assert database == [str(event.id)]
    connection = asyncio.run(_read_connection(connection_id))
    assert connection.config["last_update_id"] == 5


@pytest.mark.parametrize(
    "secret_header",
    ["wrong-secret", None],
)
def test_wrong_or_missing_secret_returns_401(database, secret_header):
    """A bad or absent secret token -> 401."""
    _, connection_id = asyncio.run(_seed_connection())

    response = _post(connection_id, secret_header=secret_header)

    assert response.status_code == 401


def _post_raw(connection_id, headers, update=None):
    """Raw ASGI call for headers httpx refuses to send (non-ASCII bytes)."""

    async def _do():
        engine_module.init_engine(_database_url())
        try:
            app = create_app()
            body = json.dumps(update if update is not None else TEXT_UPDATE).encode()
            scope = {
                "type": "http",
                "method": "POST",
                "path": f"/hooks/telegram/{connection_id}",
                "raw_path": f"/hooks/telegram/{connection_id}".encode("ascii"),
                "query_string": b"",
                "headers": [(b"content-type", b"application/json"), *headers],
                "scheme": "http",
                "server": ("testserver", 80),
            }
            messages: list[dict] = []

            async def receive():
                return {"type": "http.request", "body": body, "more_body": False}

            async def send(message):
                messages.append(message)

            await app(scope, receive, send)
            status = next(
                m["status"] for m in messages if m["type"] == "http.response.start"
            )
            payload = b"".join(
                m.get("body", b"") for m in messages if m["type"] == "http.response.body"
            )
            return status, payload
        finally:
            await engine_module.dispose_engine()

    return asyncio.run(_do())


def test_non_ascii_secret_returns_401(database):
    """A non-ASCII secret header -> 401 (never a compare_digest TypeError)."""
    _, connection_id = asyncio.run(_seed_connection())

    status, _ = _post_raw(
        connection_id,
        headers=[(b"x-telegram-bot-api-secret-token", b"\xe9\xe9\xe9\xe9")],
    )

    assert status == 401


def test_unknown_connection_returns_404(database):
    response = _post(uuid.uuid4())
    assert response.status_code == 404


def test_inactive_connection_returns_404(database):
    _, connection_id = asyncio.run(_seed_connection(status="secret_error"))

    response = _post(connection_id)

    assert response.status_code == 404


def test_exact_replay_is_ignored_with_one_row(database):
    """The same update twice -> ignored:true, one event row, one enqueue."""
    _, connection_id = asyncio.run(_seed_connection())

    first = _post(connection_id)
    second = _post(connection_id)

    assert first.json() == {"ok": True, "ignored": False}
    assert second.json() == {"ok": True, "ignored": True}
    assert len(asyncio.run(_events())) == 1
    assert len(database) == 1


def test_older_update_id_is_ignored_without_event(database):
    """update 5 accepted, then update 3 -> ignored, no second event."""
    _, connection_id = asyncio.run(_seed_connection())
    assert _post(connection_id).json()["ignored"] is False

    old = {**TEXT_UPDATE, "update_id": 3, "message": {**TEXT_UPDATE["message"], "message_id": 1}}
    response = _post(connection_id, update=old)

    assert response.status_code == 200
    assert response.json() == {"ok": True, "ignored": True}
    assert len(asyncio.run(_events())) == 1
    assert len(database) == 1


def test_photo_update_is_ignored_with_log(database, capsys):
    """A non-text message -> ignored:true, a telegram_update_ignored log, no row."""
    setup_logging()
    _, connection_id = asyncio.run(_seed_connection())
    photo = {
        "update_id": 7,
        "message": {"message_id": 9, "from": {"id": 1}, "chat": {"id": 2}, "photo": []},
    }

    response = _post(connection_id, update=photo)

    assert response.json() == {"ok": True, "ignored": True}
    assert asyncio.run(_events()) == []
    out = capsys.readouterr().out
    assert "telegram_update_ignored" in out
    assert "non_text_message" in out


def test_bare_callback_query_is_ignored_with_log(database, capsys):
    """An update without a message -> ignored with a log entry, no row."""
    setup_logging()
    _, connection_id = asyncio.run(_seed_connection())
    callback = {"update_id": 8, "callback_query": {"id": "abc"}}

    response = _post(connection_id, update=callback)

    assert response.json() == {"ok": True, "ignored": True}
    assert asyncio.run(_events()) == []
    out = capsys.readouterr().out
    assert "telegram_update_ignored" in out
    assert "no_message" in out


def test_enqueue_count_stays_one_through_replays_and_ignores(database):
    """Mixed valid/invalid traffic keeps exactly one enqueue and one row."""
    _, connection_id = asyncio.run(_seed_connection())
    assert _post(connection_id).json()["ignored"] is False
    _post(connection_id)  # exact replay
    old = {**TEXT_UPDATE, "update_id": 2, "message": {**TEXT_UPDATE["message"], "message_id": 3}}
    _post(connection_id, update=old)  # older than last
    _post(connection_id, secret_header="bad")  # unauthorized
    photo = {"update_id": 9, "message": {"message_id": 1, "chat": {"id": 2}, "photo": []}}
    _post(connection_id, update=photo)  # non-text

    assert len(asyncio.run(_events())) == 1
    assert len(database) == 1
