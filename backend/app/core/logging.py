"""Structured JSON logging with correlation-id binding.

C02 contract: configure structured JSON logging with request/correlation id.
Writes to stdout only; never raises — falls back to plain stdlib logging
if structured setup fails.
"""

import logging
import sys

import structlog


def setup_logging(log_level: int | str = logging.INFO) -> logging.Logger:
    """Configure structured JSON logging to stdout.

    Merges bound context variables (including the correlation id, see
    :func:`bind_correlation_id`) into every log record and renders each
    record as one JSON object on stdout.

    Args:
        log_level: Logging level for the root stdlib logger (e.g.
            ``logging.INFO`` or ``"INFO"``).

    Returns:
        The configured stdlib root logger.

    Raises:
        Never raises: if the structlog setup fails for any reason, the
        function falls back to plain stdlib logging on stdout.
    """
    try:
        structlog.configure(
            processors=[
                structlog.contextvars.merge_contextvars,
                structlog.processors.add_log_level,
                structlog.processors.TimeStamper(fmt="iso", utc=True),
                structlog.processors.format_exc_info,
                structlog.processors.JSONRenderer(),
            ],
            logger_factory=structlog.stdlib.LoggerFactory(),
            wrapper_class=structlog.stdlib.BoundLogger,
            cache_logger_on_first_use=True,
        )
        logging.basicConfig(level=log_level, format="%(message)s", stream=sys.stdout, force=True)
    except Exception:  # noqa: BLE001 — contract: setup must never raise
        logging.basicConfig(level=log_level, stream=sys.stdout, force=True)
    return logging.getLogger()


def bind_correlation_id(correlation_id: str) -> None:
    """Bind a correlation id to the current logging context.

    The id is included in every log record emitted by the current context
    (per-thread / per-request) until :func:`structlog.contextvars.clear_contextvars`
    is called.

    Args:
        correlation_id: The request/correlation id to attach to log records.
    """
    structlog.contextvars.bind_contextvars(correlation_id=correlation_id)
