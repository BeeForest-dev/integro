"""Tests for C16 api.security — PG-backed, against a scratch FastAPI app.

The scratch app mounts one route guarded by require_roles(OWNER, ADMIN);
the C03 problem-details handlers make the 401/403 bodies assertable.
"""

import asyncio
import os
import uuid
from pathlib import Path
from typing import Annotated

import httpx
import pytest
from alembic import command
from alembic.config import Config
from fastapi import Depends, FastAPI
from sqlalchemy import delete

from app.api.security import require_roles
from app.core.errors import register_error_handlers
from app.db import engine as engine_module
from app.db.engine import create_engine, create_session_factory
from app.models import Membership, MembershipRole, Organization, User
from app.services.auth.tokens import issue_token_pair

BACKEND_DIR = Path(__file__).resolve().parents[2]
SECRET = "c16-test-secret"

app = FastAPI()
register_error_handlers(app)


@app.get("/protected")
async def _protected(
    membership: Annotated[
        Membership, Depends(require_roles(MembershipRole.OWNER, MembershipRole.ADMIN))
    ],
) -> dict:
    return {"role": membership.role.value}


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
    """Settings the per-request get_settings() reads from the environment."""
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


async def _clean_all():
    engine = create_engine(_database_url())
    factory = create_session_factory(engine)
    try:
        for model in (Membership, User, Organization):
            async with factory() as session:
                await session.execute(delete(model))
                await session.commit()
    finally:
        await engine.dispose()


async def _seed(role: MembershipRole):
    """Create an organization, a user and one membership; return their ids."""
    engine = create_engine(_database_url())
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            organization = Organization(name="Org", slug=f"org-{uuid.uuid4().hex[:8]}")
            user = User(email=f"user-{uuid.uuid4().hex[:8]}@example.com")
            session.add_all([organization, user])
            await session.flush()
            membership = Membership(
                user_id=user.id, organization_id=organization.id, role=role
            )
            session.add(membership)
            await session.commit()
            return user.id, organization.id, membership.id
    finally:
        await engine.dispose()


def _get(token: str | None) -> httpx.Response:
    """One in-process request with a fresh engine bound to one event loop."""

    async def _do():
        engine_module.init_engine(_database_url())
        try:
            transport = httpx.ASGITransport(app=app)
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            base_url = "http://testserver"
            async with httpx.AsyncClient(transport=transport, base_url=base_url) as client:
                return await client.get("/protected", headers=headers)
        finally:
            await engine_module.dispose_engine()

    return asyncio.run(_do())


def _access_token(user_id, organization_id, now=None) -> str:
    pair = issue_token_pair(user_id, organization_id, SECRET, now=now)
    return pair.access_token


def test_owner_role_passes():
    """An owner reaches a route requiring owner or admin."""
    user_id, organization_id, _ = asyncio.run(_seed(MembershipRole.OWNER))

    response = _get(_access_token(user_id, organization_id))

    assert response.status_code == 200
    assert response.json() == {"role": "owner"}


def test_insufficient_role_lists_required_roles():
    """A viewer is rejected with 403 naming the allowed roles."""
    user_id, organization_id, _ = asyncio.run(_seed(MembershipRole.VIEWER))

    response = _get(_access_token(user_id, organization_id))

    assert response.status_code == 403
    detail = response.json()["detail"]
    assert "owner" in detail and "admin" in detail
    assert "viewer" not in detail


def test_deleted_membership_is_403_not_404():
    """Revoked membership -> 403 with the shared message (no existence probing)."""
    user_id, organization_id, membership_id = asyncio.run(_seed(MembershipRole.OWNER))

    async def _revoke():
        engine = create_engine(_database_url())
        factory = create_session_factory(engine)
        try:
            async with factory() as session:
                membership = await session.get(Membership, membership_id)
                await session.delete(membership)
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(_revoke())

    response = _get(_access_token(user_id, organization_id))

    assert response.status_code == 403
    assert response.json()["detail"] == "no membership in this organization"


def test_missing_bearer_returns_401():
    """No Authorization header -> generic 401."""
    asyncio.run(_seed(MembershipRole.OWNER))

    response = _get(None)

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials"


def test_expired_token_returns_401():
    """An expired access token -> generic 401."""
    user_id, organization_id, _ = asyncio.run(_seed(MembershipRole.OWNER))
    expired = _access_token(user_id, organization_id, now=1_700_000_000)

    response = _get(expired)

    assert response.status_code == 401


def test_refresh_token_as_access_returns_401():
    """The refresh token presented as a bearer -> generic 401."""
    user_id, organization_id, _ = asyncio.run(_seed(MembershipRole.OWNER))
    refresh = issue_token_pair(user_id, organization_id, SECRET).refresh_token

    response = _get(refresh)

    assert response.status_code == 401
