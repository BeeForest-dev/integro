"""Tests for C04 db.engine — one test per contract error case."""

import asyncio
from typing import Annotated

import httpx
import pytest
from fastapi import Depends, FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import register_error_handlers
from app.db.engine import (
    DatabaseUnavailableError,
    create_engine,
    create_session_factory,
    dispose_engine,
    get_session,
    init_engine,
)

# Port 1 is guaranteed closed: connection refused, no network dependency.
UNREACHABLE_URL = "postgresql+asyncpg://user:pass@127.0.0.1:1/none"


@pytest.fixture(autouse=True)
def reset_engine():
    """Reset module-level engine state between tests."""
    yield
    asyncio.run(dispose_engine())


def test_session_factory_creates_async_session():
    """The session factory produces AsyncSession instances."""
    engine = create_engine(UNREACHABLE_URL)
    factory = create_session_factory(engine)

    async def _check():
        async with factory() as session:
            assert isinstance(session, AsyncSession)

    asyncio.run(_check())
    asyncio.run(engine.dispose())


def test_get_session_raises_503_error_when_db_unreachable():
    """DB unreachable -> DatabaseUnavailableError carrying HTTP 503."""
    init_engine(UNREACHABLE_URL)

    async def _consume():
        agen = get_session()
        try:
            await agen.__anext__()
        finally:
            await agen.aclose()

    with pytest.raises(DatabaseUnavailableError) as exc_info:
        asyncio.run(_consume())

    assert exc_info.value.status_code == 503
    assert exc_info.value.title == "Database Unavailable"


def test_unavailable_db_surfaces_as_503_response():
    """Through FastAPI + C03 handlers the failure is a 503, not a 500."""
    app = FastAPI()
    register_error_handlers(app)
    init_engine(UNREACHABLE_URL)

    @app.get("/query")
    async def _query(session: Annotated[AsyncSession, Depends(get_session)]):
        return {"ok": True}

    async def _fetch() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        base_url = "http://testserver"
        async with httpx.AsyncClient(transport=transport, base_url=base_url) as client:
            return await client.get("/query")

    response = asyncio.run(_fetch())

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == 503
    assert body["title"] == "Database Unavailable"
    assert body["instance"] == "/query"


def test_get_session_without_init_raises_runtime_error():
    """Dependency used before init_engine -> clear error, not an NPE."""
    asyncio.run(dispose_engine())

    async def _consume():
        agen = get_session()
        try:
            await agen.__anext__()
        finally:
            await agen.aclose()

    with pytest.raises(RuntimeError, match="init_engine"):
        asyncio.run(_consume())
