"""Tests for C06 api.health — one test per contract error case.

``httpx.ASGITransport`` does not run the FastAPI lifespan, so the engine
and Redis client are initialised/disposed manually in fixtures — exactly
how the live process does it via ``app.main._lifespan``.
"""

import asyncio
import time

import httpx
import pytest

from app.api import health
from app.db import engine as engine_module
from app.db import redis as redis_module
from app.main import create_app

# Port 1 is guaranteed closed: connection refused, no network dependency.
UNREACHABLE_PG_URL = "postgresql+asyncpg://user:pass@127.0.0.1:1/none"


async def _ok() -> None:
    """A dependency check that succeeds."""


async def _failing_db() -> None:
    """A dependency check that fails the way a dead PostgreSQL does."""
    raise engine_module.DatabaseUnavailableError("database is unreachable")


async def _failing_redis() -> None:
    """A dependency check that fails the way a dead Redis does."""
    raise ConnectionRefusedError("redis is down")


async def _slow() -> None:
    """A dependency check that hangs far beyond the probe timeout."""
    await asyncio.sleep(60)


def _get(app, path: str) -> httpx.Response:
    """Call an ASGI app in-process, the same way as the C04 503 test."""

    async def _fetch() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        base_url = "http://testserver"
        async with httpx.AsyncClient(transport=transport, base_url=base_url) as client:
            return await client.get(path)

    return asyncio.run(_fetch())


@pytest.fixture(autouse=True)
def reset_dependencies():
    """Start and end every test with no engine and no Redis client."""
    asyncio.run(engine_module.dispose_engine())
    asyncio.run(redis_module.dispose_redis())
    yield
    asyncio.run(engine_module.dispose_engine())
    asyncio.run(redis_module.dispose_redis())


def test_health_ok_without_dependencies():
    """Liveness answers 200 exactly, even with DB and Redis down."""
    response = _get(create_app(), "/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_ok_when_all_dependencies_healthy(monkeypatch):
    """Readiness 200 with both checks True."""
    monkeypatch.setattr(health, "_DEPENDENCY_CHECKS", {"db": _ok, "redis": _ok})

    response = _get(create_app(), "/ready")

    assert response.status_code == 200
    assert response.json() == {"db": True, "redis": True}


def test_ready_503_when_database_down(monkeypatch):
    """DB failure -> 503, failed == ["db"], redis still True."""
    monkeypatch.setattr(health, "_DEPENDENCY_CHECKS", {"db": _failing_db, "redis": _ok})

    response = _get(create_app(), "/ready")

    assert response.status_code == 503
    assert response.json() == {"db": False, "redis": True, "failed": ["db"]}


def test_ready_503_when_redis_down(monkeypatch):
    """Redis failure -> 503, failed == ["redis"], db still True."""
    monkeypatch.setattr(health, "_DEPENDENCY_CHECKS", {"db": _ok, "redis": _failing_redis})

    response = _get(create_app(), "/ready")

    assert response.status_code == 503
    assert response.json() == {"db": True, "redis": False, "failed": ["redis"]}


def test_ready_503_when_all_dependencies_down(monkeypatch):
    """Both failures -> 503 with the sorted failed list."""
    monkeypatch.setattr(
        health, "_DEPENDENCY_CHECKS", {"db": _failing_db, "redis": _failing_redis}
    )

    response = _get(create_app(), "/ready")

    assert response.status_code == 503
    assert response.json() == {"db": False, "redis": False, "failed": ["db", "redis"]}


def test_ready_times_out_slow_dependency(monkeypatch):
    """A hanging check -> 503 within ~3 s, not after the hang duration."""
    monkeypatch.setattr(health, "_DEPENDENCY_CHECKS", {"db": _slow, "redis": _ok})

    started = time.monotonic()
    response = _get(create_app(), "/ready")
    elapsed = time.monotonic() - started

    assert response.status_code == 503
    assert response.json()["failed"] == ["db"]
    assert elapsed < 3.0


def test_metrics_exposes_prometheus_text():
    """Metrics endpoint serves Prometheus exposition format."""
    response = _get(create_app(), "/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "# HELP" in response.text
    assert "# TYPE" in response.text


def test_ready_reports_real_unreachable_database(monkeypatch):
    """No mocks: a refused PostgreSQL connection surfaces as 503 with failed db."""
    engine_module.init_engine(UNREACHABLE_PG_URL)
    checks = {"db": health._DEPENDENCY_CHECKS["db"], "redis": _ok}
    monkeypatch.setattr(health, "_DEPENDENCY_CHECKS", checks)

    response = _get(create_app(), "/ready")

    assert response.status_code == 503
    assert response.json() == {"db": False, "redis": True, "failed": ["db"]}


def test_ready_reports_real_unreachable_redis(monkeypatch):
    """No mocks: a refused Redis connection surfaces as 503 with failed redis.

    Exercises the real ``init_redis`` + ``check_redis`` path from
    ``app/db/redis.py`` (a stubbed check would not catch a broken ``PING``).
    """
    redis_module.init_redis("redis://127.0.0.1:1/0")  # port 1 is guaranteed closed
    checks = {"db": _ok, "redis": health._DEPENDENCY_CHECKS["redis"]}
    monkeypatch.setattr(health, "_DEPENDENCY_CHECKS", checks)

    response = _get(create_app(), "/ready")

    assert response.status_code == 503
    assert response.json() == {"db": True, "redis": False, "failed": ["redis"]}
