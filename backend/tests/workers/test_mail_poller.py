"""Tests for C26 services.imap + workers.mail_poller.

PG-backed against the real database; IMAP is served by a threaded fake
speaking just enough protocol (LOGIN/SELECT/UID SEARCH/UID FETCH/LOGOUT).
No external mailbox, no new dependencies.
"""

import asyncio
import contextlib
import os
import re
import socket
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import delete, select

from app.core.logging import setup_logging
from app.db.engine import create_engine, create_session_factory
from app.models import Connection, Event, Organization
from app.repositories.connections import create_connection
from app.repositories.org_scope import OrgScope
from app.workers import mail_poller

BACKEND_DIR = Path(__file__).resolve().parents[2]
SECRET = "c26-test-secret"
USER = "box@example.com"
PASSWORD = "mailbox-pw"


def _raw(
    subject: str, body: str, message_id: str, date: str, sender: str = "alice@example.com"
) -> bytes:
    return (
        f"From: {sender}\r\n"
        f"To: {USER}\r\n"
        f"Subject: {subject}\r\n"
        f"Message-ID: {message_id}\r\n"
        f"Date: {date}\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        "MIME-Version: 1.0\r\n"
        "\r\n"
        f"{body}"
    ).encode()


MSG_101 = _raw("Lead A", "Hello lead A", "<a@example.com>", "Sat, 14 Nov 2026 09:00:00 +0000")
MSG_102 = _raw("Lead B", "Hello lead B", "<b@example.com>", "Sat, 14 Nov 2026 09:30:00 +0000")
MSG_103 = _raw("Lead C", "Hello lead C", "<c@example.com>", "Sat, 14 Nov 2026 10:00:00 +0000")


class FakeImapServer:
    """Scripted fake IMAP server; counts connections/logins/selects."""

    def __init__(self, mode: str = "ok", messages: dict | None = None):
        self.mode = mode  # ok | reject_login | hang_on_search | break_mid_session
        self.messages = dict(messages or {})
        self.connections = 0
        self.logins = 0
        self.selects = 0
        self._lock = threading.Lock()
        self._listener = socket.socket()
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(8)
        self.port = self._listener.getsockname()[1]
        threading.Thread(target=self._accept_loop, daemon=True).start()

    def close(self):
        with contextlib.suppress(OSError):
            self._listener.close()

    def _accept_loop(self):
        while True:
            try:
                conn, _ = self._listener.accept()
            except OSError:
                return
            with self._lock:
                self.connections += 1
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn: socket.socket):
        stream = conn.makefile("rwb")
        try:
            stream.write(b"* OK fake imap ready\r\n")
            stream.flush()
            logged_in = False
            while True:
                line = stream.readline()
                if not line:
                    return
                parts = line.decode(errors="replace").split()
                if len(parts) < 2:
                    continue
                tag, cmd = parts[0], parts[1].upper()
                if cmd == "LOGIN":
                    with self._lock:
                        self.logins += 1
                    user = parts[2].strip('"') if len(parts) > 2 else ""
                    password = parts[3].strip('"') if len(parts) > 3 else ""
                    if self.mode == "reject_login" or user != USER or password != PASSWORD:
                        stream.write(f"{tag} NO LOGIN rejected\r\n".encode())
                    else:
                        logged_in = True
                        stream.write(f"{tag} OK LOGIN completed\r\n".encode())
                    stream.flush()
                elif cmd in ("SELECT", "EXAMINE") and logged_in:
                    with self._lock:
                        self.selects += 1
                    stream.write(b"* 5 EXISTS\r\n")
                    ok_word = "READ-ONLY" if cmd == "EXAMINE" else "READ-WRITE"
                    stream.write(f"{tag} OK [{ok_word}] {cmd} completed\r\n".encode())
                    stream.flush()
                    if self.mode == "break_mid_session":
                        time.sleep(0.05)
                        return  # abrupt close mid-session
                elif cmd == "UID" and len(parts) > 2 and parts[2].upper() == "SEARCH":
                    if self.mode == "hang_on_search":
                        time.sleep(30)
                        return
                    match = re.search(r"(\d+):\*", line.decode(errors="replace"))
                    start = int(match.group(1)) if match else 1
                    uids = sorted(uid for uid in self.messages if uid >= start)
                    stream.write(
                        ("* SEARCH" + "".join(f" {uid}" for uid in uids) + "\r\n").encode()
                    )
                    stream.write(f"{tag} OK SEARCH completed\r\n".encode())
                    stream.flush()
                elif cmd == "UID" and len(parts) > 2 and parts[2].upper() == "FETCH":
                    uids = [int(token) for token in parts[3:] if token.isdigit()]
                    for uid in uids:
                        raw = self.messages[uid]
                        stream.write(f"* {uid} FETCH (RFC822 {{{len(raw)}}}\r\n".encode())
                        stream.write(raw + b")\r\n")
                    stream.write(f"{tag} OK FETCH completed\r\n".encode())
                    stream.flush()
                elif cmd == "LOGOUT":
                    stream.write(b"* BYE fake imap signing off\r\n")
                    stream.write(f"{tag} OK LOGOUT completed\r\n".encode())
                    stream.flush()
                    return
                elif cmd == "CAPABILITY":
                    stream.write(f"* CAPABILITY IMAP4rev1\r\n{tag} OK CAPABILITY\r\n".encode())
                    stream.flush()
                else:
                    stream.write(f"{tag} BAD unknown command\r\n".encode())
                    stream.flush()
        except OSError:
            return
        finally:
            with contextlib.suppress(OSError):
                conn.close()


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
    monkeypatch.setenv("SECRET_KEY", SECRET)


@pytest.fixture(autouse=True)
def database(monkeypatch):
    """Schema at head, empty tables, spied enqueue seam, per test."""
    command.upgrade(_alembic_cfg(), "head")
    asyncio.run(_clean_all())
    sent: list[str] = []
    monkeypatch.setattr(mail_poller, "_enqueue", sent.append)
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


async def _seed_imap_connection(server_port: int, **config_overrides):
    """Create an organization with one imap_mailbox connection aimed at the fake server."""
    config = {
        "host": "127.0.0.1",
        "port": server_port,
        "username": USER,
        "poll_every_seconds": 1,
    }
    config.update(config_overrides)
    engine = create_engine(_database_url())
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            organization = Organization(name="Org", slug=f"imap-{os.urandom(4).hex()}")
            session.add(organization)
            await session.commit()
            scope = OrgScope(session, organization.id)
            connection = await create_connection(
                session,
                scope,
                name="Mailbox",
                connection_type="imap_mailbox",
                config=config,
                plaintext_secret=PASSWORD,
                secret=SECRET,
            )
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


async def _backdate_last_poll(connection_id):
    """Force the next tick to consider the connection due."""
    engine = create_engine(_database_url())
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            connection = await session.get(Connection, connection_id)
            config = dict(connection.config or {})
            config["last_poll_at"] = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
            connection.config = config
            await session.commit()
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


def test_happy_path_creates_events_and_cursor(database):
    """Two waiting messages -> two fully-normalized events, cursor recorded."""
    server = FakeImapServer(messages={101: MSG_101, 102: MSG_102})
    try:
        _, connection_id = asyncio.run(_seed_imap_connection(server.port))

        created = asyncio.run(mail_poller._poll_mailboxes())

        assert created == 2
        events = asyncio.run(_events())
        assert len(events) == 2
        by_uid = {event.payload["uid"]: event for event in events}
        first = by_uid[101]
        assert first.type == "imap.message"
        assert first.payload["message_id"] == "<a@example.com>"
        assert first.payload["from"] == "alice@example.com"
        assert first.payload["subject"] == "Lead A"
        assert first.payload["date"] == "Sat, 14 Nov 2026 09:00:00 +0000"
        assert first.payload["body_text"] == "Hello lead A"
        assert {e.idempotency_key for e in events} == {
            f"imap:{connection_id}:101",
            f"imap:{connection_id}:102",
        }
        assert len(database) == 2
        connection = asyncio.run(_read_connection(connection_id))
        assert connection.config["last_uid"] == 102
        assert "last_poll_at" in connection.config
        assert connection.status == "active"
    finally:
        server.close()


def test_second_poll_creates_nothing(database):
    """A re-poll with no new mail stores nothing new."""
    server = FakeImapServer(messages={101: MSG_101, 102: MSG_102})
    try:
        asyncio.run(_seed_imap_connection(server.port))
        assert asyncio.run(mail_poller._poll_mailboxes()) == 2

        created = asyncio.run(mail_poller._poll_mailboxes())

        assert created == 0
        assert len(asyncio.run(_events())) == 2
    finally:
        server.close()


def test_new_message_later_creates_one_event(database):
    """A message arriving between polls (uid 103) yields exactly one event."""
    server = FakeImapServer(messages={101: MSG_101, 102: MSG_102})
    try:
        _, connection_id = asyncio.run(_seed_imap_connection(server.port))
        assert asyncio.run(mail_poller._poll_mailboxes()) == 2

        server.messages[103] = MSG_103
        asyncio.run(_backdate_last_poll(connection_id))
        created = asyncio.run(mail_poller._poll_mailboxes())

        assert created == 1
        events = asyncio.run(_events())
        assert len(events) == 3
        assert f"imap:{connection_id}:103" in {e.idempotency_key for e in events}
        assert asyncio.run(_read_connection(connection_id)).config["last_uid"] == 103
    finally:
        server.close()


def test_rejected_login_marks_auth_failed_and_skips_later_ticks(database):
    """LOGIN rejected -> auth_failed persists, no events, no retry storm."""
    server = FakeImapServer(mode="reject_login", messages={101: MSG_101})
    try:
        _, connection_id = asyncio.run(_seed_imap_connection(server.port))

        assert asyncio.run(mail_poller._poll_mailboxes()) == 0

        connection = asyncio.run(_read_connection(connection_id))
        assert connection.status == "auth_failed"
        assert asyncio.run(_events()) == []
        logins_after_first = server.logins

        assert asyncio.run(mail_poller._poll_mailboxes()) == 0
        assert server.logins == logins_after_first  # skipped, not re-attempted
    finally:
        server.close()


def test_timeout_leaves_status_active(database, monkeypatch, capsys):
    """A server that accepts then hangs -> timeout log, status stays active."""
    from app.services import imap

    monkeypatch.setattr(imap, "IMAP_TIMEOUT_SECONDS", 0.5)
    setup_logging()
    server = FakeImapServer(mode="hang_on_search", messages={101: MSG_101})
    try:
        _, connection_id = asyncio.run(_seed_imap_connection(server.port))

        assert asyncio.run(mail_poller._poll_mailboxes()) == 0

        assert asyncio.run(_read_connection(connection_id)).status == "active"
        assert asyncio.run(_events()) == []
        assert "imap_poll_timeout" in capsys.readouterr().out
    finally:
        server.close()


def test_mid_session_break_reconnects_once_then_gives_up(database, capsys):
    """A server closing mid-session -> ONE reconnect, imap_poll_failed, active."""
    setup_logging()
    server = FakeImapServer(mode="break_mid_session", messages={101: MSG_101})
    try:
        _, connection_id = asyncio.run(_seed_imap_connection(server.port))

        assert asyncio.run(mail_poller._poll_mailboxes()) == 0

        assert server.connections == 2  # initial attempt + exactly one reconnect
        assert asyncio.run(_read_connection(connection_id)).status == "active"
        assert asyncio.run(_events()) == []
        assert "imap_poll_failed" in capsys.readouterr().out
    finally:
        server.close()


def test_due_gate_skips_recently_polled_connection(database):
    """poll_every_seconds not elapsed -> the server is never contacted."""
    server = FakeImapServer(messages={101: MSG_101})
    try:
        fresh = (datetime.now(UTC)).isoformat()
        asyncio.run(_seed_imap_connection(server.port, last_poll_at=fresh))

        assert asyncio.run(mail_poller._poll_mailboxes()) == 0

        assert server.logins == 0
        assert asyncio.run(_events()) == []
    finally:
        server.close()


def test_imap_config_validation_names_the_field():
    """imap_mailbox configs are validated at create time (C26)."""

    async def _try(config):
        engine = create_engine(_database_url())
        factory = create_session_factory(engine)
        try:
            async with factory() as session:
                organization = Organization(name="Org", slug=f"cfg-{os.urandom(4).hex()}")
                session.add(organization)
                await session.commit()
                scope = OrgScope(session, organization.id)
                with pytest.raises(ValueError) as exc_info:
                    await create_connection(
                        session,
                        scope,
                        name="Bad",
                        connection_type="imap_mailbox",
                        config=config,
                        secret=SECRET,
                    )
                return str(exc_info.value)
        finally:
            await engine.dispose()

    assert "config.host" in asyncio.run(_try({"username": USER}))
    assert "config.username" in asyncio.run(_try({"host": "127.0.0.1"}))
    assert "config.port" in asyncio.run(
        _try({"host": "127.0.0.1", "username": USER, "port": "993"})
    )


def test_body_truncated_at_20000_chars(database):
    """Long text/plain bodies are truncated to the documented ceiling."""
    long_body = "x" * 25000
    big = _raw("Big", long_body, "<big@example.com>", "Sat, 14 Nov 2026 11:00:00 +0000")
    server = FakeImapServer(messages={110: big})
    try:
        asyncio.run(_seed_imap_connection(server.port))

        assert asyncio.run(mail_poller._poll_mailboxes()) == 1

        event = asyncio.run(_events())[0]
        assert len(event.payload["body_text"]) == 20000
    finally:
        server.close()
