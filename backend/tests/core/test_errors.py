"""Tests for C03 core.errors — one test per contract error case."""

import asyncio
import json
import logging

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.requests import Request

from app.core.errors import (
    AppError,
    app_error_handler,
    register_error_handlers,
    unhandled_error_handler,
    validation_error_handler,
)

INTERNAL_SECRET = "db-password-xyzzy-leak-check"


def make_request(path: str = "/test", method: str = "GET") -> Request:
    """Build a minimal ASGI request scoped to the given path."""
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "query_string": b"",
        "headers": [],
    }
    return Request(scope)


def run(coro):
    """Run an async exception handler coroutine to completion."""
    return asyncio.run(coro)


def body_of(response) -> dict:
    """Decode a JSONResponse body into a dict."""
    return json.loads(response.body.decode())


def test_domain_error_maps_to_declared_status() -> None:
    """Domain error -> mapped status with full RFC 7807 body."""
    exc = AppError("org does not exist", status_code=404, title="Not Found")

    response = run(app_error_handler(make_request("/not-found"), exc))

    assert response.status_code == 404
    assert response.media_type == "application/problem+json"
    assert body_of(response) == {
        "type": "urn:integro:error:app_error",
        "title": "Not Found",
        "status": 404,
        "detail": "org does not exist",
        "instance": "/not-found",
        "errors": [],
    }


def test_domain_error_carries_errors_list() -> None:
    """The errors[] member is passed through for domain errors."""
    exc = AppError(
        "duplicate slug",
        status_code=409,
        title="Conflict",
        errors=[{"loc": ["slug"], "msg": "already taken"}],
    )

    response = run(app_error_handler(make_request("/conflict"), exc))

    assert response.status_code == 409
    assert body_of(response)["errors"] == [{"loc": ["slug"], "msg": "already taken"}]


def test_domain_error_detail_defaults_to_title() -> None:
    """Detail falls back to title when no explicit detail is given."""
    exc = AppError(status_code=403, title="Forbidden")

    response = run(app_error_handler(make_request("/default-detail"), exc))

    assert response.status_code == 403
    body = body_of(response)
    assert body["title"] == "Forbidden"
    assert body["detail"] == "Forbidden"


def test_unknown_error_returns_generic_500_without_internal_detail(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Unknown error -> 500 generic text; internal detail only in logs."""
    exc = RuntimeError(INTERNAL_SECRET)

    with caplog.at_level(logging.ERROR, logger="app.core.errors"):
        response = run(unhandled_error_handler(make_request("/boom"), exc))

    assert response.status_code == 500
    body = body_of(response)
    assert body["status"] == 500
    assert body["title"] == "Internal Server Error"
    assert body["detail"] == "Internal Server Error"
    assert body["errors"] == []
    assert INTERNAL_SECRET not in response.body.decode()

    # ...but the internal detail is logged.
    assert INTERNAL_SECRET in caplog.text


def test_validation_error_maps_to_422_with_field_errors() -> None:
    """Request validation failure -> 422 problem-details with per-field errors."""
    exc = RequestValidationError(
        [
            {"loc": ("body", "name"), "msg": "field required", "type": "missing"},
            {"loc": ("body", "price"), "msg": "value is not a valid integer", "type": "type_error"},
        ]
    )

    response = run(validation_error_handler(make_request("/items", method="POST"), exc))

    assert response.status_code == 422
    assert response.media_type == "application/problem+json"
    body = body_of(response)
    assert body["status"] == 422
    assert body["instance"] == "/items"
    assert body["errors"] == [
        {"loc": ["body", "name"], "msg": "field required"},
        {"loc": ["body", "price"], "msg": "value is not a valid integer"},
    ]


def test_register_error_handlers_wires_all_three() -> None:
    """Registration maps AppError, RequestValidationError and the catch-all."""
    app = FastAPI()

    register_error_handlers(app)

    handlers = app.exception_handlers
    assert handlers[AppError] is app_error_handler
    assert handlers[RequestValidationError] is validation_error_handler
    assert handlers[Exception] is unhandled_error_handler
