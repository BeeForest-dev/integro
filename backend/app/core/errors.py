"""Unified exception -> RFC 7807 problem-details responses.

C03 contract: map any raised exception to a JSON problem-details body
``{type, title, status, detail, instance, errors[]}`` with media type
``application/problem+json``. Domain errors (``AppError``) map to their
declared status; unknown errors become a generic 500 whose internal detail
is written to the log only, never to the response body.
"""

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

_PROBLEM_MEDIA_TYPE = "application/problem+json"


class AppError(Exception):
    """Base class for domain errors with a fixed HTTP status mapping.

    Args:
        detail: Human-readable explanation of this concrete failure.
            Falls back to ``title`` when omitted.
        status_code: HTTP status code for the problem response
            (defaults to the class attribute of the same name).
        title: Short problem summary (defaults to the class attribute).
        errors: Optional list of per-field / per-item errors, exposed in
            the ``errors`` member of the problem-details body.
        type_: RFC 7807 ``type`` URI (defaults to
            ``urn:integro:error:<snake_case_class_name>``).

    Attributes:
        status_code: Default HTTP status code for subclasses.
        title: Default short summary for subclasses.
    """

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    title: str = "Internal Server Error"

    def __init__(
        self,
        detail: str | None = None,
        *,
        status_code: int | None = None,
        title: str | None = None,
        errors: list[dict[str, Any]] | None = None,
        type_: str | None = None,
    ) -> None:
        self.status_code = status_code if status_code is not None else self.status_code
        self.title = title if title is not None else self.title
        self.detail = detail if detail is not None else self.title
        self.errors = errors if errors is not None else []
        self.type = (
            type_
            if type_ is not None
            else f"urn:integro:error:{self._type_slug()}"
        )
        super().__init__(self.detail)

    def _type_slug(self) -> str:
        """Return the class name in snake_case for the default type URI."""
        chars: list[str] = []
        for index, char in enumerate(type(self).__name__):
            if char.isupper() and index > 0:
                chars.append("_")
            chars.append(char.lower())
        return "".join(chars)


def _problem_response(
    status_code: int,
    title: str,
    detail: str,
    type_: str,
    instance: str,
    errors: list[dict[str, Any]],
) -> JSONResponse:
    """Build an RFC 7807 problem-details JSONResponse."""
    body = {
        "type": type_,
        "title": title,
        "status": status_code,
        "detail": detail,
        "instance": instance,
        "errors": errors,
    }
    return JSONResponse(
        status_code=status_code,
        content=body,
        media_type=_PROBLEM_MEDIA_TYPE,
    )


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    """Map a domain ``AppError`` to its declared problem-details response."""
    return _problem_response(
        status_code=exc.status_code,
        title=exc.title,
        detail=exc.detail,
        type_=exc.type,
        instance=str(request.url.path),
        errors=exc.errors,
    )


async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Map a FastAPI request-validation failure to a 422 problem-details body."""
    errors = [
        {"loc": [str(part) for part in error.get("loc", ())], "msg": str(error.get("msg", ""))}
        for error in exc.errors()
    ]
    return _problem_response(
        status_code=422,
        title="Validation Failed",
        detail="Request validation failed.",
        type_="urn:integro:error:validation_failed",
        instance=str(request.url.path),
        errors=errors,
    )

async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Map any unknown exception to a generic 500 problem-details response.

    The internal exception detail is logged with the traceback and never
    included in the response body.
    """
    logger.exception(
        "unhandled error while processing %s %s",
        request.method,
        request.url.path,
        exc_info=exc,
    )
    return _problem_response(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        title="Internal Server Error",
        detail="Internal Server Error",
        type_="about:blank",
        instance=str(request.url.path),
        errors=[],
    )


def register_error_handlers(app: FastAPI) -> None:
    """Attach the problem-details handlers to a FastAPI application.

    Registers handlers for ``AppError`` (domain errors), FastAPI's
    ``RequestValidationError`` (422 with per-field ``errors``) and a
    catch-all ``Exception`` handler (generic 500).

    Args:
        app: The FastAPI application to register the handlers on.
    """
    # Handler signatures narrow the exception type; starlette's registry is
    # typed for the broad Exception base, hence the ignores (runtime is safe:
    # each handler is registered only for its own exception class).
    app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_error_handler)
