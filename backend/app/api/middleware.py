"""Request correlation-id middleware (C09).

Binds one correlation id per HTTP request: a valid incoming ``x-request-id``
is reused, a missing or invalid one is replaced with a fresh uuid4. The id
is bound to the structlog context for the duration of the request (so every
log line carries it), echoed on the response, and cleared in a ``finally``
block so ids never leak between requests.
"""

import uuid
from uuid import UUID

import structlog
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging import bind_correlation_id

_REQUEST_ID_HEADER = b"x-request-id"


def _resolve_request_id(raw_values: list[bytes]) -> str:
    """Return the incoming id when it is a valid uuid, else a fresh uuid4.

    Args:
        raw_values: All ``x-request-id`` header values from the request.

    Returns:
        The canonical string form of the reused or generated uuid.
    """
    if raw_values:
        try:
            return str(UUID(raw_values[0].decode("ascii")))
        except (ValueError, UnicodeDecodeError):
            pass
    return str(uuid.uuid4())


class RequestContextMiddleware:
    """Pure ASGI middleware assigning an ``x-request-id`` to each request.

    Args:
        app: The inner ASGI application.
    """

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Process one ASGI connection; only HTTP requests get a request id."""
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        raw_values = [value for name, value in scope["headers"] if name == _REQUEST_ID_HEADER]
        request_id = _resolve_request_id(raw_values)

        bind_correlation_id(request_id)
        try:
            await self._app(scope, receive, self._echo_request_id(send, request_id))
        finally:
            structlog.contextvars.clear_contextvars()

    @staticmethod
    def _echo_request_id(send: Send, request_id: str) -> Send:
        """Wrap ``send`` so the response carries the same ``x-request-id``."""

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(raw=list(message["headers"]))
                headers.append("x-request-id", request_id)
                message["headers"] = headers.raw
            await send(message)

        return send_with_request_id
