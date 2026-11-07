"""Tests for C19 services.audit (full shape + failure isolation).

Real PostgreSQL via DATABASE_URL. No skips: without a reachable database
these tests fail loudly.
"""

import asyncio
import json
import logging
import os
import uuid
from pathlib import Path

import pytest
import structlog
from alembic import command
from alembic.config import Config
from sqlalchemy import delete, inspect, select

from app.core.logging import setup_logging
from app.db.engine import create_engine, create_session_factory
from app.models import AuditLog, Organization, User
from app.services.audit import record_audit, try_record_audit

BACKEND_DIR = Path(__file__).resolve().parents[2]

FULL = dict(
    action="connection.updated",
    entity="connection",
    entity_id=uuid.uuid4(),
    before={"name": "old"},
    after={"name": "new", "secret": "do-not-log-me"},
    ip="203.0.113.7",
)


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
def reset_logging_state():
    structlog.contextvars.clear_contextvars()
    yield
    structlog.contextvars.clear_contextvars()
    structlog.reset_defaults()
    logging.getLogger().handlers.clear()


@pytest.fixture
def run():
    """Run a coroutine against a fresh engine bound to a single event loop.

    Tables are cleaned before AND after: leftover audit rows would break
    other suites' organization cleanup through the foreign keys.
    """

    def _run(scenario) -> None:
        async def _wrapped():
            engine = create_engine(_database_url())
            factory = create_session_factory(engine)
            try:
                command.upgrade(_alembic_cfg(), "head")
                for model in (AuditLog, User, Organization):
                    async with factory() as session:
                        await session.execute(delete(model))
                        await session.commit()
                await scenario(factory)
                for model in (AuditLog, User, Organization):
                    async with factory() as session:
                        await session.execute(delete(model))
                        await session.commit()
            finally:
                await engine.dispose()

        asyncio.run(_wrapped())

    return _run


def _audit_columns() -> set[str]:
    async def _read() -> set[str]:
        engine = create_engine(_database_url())
        try:
            async with engine.connect() as connection:
                return set(
                    await connection.run_sync(
                        lambda conn: {c["name"] for c in inspect(conn).get_columns("audit_log")}
                    )
                )
        finally:
            await engine.dispose()

    return asyncio.run(_read())


def test_migration_0008_reflection_and_cycle():
    """0008 adds the five columns; the upgrade/downgrade/re-upgrade cycle is clean."""
    expected = {"entity", "entity_id", "before_json", "after_json", "ip"}
    command.upgrade(_alembic_cfg(), "head")
    assert expected.issubset(_audit_columns())

    command.downgrade(_alembic_cfg(), "base")
    command.upgrade(_alembic_cfg(), "head")
    assert expected.issubset(_audit_columns())


def test_record_audit_full_field_roundtrip(run):
    """All C19 fields persist, JSONB diffs included."""
    async def _scenario(factory):
        async with factory() as session:
            organization = Organization(name="Org", slug="audit-org")
            actor = User(email="auditor@example.com")
            session.add_all([organization, actor])
            await session.commit()

            entry = await record_audit(
                session,
                organization_id=organization.id,
                actor_user_id=actor.id,
                **FULL,
            )
            await session.commit()
            entry_id = entry.id

        async with factory() as session:
            stored = await session.scalar(select(AuditLog).where(AuditLog.id == entry_id))
            assert stored.action == "connection.updated"
            assert stored.entity == "connection"
            assert stored.entity_id == FULL["entity_id"]
            assert stored.before_json == {"name": "old"}
            assert stored.after_json == {"name": "new", "secret": "do-not-log-me"}
            assert stored.ip == "203.0.113.7"
            assert stored.actor_user_id is not None

    run(_scenario)


def test_try_record_audit_happy_path(run):
    """The wrapper persists the row on success."""
    async def _scenario(factory):
        async with factory() as session:
            organization = Organization(name="Org", slug="try-happy-org")
            session.add(organization)
            await session.commit()

            entry = await try_record_audit(
                session, organization_id=organization.id, action="user.login", ip="10.0.0.1"
            )
            assert entry is not None
            await session.commit()

            stored = await session.scalar(select(AuditLog).where(AuditLog.id == entry.id))
            assert stored.action == "user.login"
            assert stored.ip == "10.0.0.1"

    run(_scenario)


def test_try_record_audit_failure_isolates_the_caller(run, capsys):
    """A broken audit write -> None, caller's insert still commits, log carries no payload."""
    setup_logging()

    async def _scenario(factory):
        async with factory() as session:
            organization = Organization(name="Org", slug="try-fail-org")
            session.add(organization)
            await session.commit()

            # Force the audit insert to die on the organization FK.
            bogus_org = uuid.uuid4()
            entry = await try_record_audit(
                session,
                organization_id=bogus_org,
                action="connection.updated",
                entity="connection",
                entity_id=FULL["entity_id"],
                before=FULL["before"],
                after=FULL["after"],
            )
            assert entry is None

            # The caller's own insert in the same transaction still commits.
            probe = User(email="probe@example.com")
            session.add(probe)
            await session.commit()
            stored = await session.scalar(select(User).where(User.email == "probe@example.com"))
            assert stored is not None
            assert (await session.scalars(select(AuditLog))).all() == []

    run(_scenario)

    lines = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if line.strip().startswith("{")
    ]
    failures = [record for record in lines if record.get("event") == "audit_write_failed"]
    assert len(failures) == 1
    failure = failures[0]
    assert failure["action"] == "connection.updated"
    assert failure["entity"] == "connection"
    assert "payload" not in json.dumps(failure)
    assert "do-not-log-me" not in json.dumps(failure)
    for key in ("before", "after", "before_json", "after_json"):
        assert key not in failure
