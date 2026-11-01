"""Tests for C02 core.logging — one test per contract error case."""

import json
import logging

import pytest
import structlog

from app.core.logging import bind_correlation_id, setup_logging


@pytest.fixture(autouse=True)
def reset_logging_state():
    """Isolate structlog context and stdlib handlers between tests."""
    structlog.contextvars.clear_contextvars()
    yield
    structlog.contextvars.clear_contextvars()
    structlog.reset_defaults()
    logging.getLogger().handlers.clear()


def _json_lines(capsys):
    """Return all stdout lines emitted during a test as parsed JSON objects."""
    out = capsys.readouterr().out
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def test_setup_logging_returns_configured_stdlib_logger():
    """setup_logging returns the configured stdlib root logger."""
    logger = setup_logging()

    assert isinstance(logger, logging.Logger)
    assert logger.handlers


def test_setup_logging_writes_json_to_stdout(capsys):
    """Log records are rendered as structured JSON on stdout."""
    setup_logging()
    structlog.get_logger().info("hello")

    records = _json_lines(capsys)
    assert records[0]["event"] == "hello"
    assert records[0]["level"] == "info"
    assert "timestamp" in records[0]


def test_bind_correlation_id_included_in_log_records(capsys):
    """The bound correlation id appears in every log record of the context."""
    setup_logging()
    bind_correlation_id("corr-123")
    structlog.get_logger().info("with-correlation")

    records = _json_lines(capsys)
    assert records[0]["correlation_id"] == "corr-123"


def test_setup_logging_falls_back_to_plain_logging(monkeypatch, capsys):
    """Structlog failure -> no exception, plain stdlib logging still works."""
    def _boom(**_kwargs):
        raise RuntimeError("structlog broken")

    monkeypatch.setattr(structlog, "configure", _boom)

    logger = setup_logging()  # must not raise

    assert isinstance(logger, logging.Logger)
    logging.getLogger("integro.test").warning("plain message")
    out = capsys.readouterr().out
    assert "plain message" in out
    with pytest.raises(json.JSONDecodeError):
        json.loads(out.strip().splitlines()[-1])
