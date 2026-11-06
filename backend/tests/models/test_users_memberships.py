"""Tests for C11 models.user + models.membership.

Real PostgreSQL via DATABASE_URL (compose postgres locally, CI service
container). No skips: without a reachable database these tests fail loudly.
"""

import asyncio
import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import delete, inspect, select

from app.db.engine import create_engine, create_session_factory
from app.models import Membership, MembershipRole, Organization, User

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

    Pooled asyncpg connections stay bound to the loop that opened them, so
    the engine must be created, used and disposed inside one coroutine.
    """

    def _run(scenario) -> None:
        async def _wrapped():
            engine = create_engine(_database_url())
            factory = create_session_factory(engine)
            try:
                for model in (Membership, User, Organization):
                    async with factory() as session:
                        await session.execute(delete(model))
                        await session.commit()
                await scenario(factory)
            finally:
                await engine.dispose()

        asyncio.run(_wrapped())

    return _run


def _tables_present(expected: set[str]) -> bool:
    async def _check() -> bool:
        engine = create_engine(_database_url())
        try:
            async with engine.connect() as connection:
                tables = set(
                    await connection.run_sync(lambda conn: inspect(conn).get_table_names())
                )
                return expected.issubset(tables)
        finally:
            await engine.dispose()

    return asyncio.run(_check())


def test_migration_upgrade_downgrade_reupgrade():
    """upgrade head creates users + memberships, downgrade base drops them, re-up is clean."""
    command.downgrade(_alembic_cfg(), "base")
    assert not _tables_present({"users", "memberships"})

    command.upgrade(_alembic_cfg(), "head")
    assert _tables_present({"users", "memberships"})

    command.downgrade(_alembic_cfg(), "base")
    assert not _tables_present({"users", "memberships"})

    command.upgrade(_alembic_cfg(), "head")
    assert _tables_present({"users", "memberships"})


def test_user_and_membership_persist(run):
    """User + membership rows land in the real tables; the role round-trips as an enum."""
    async def _scenario(factory):
        async with factory() as session:
            user = User(email="ada@example.com")
            organization = Organization(name="Acme", slug="acme")
            session.add_all([user, organization])
            await session.flush()
            membership = Membership(
                user_id=user.id, organization_id=organization.id, role=MembershipRole.ADMIN
            )
            session.add(membership)
            await session.commit()
            user_id, membership_id = user.id, membership.id

        async with factory() as session:
            stored = await session.scalar(select(Membership).where(Membership.id == membership_id))
            assert stored is not None
            assert stored.user_id == user_id
            assert stored.role == MembershipRole.ADMIN
            assert stored.role.value == "admin"

    run(_scenario)


def test_all_contract_roles_persist(run):
    """Every role from the contract {owner, admin, member, viewer} is accepted and stored."""
    async def _scenario(factory):
        async with factory() as session:
            organization = Organization(name="Roles", slug="roles-org")
            session.add(organization)
            await session.flush()
            memberships = []
            for index, role in enumerate(MembershipRole):
                user = User(email=f"user-{index}@example.com")
                session.add(user)
                await session.flush()
                memberships.append(
                    Membership(user_id=user.id, organization_id=organization.id, role=role)
                )
            session.add_all(memberships)
            await session.commit()

        async with factory() as session:
            stored_roles = set(
                (await session.scalars(select(Membership.role))).all()
            )
            assert stored_roles == set(MembershipRole)

    run(_scenario)


def test_invalid_role_is_a_validation_error(run):
    """A role outside the enum is rejected with a validation error, not stored."""
    async def _scenario(factory):
        async with factory() as session:
            user = User(email="mallory@example.com")
            organization = Organization(name="Evil", slug="evil-org")
            session.add_all([user, organization])
            await session.flush()
            with pytest.raises(ValueError, match="invalid membership role"):
                session.add(
                    Membership(user_id=user.id, organization_id=organization.id, role="superuser")
                )

        async with factory() as session:
            assert (await session.scalars(select(Membership))).all() == []

    run(_scenario)


def test_ids_are_uuid_and_created_at_set(run):
    """Row defaults behave: uuid4 primary keys and a server-side created_at."""
    async def _scenario(factory):
        async with factory() as session:
            user = User(email="grace@example.com")
            session.add(user)
            await session.commit()
            assert isinstance(user.id, uuid.UUID)
            assert user.created_at is not None

    run(_scenario)
