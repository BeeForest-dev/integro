"""Tests for C07 workers.tasks."""

import os

os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from app.workers import celery_app
from app.workers.tasks import ping


def test_ping_returns_pong():
    """Direct call returns "pong" without Redis."""
    assert ping() == "pong"


def test_task_module_registered_in_celery_include():
    """The worker must import the task module or it starts with an empty registry."""
    assert "app.workers.tasks" in celery_app.app.conf.include
