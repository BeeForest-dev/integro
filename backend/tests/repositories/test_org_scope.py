"""Tests for C12 repositories.org_scope — the anti-leak choke point.

Real PostgreSQL via DATABASE_URL (compose postgres locally, CI service
container). No skips: without a reachable database these tests fail loudly.
"""

import asyncio
import os
from pathlib import Path

import pytest
from sqlalchemy import delete, or_, select, text

from app.core.errors import AppError
from app.db.engine import create_engine, create_session_factory
from app.models import Membership, MembershipRole, Organization, User
from app.repositories.org_scope import OrgScope, ScopeError

BACKEND_DIR = Path(__file__).resolve().parents[2]


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set - these tests require a real PostgreSQL")
    return url


@pytest.fixture
def run():
    """Run a coroutine against a fresh engine bound to a single event loop."""

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


async def _seed_two_organizations(factory):
    """Create org A and org B with one membership each; return their ids."""
    async with factory() as session:
        org_a = Organization(name="Org A", slug="org-a")
        org_b = Organization(name="Org B", slug="org-b")
        user_a = User(email="user-a@example.com")
        user_b = User(email="user-b@example.com")
        session.add_all([org_a, org_b, user_a, user_b])
        await session.flush()
        member_a = Membership(
            user_id=user_a.id, organization_id=org_a.id, role=MembershipRole.OWNER
        )
        member_b = Membership(
            user_id=user_b.id, organization_id=org_b.id, role=MembershipRole.OWNER
        )
        session.add_all([member_a, member_b])
        await session.commit()
        return org_a.id, org_b.id, member_a.id, member_b.id


def test_scoped_query_returns_only_own_rows(run):
    """The choke point returns only rows of the scope's organization."""
    async def _scenario(factory):
        org_a, org_b, member_a, member_b = await _seed_two_organizations(factory)
        async with factory() as session:
            scope = OrgScope(session, org_a)
            rows = await scope.all(scope.query(Membership))

            assert [row.id for row in rows] == [member_a]
            assert member_b not in [row.id for row in rows]
            assert org_b not in [row.organization_id for row in rows]

    run(_scenario)


def test_get_hides_cross_tenant_rows(run):
    """A foreign row id read through the scope returns None, never the row."""
    async def _scenario(factory):
        org_a, _org_b, member_a, member_b = await _seed_two_organizations(factory)
        async with factory() as session:
            scope = OrgScope(session, org_a)
            assert await scope.get(Membership, member_a) is not None
            foreign = await scope.get(Membership, member_b)
            assert foreign is None

    run(_scenario)


def test_unscoped_query_is_rejected(run):
    """SELECT without any organization filter raises ScopeError, runs nothing."""
    async def _scenario(factory):
        org_a, *_ = await _seed_two_organizations(factory)
        async with factory() as session:
            scope = OrgScope(session, org_a)
            with pytest.raises(ScopeError):
                await scope.execute(select(Membership))

    run(_scenario)


def test_foreign_scope_query_is_rejected(run):
    """A statement pinned to a DIFFERENT organization is also rejected."""
    async def _scenario(factory):
        org_a, org_b, *_ = await _seed_two_organizations(factory)
        async with factory() as session:
            scope = OrgScope(session, org_a)
            foreign_statement = select(Membership).where(Membership.organization_id == org_b)
            with pytest.raises(ScopeError):
                await scope.execute(foreign_statement)

    run(_scenario)


def test_correctly_scoped_statement_passes(run):
    """An explicitly written statement with the right equality runs fine."""
    async def _scenario(factory):
        org_a, _org_b, member_a, _member_b = await _seed_two_organizations(factory)
        async with factory() as session:
            scope = OrgScope(session, org_a)
            statement = select(Membership).where(Membership.organization_id == org_a)
            rows = await scope.all(statement)
            assert [row.id for row in rows] == [member_a]

    run(_scenario)


def test_model_without_org_column_is_rejected(run):
    """User and Organization cannot be org-scoped; querying them here errors."""
    async def _scenario(factory):
        org_a, *_ = await _seed_two_organizations(factory)
        async with factory() as session:
            scope = OrgScope(session, org_a)
            with pytest.raises(ScopeError):
                scope.query(User)
            with pytest.raises(ScopeError):
                scope.query(Organization)

    run(_scenario)


def test_scope_error_is_a_generic_app_error():
    """ScopeError maps through C03 as a generic 500, never leaking internals."""
    error = ScopeError("query attempted without organization scope")
    assert isinstance(error, AppError)
    assert error.status_code == 500
    assert error.title == "Scope Error"


def test_scope_requires_an_organization():
    """Constructing a scope without an organization fails loudly."""
    with pytest.raises(ScopeError):
        OrgScope(session=None, organization_id=None)  # type: ignore[arg-type]


def test_or_poisoned_query_is_rejected(run):
    """or_(org == A, org == B) must not launder a cross-tenant read through scope A."""
    async def _scenario(factory):
        org_a, org_b, _member_a, member_b = await _seed_two_organizations(factory)
        async with factory() as session:
            scope = OrgScope(session, org_a)
            poisoned = select(Membership).where(
                or_(
                    Membership.organization_id == org_a,
                    Membership.organization_id == org_b,
                )
            )
            with pytest.raises(ScopeError):
                await scope.execute(poisoned)
            # no foreign row id can be obtained through this scope at all
            assert await scope.get(Membership, member_b) is None

    run(_scenario)


def test_union_is_rejected(run):
    """CompoundSelect (union) is not a plain SELECT and must raise ScopeError."""
    async def _scenario(factory):
        org_a, org_b, *_ = await _seed_two_organizations(factory)
        async with factory() as session:
            scope = OrgScope(session, org_a)
            union_statement = select(Membership).where(
                Membership.organization_id == org_a
            ).union(
                select(Membership).where(Membership.organization_id == org_b)
            )
            with pytest.raises(ScopeError):
                await scope.execute(union_statement)

    run(_scenario)


def test_text_clause_is_rejected(run):
    """Raw text() bypasses inspection entirely and must raise ScopeError."""
    async def _scenario(factory):
        org_a, *_ = await _seed_two_organizations(factory)
        async with factory() as session:
            scope = OrgScope(session, org_a)
            with pytest.raises(ScopeError):
                await scope.execute(text("SELECT * FROM memberships"))

    run(_scenario)


def test_two_entity_select_is_rejected(run):
    """A second selected entity could smuggle unscoped columns; reject it."""
    async def _scenario(factory):
        org_a, *_ = await _seed_two_organizations(factory)
        async with factory() as session:
            scope = OrgScope(session, org_a)
            two_entities = select(Membership, User).where(
                Membership.organization_id == org_a
            )
            with pytest.raises(ScopeError):
                await scope.execute(two_entities)

    run(_scenario)
