"""Tests for C18 models.connection + repositories.connections.

Real PostgreSQL via DATABASE_URL (compose postgres locally, CI service
container). No skips: without a reachable database these tests fail loudly.
"""

import asyncio
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import delete, inspect, text

from app.core.crypto import decrypt, encrypt
from app.db.engine import create_engine, create_session_factory
from app.models import SUPPORTED_TYPES, Connection, Organization
from app.repositories.connections import (
    create_connection,
    get_connection,
    list_connections,
    read_secret,
    to_api_dict,
)
from app.repositories.org_scope import OrgScope

BACKEND_DIR = Path(__file__).resolve().parents[2]
SECRET = "c18-test-secret"
WRONG_SECRET = "another-secret-entirely"


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


@pytest.fixture
def run():
    """Run a coroutine against a fresh engine bound to a single event loop.

    Tables are cleaned before AND after each scenario: a leftover
    connections row would break other suites' organization cleanup through
    the foreign key.
    """

    def _run(scenario) -> None:
        async def _wrapped():
            engine = create_engine(_database_url())
            factory = create_session_factory(engine)
            try:
                command.upgrade(_alembic_cfg(), "head")
                for model in (Connection, Organization):
                    async with factory() as session:
                        await session.execute(delete(model))
                        await session.commit()
                await scenario(factory)
                for model in (Connection, Organization):
                    async with factory() as session:
                        await session.execute(delete(model))
                        await session.commit()
            finally:
                await engine.dispose()

        asyncio.run(_wrapped())

    return _run


def _connections_table_exists() -> bool:
    async def _check() -> bool:
        engine = create_engine(_database_url())
        try:
            async with engine.connect() as connection:
                tables = await connection.run_sync(
                    lambda conn: inspect(conn).get_table_names()
                )
                return "connections" in tables
        finally:
            await engine.dispose()

    return asyncio.run(_check())


def test_migration_upgrade_downgrade_reupgrade():
    """upgrade head creates connections, downgrade base drops it, re-up is clean."""
    command.downgrade(_alembic_cfg(), "base")
    assert not _connections_table_exists()

    command.upgrade(_alembic_cfg(), "head")
    assert _connections_table_exists()

    command.downgrade(_alembic_cfg(), "base")
    assert not _connections_table_exists()

    command.upgrade(_alembic_cfg(), "head")
    assert _connections_table_exists()


def test_create_persists_jsonb_and_encrypts_secret_at_rest(run):
    """config round-trips as JSONB; the raw column holds a Fernet token."""
    async def _scenario(factory):
        async with factory() as session:
            organization = Organization(name="Org", slug="conn-org")
            session.add(organization)
            await session.commit()
            scope = OrgScope(session, organization.id)

            connection = await create_connection(
                session,
                scope,
                name="Inbox",
                connection_type="imap_mailbox",
                config={"host": "imap.example.com", "port": 993, "username": "user"},
                plaintext_secret="s3cret p4ssphrase",
                secret=SECRET,
            )
            await session.commit()
            connection_id = connection.id

            raw = (
                await session.execute(
                    text("SELECT config, secret_ciphertext FROM connections WHERE id = :id"),
                    {"id": connection_id},
                )
            ).one()
            raw_config, raw_ciphertext = raw
            expected_config = {"host": "imap.example.com", "port": 993, "username": "user"}
            assert raw_config == expected_config
            assert raw_ciphertext != "s3cret p4ssphrase"
            assert decrypt(raw_ciphertext, SECRET) == "s3cret p4ssphrase"

            stored = await get_connection(session, scope, connection_id)
            assert stored.config == expected_config
            assert stored.status == "active"

    run(_scenario)


def test_unknown_type_is_a_validation_error_with_the_supported_list(run):
    """create_connection rejects an unknown type, naming the supported types."""
    async def _scenario(factory):
        async with factory() as session:
            organization = Organization(name="Org", slug="type-org")
            session.add(organization)
            await session.commit()
            scope = OrgScope(session, organization.id)

            with pytest.raises(ValueError) as exc_info:
                await create_connection(
                    session, scope, name="Bad", connection_type="carrier_pigeon", secret=SECRET
                )
            message = str(exc_info.value)
            assert "carrier_pigeon" in message
            for supported in SUPPORTED_TYPES:
                assert supported in message

    run(_scenario)


def test_to_api_dict_never_leaks_secrets(run):
    """Serialization exposes has_secret only - no ciphertext, no plaintext."""
    async def _scenario(factory):
        async with factory() as session:
            organization = Organization(name="Org", slug="api-dict-org")
            session.add(organization)
            await session.commit()
            scope = OrgScope(session, organization.id)

            connection = await create_connection(
                session,
                scope,
                name="Hook",
                connection_type="webhook_in",
                plaintext_secret="shhh",
                secret=SECRET,
            )
            await session.flush()

            payload = to_api_dict(connection)
            assert payload["has_secret"] is True
            assert "secret_ciphertext" not in payload
            assert "shhh" not in str(payload)

            empty = await create_connection(
                session, scope, name="Plain", connection_type="http_api", secret=SECRET
            )
            await session.flush()
            assert to_api_dict(empty)["has_secret"] is False

    run(_scenario)


def test_list_and_get_are_scoped_between_organizations(run):
    """Org B cannot list or get org A's connection."""
    async def _scenario(factory):
        async with factory() as session:
            org_a = Organization(name="A", slug="scope-a")
            org_b = Organization(name="B", slug="scope-b")
            session.add_all([org_a, org_b])
            await session.commit()
            scope_a = OrgScope(session, org_a.id)
            scope_b = OrgScope(session, org_b.id)

            connection = await create_connection(
                session, scope_a, name="A hook", connection_type="webhook_in", secret=SECRET
            )
            await session.commit()
            connection_id = connection.id

            assert [c.id for c in await list_connections(session, scope_a)] == [connection_id]
            assert await list_connections(session, scope_b) == []
            assert await get_connection(session, scope_a, connection_id) is not None
            assert await get_connection(session, scope_b, connection_id) is None

    run(_scenario)


def test_read_secret_happy_path(run):
    """read_secret returns the stored plaintext for the right key."""
    async def _scenario(factory):
        async with factory() as session:
            organization = Organization(name="Org", slug="read-org")
            session.add(organization)
            await session.commit()
            scope = OrgScope(session, organization.id)

            connection = await create_connection(
                session,
                scope,
                name="Hook",
                connection_type="telegram",
                plaintext_secret="bot-token",
                secret=SECRET,
            )
            await session.commit()

            assert await read_secret(session, scope, connection.id, SECRET) == "bot-token"

    run(_scenario)


def test_read_secret_with_wrong_key_marks_secret_error_and_returns_none(run):
    """A CryptoError degrades the connection (status persisted) instead of raising."""
    async def _scenario(factory):
        async with factory() as session:
            organization = Organization(name="Org", slug="wrong-key-org")
            session.add(organization)
            await session.commit()
            scope = OrgScope(session, organization.id)

            connection = await create_connection(
                session,
                scope,
                name="Hook",
                connection_type="http_api",
                config={},
                plaintext_secret="encrypted-with-other-key",
                secret=WRONG_SECRET,  # stored under a DIFFERENT key than we read with
            )
            await session.commit()
            connection_id = connection.id

            # Reading with SECRET while the row was encrypted with WRONG_SECRET fails closed.
            assert await read_secret(session, scope, connection_id, SECRET) is None

            stored = await get_connection(session, scope, connection_id)
            assert stored.status == "secret_error"

            # Re-reading with the wrong key keeps failing the same way, without raising.
            assert await read_secret(session, scope, connection_id, SECRET) is None

    run(_scenario)


def test_read_secret_self_heals_after_good_decrypt(run):
    """A successful read on a secret_error row restores status active."""
    async def _scenario(factory):
        async with factory() as session:
            organization = Organization(name="Org", slug="heal-org")
            session.add(organization)
            await session.commit()
            scope = OrgScope(session, organization.id)

            connection = await create_connection(
                session,
                scope,
                name="Hook",
                connection_type="webhook_in",
                plaintext_secret="top secret",
                secret=SECRET,
            )
            await session.commit()
            connection_id = connection.id

            # Break the stored ciphertext so the next read marks secret_error.
            connection.secret_ciphertext = encrypt("different plaintext", WRONG_SECRET)
            await session.flush()

            assert await read_secret(session, scope, connection_id, SECRET) is None
            marked = await get_connection(session, scope, connection_id)
            assert marked.status == "secret_error"

            # Restore a valid ciphertext and read again: the row self-heals.
            marked.secret_ciphertext = encrypt("top secret", SECRET)
            await session.flush()
            assert await read_secret(session, scope, connection_id, SECRET) == "top secret"
            healed = await get_connection(session, scope, connection_id)
            assert healed.status == "active"

    run(_scenario)
