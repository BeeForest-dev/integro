"""Tests for C10 models.organization + repositories.organizations.

These tests run against a REAL PostgreSQL — the DATABASE_URL environment
variable (docker compose postgres locally, the CI service container in the
pipeline). There are deliberately no skips: without a reachable database
these tests must fail loudly, not silently pass.
"""

import asyncio
import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import delete, inspect, select

from app.core.errors import AppError
from app.db.engine import create_engine, create_session_factory
from app.models import Organization
from app.repositories.organizations import create_organization

BACKEND_DIR = Path(__file__).resolve().parents[2]


def _database_url() -> str:
    """Return the real PostgreSQL DSN; fail loudly when it is not configured."""
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

    Every asyncio.run creates a new loop, and pooled asyncpg connections
    stay bound to the loop that opened them — so the engine must be created,
    used and disposed inside one coroutine.
    """

    def _run(scenario) -> None:
        async def _wrapped():
            engine = create_engine(_database_url())
            factory = create_session_factory(engine)
            try:
                async with factory() as session:
                    await session.execute(delete(Organization))
                    await session.commit()
                await scenario(factory)
            finally:
                await engine.dispose()

        asyncio.run(_wrapped())

    return _run


def _table_exists() -> bool:
    async def _check() -> bool:
        engine = create_engine(_database_url())
        try:
            async with engine.connect() as connection:
                tables = await connection.run_sync(
                    lambda conn: inspect(conn).get_table_names()
                )
                return "organizations" in tables
        finally:
            await engine.dispose()

    return asyncio.run(_check())


def test_migration_upgrade_downgrade_reupgrade():
    """upgrade head creates the table, downgrade base drops it, re-upgrade is clean."""
    command.downgrade(_alembic_cfg(), "base")
    assert not _table_exists()

    command.upgrade(_alembic_cfg(), "head")
    assert _table_exists()

    command.downgrade(_alembic_cfg(), "base")
    assert not _table_exists()

    command.upgrade(_alembic_cfg(), "head")
    assert _table_exists()


def test_create_organization_persists(run):
    """A created row lands in the real table: uuid id, plan default, created_at set."""
    async def _scenario(factory):
        async with factory() as session:
            organization = await create_organization(session, name="Acme", slug="acme")
            await session.commit()
            stored_id = organization.id
            assert isinstance(stored_id, uuid.UUID)
            assert organization.plan == "free"
            assert organization.created_at is not None

        async with factory() as session:
            stored = await session.scalar(select(Organization).where(Organization.id == stored_id))
            assert stored is not None
            assert stored.name == "Acme"
            assert stored.slug == "acme"
            assert stored.plan == "free"

    run(_scenario)


def test_duplicate_slug_raises_conflict(run):
    """A real unique violation on slug maps to AppError with status 409."""
    async def _scenario(factory):
        async with factory() as session:
            await create_organization(session, name="First", slug="taken")
            await session.commit()

        async with factory() as session:
            with pytest.raises(AppError) as exc_info:
                await create_organization(session, name="Second", slug="taken")
            assert exc_info.value.status_code == 409

    run(_scenario)


def test_slug_unique_index_exists():
    """The schema carries a unique index covering the slug column."""
    async def _scenario():
        engine = create_engine(_database_url())
        try:
            async with engine.connect() as connection:
                def _reflect(conn):
                    inspector = inspect(conn)
                    indexes = inspector.get_indexes("organizations")
                    return [
                        index
                        for index in indexes
                        if index.get("unique") and index.get("column_names") == ["slug"]
                    ]

                unique_slug_indexes = await connection.run_sync(_reflect)
        finally:
            await engine.dispose()
        assert unique_slug_indexes, "organizations.slug must have a unique index"

    asyncio.run(_scenario())
