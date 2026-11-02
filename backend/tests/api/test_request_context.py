"""Tests for C09 api.request_context — one test per contract error case."""

import asyncio
import json
import logging
import uuid

import httpx
import pytest
import structlog
from fastapi import FastAPI

from app.api.middleware import RequestContextMiddleware
from app.core.logging import setup_logging
from app.main import create_app


@pytest.fixture(autouse=True)
def reset_logging_state():
    """Isolate structlog context between tests."""
    structlog.contextvars.clear_contextvars()
    yield
    structlog.contextvars.clear_contextvars()
    structlog.reset_defaults()
    logging.getLogger().handlers.clear()


def _build_app():
    """Small app with the middleware and a route that emits one log line."""
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)

    @app.get("/probe")
    async def _probe():
        structlog.get_logger().info("probe-request")
        return {"status": "ok"}

    return app


def _get(app, path: str, headers: dict[str, str] | None = None) -> httpx.Response:
    """Call an ASGI app in-process, the same way as the other api tests."""

    async def _fetch() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        base_url = "http://testserver"
        async with httpx.AsyncClient(transport=transport, base_url=base_url) as client:
            return await client.get(path, headers=headers or {})

    return asyncio.run(_fetch())


def test_missing_header_gets_generated_uuid():
    """No x-request-id -> response carries a fresh valid uuid."""
    response = _get(_build_app(), "/probe")

    assert response.status_code == 200
    request_id = response.headers["x-request-id"]
    uuid.UUID(request_id)  # raises if the header is not a valid uuid


def test_valid_header_is_reused():
    """A valid incoming x-request-id is echoed back unchanged."""
    incoming = str(uuid.uuid4())

    response = _get(_build_app(), "/probe", headers={"x-request-id": incoming})

    assert response.headers["x-request-id"] == incoming


def test_invalid_header_is_replaced():
    """A non-uuid x-request-id is replaced with a fresh valid uuid."""
    response = _get(_build_app(), "/probe", headers={"x-request-id": "not-a-uuid"})

    request_id = response.headers["x-request-id"]
    assert request_id != "not-a-uuid"
    uuid.UUID(request_id)


def test_correlation_id_present_in_log_output(capsys):
    """The bound id appears in the emitted log line."""
    setup_logging()
    response = _get(_build_app(), "/probe")
    request_id = response.headers["x-request-id"]

    # httpx logs its request line at INFO through the same root logger;
    # only the JSON log records are ours.
    lines = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if line.strip().startswith("{")
    ]
    probe_records = [record for record in lines if record.get("event") == "probe-request"]
    assert probe_records[0]["correlation_id"] == request_id


def test_context_cleared_after_request():
    """The correlation id does not leak into the next request's context.

    The request and the assertion must run in the same coroutine: cleanup
    happens inside the middleware's task context, and checking from another
    context would pass even if the ``finally`` block did nothing.
    """

    async def scenario() -> None:
        transport = httpx.ASGITransport(app=_build_app())
        base_url = "http://testserver"
        async with httpx.AsyncClient(transport=transport, base_url=base_url) as client:
            response = await client.get("/probe")
        uuid.UUID(response.headers["x-request-id"])  # a valid id was assigned

        assert "correlation_id" not in structlog.contextvars.get_contextvars()

    asyncio.run(scenario())


def test_create_app_registers_middleware():
    """create_app wires RequestContextMiddleware via add_middleware."""
    app = create_app()

    middleware_names = [entry.cls for entry in app.user_middleware]
    assert RequestContextMiddleware in middleware_names
