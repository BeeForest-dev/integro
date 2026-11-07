"""Tests for C15 api.auth — PG-backed, via httpx.ASGITransport (C09 pattern).

ASGITransport does not run the lifespan, so the engine is initialised
manually in fixtures exactly as app.main._lifespan would. Settings for the
endpoints are read per request from the environment.
"""

import asyncio
import os
import time
from pathlib import Path

import httpx
import pytest
from alembic import command
from sqlalchemy import delete, select

from app.db import engine as engine_module
from app.db.engine import create_engine, create_session_factory
from app.main import create_app
from app.models import AuditLog, Membership, Organization, User

BACKEND_DIR = Path(__file__).resolve().parents[2]

VALID = {
    "email": "ada@example.com",
    "password": "correct horse battery staple",
    "organization_name": "Acme",
    "organization_slug": "acme",
}

SECOND = {
    "email": "grace@example.com",
    "password": "hopper's password",
    "organization_name": "Second",
    "organization_slug": "second-org",
}


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set - these tests require a real PostgreSQL")
    return url


@pytest.fixture(autouse=True)
def environment(monkeypatch):
    """Provide the settings the endpoints read per request."""
    monkeypatch.setenv("DATABASE_URL", _database_url())
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    monkeypatch.setenv("SECRET_KEY", "c15-test-secret")


@pytest.fixture(autouse=True)
def database():
    """Schema at head and empty tables per test (requests manage engines)."""
    command.upgrade(_alembic_cfg(), "head")
    asyncio.run(_clean_all())
    yield
    asyncio.run(_clean_all())


def _alembic_cfg():
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", _database_url())
    return cfg


async def _clean_all():
    engine = create_engine(_database_url())
    factory = create_session_factory(engine)
    try:
        for model in (AuditLog, Membership, User, Organization):
            async with factory() as session:
                await session.execute(delete(model))
                await session.commit()
    finally:
        await engine.dispose()


def _request(method: str, path: str, **kwargs) -> httpx.Response:
    """Call the app in-process with a fresh engine bound to one event loop.

    Each request runs in its own asyncio.run, so the module-level engine is
    created and disposed inside that same loop (asyncpg connections are
    loop-bound).
    """

    async def _do():
        engine_module.init_engine(_database_url())
        try:
            transport = httpx.ASGITransport(app=create_app())
            base_url = "http://testserver"
            async with httpx.AsyncClient(transport=transport, base_url=base_url) as client:
                return await client.request(method, path, **kwargs)
        finally:
            await engine_module.dispose_engine()

    return asyncio.run(_do())


def _register(payload=None) -> httpx.Response:
    return _request("POST", "/auth/register", json=payload or VALID)


def _login(email=VALID["email"], password=VALID["password"]) -> httpx.Response:
    return _request("POST", "/auth/login", json={"email": email, "password": password})


def _refresh(cookies=None, json_body=None) -> httpx.Response:
    kwargs = {}
    if cookies:
        kwargs["cookies"] = cookies
    if json_body is not None:
        kwargs["json"] = json_body
    return _request("POST", "/auth/refresh", **kwargs)


def test_register_happy_path():
    """200 with tokens + user/org; httpOnly cookie; owner membership; audit row."""
    response = _register()

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"access_token", "user", "organization"}
    assert body["user"]["email"] == VALID["email"]
    assert set(body["organization"]) == {"id", "name", "slug"}
    assert body["organization"]["slug"] == VALID["organization_slug"]

    set_cookie = response.headers["set-cookie"]
    assert "integro_refresh=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "Path=/auth" in set_cookie
    assert "SameSite=lax" in set_cookie
    assert "Max-Age=604800" in set_cookie

    async def _check_db():
        engine = create_engine(_database_url())
        factory = create_session_factory(engine)
        try:
            async with factory() as session:
                membership = (
                    await session.scalars(select(Membership))
                ).one()
                assert membership.role.value == "owner"
                audits = (await session.scalars(select(AuditLog))).all()
                assert [a.action for a in audits] == ["user.registered"]
                assert audits[0].actor_user_id == membership.user_id
        finally:
            await engine.dispose()

    asyncio.run(_check_db())


def test_register_duplicate_email_returns_409():
    """A second registration with the same email -> 409, nothing leaked."""
    assert _register().status_code == 200
    other = {**SECOND, "email": VALID["email"]}

    response = _register(other)

    assert response.status_code == 409
    assert response.json()["status"] == 409


def test_register_duplicate_slug_returns_409():
    """A second registration with the same slug -> 409."""
    assert _register().status_code == 200
    other = {**SECOND, "organization_slug": VALID["organization_slug"]}

    response = _register(other)

    assert response.status_code == 409


def test_unknown_email_and_wrong_password_have_identical_401_bodies():
    """Probe-safety: both failures return byte-identical problem bodies."""
    assert _register().status_code == 200
    unknown = _login(email="nobody@example.com", password="whatever")
    wrong = _login(password="not the password")

    assert unknown.status_code == 401
    assert wrong.status_code == 401
    assert unknown.text == wrong.text
    assert unknown.json()["detail"] == "Invalid credentials"


def test_login_happy_path():
    """Registered user logs in: same body shape plus the refresh cookie."""
    assert _register().status_code == 200

    response = _login()

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"access_token", "user", "organization"}
    assert body["user"]["email"] == VALID["email"]
    assert "integro_refresh=" in response.headers["set-cookie"]


def test_refresh_rotates_the_pair():
    """Refresh returns a new access token and sets a new cookie."""
    assert _register().status_code == 200
    login = _login()
    assert login.status_code == 200
    old_access = login.json()["access_token"]
    old_cookie = login.cookies["integro_refresh"]

    # HS256 is deterministic: same claims issued in the same second produce
    # the same token, so rotate across a second boundary.
    time.sleep(1.1)

    response = _refresh(cookies={"integro_refresh": old_cookie})

    assert response.status_code == 200
    assert response.json()["access_token"] != old_access
    new_cookie = response.cookies["integro_refresh"]
    assert new_cookie != old_cookie


def test_refresh_without_cookie_returns_401():
    """No cookie -> generic 401."""
    assert _register().status_code == 200

    response = _refresh()

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials"


def test_refresh_with_tampered_cookie_returns_401():
    """A forged cookie -> generic 401."""
    assert _register().status_code == 200
    login = _login()
    tampered = login.cookies["integro_refresh"][:-4] + "AAAA"

    response = _refresh(cookies={"integro_refresh": tampered})

    assert response.status_code == 401


def test_refresh_ignores_body_token():
    """A refresh token presented in the body (no cookie) is not accepted."""
    assert _register().status_code == 200
    login = _login()
    refresh_token = login.cookies["integro_refresh"]

    response = _refresh(json_body={"token": refresh_token})

    assert response.status_code == 401


def test_me_returns_role_from_membership():
    """GET /auth/me yields user, org and the membership role."""
    assert _register().status_code == 200
    login = _login()
    access = login.json()["access_token"]

    response = _request("GET", "/auth/me", headers={"Authorization": f"Bearer {access}"})

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"user", "organization", "role"}
    assert body["role"] == "owner"
    assert body["user"]["email"] == VALID["email"]
    assert body["organization"]["slug"] == VALID["organization_slug"]


def test_me_without_bearer_returns_401():
    """No Authorization header -> 401."""
    assert _register().status_code == 200

    response = _request("GET", "/auth/me")

    assert response.status_code == 401


def test_me_with_refresh_token_as_access_returns_401():
    """The refresh token used as a bearer is rejected (type mismatch)."""
    assert _register().status_code == 200
    login = _login()
    refresh_token = login.cookies["integro_refresh"]

    response = _request(
        "GET", "/auth/me", headers={"Authorization": f"Bearer {refresh_token}"}
    )

    assert response.status_code == 401
