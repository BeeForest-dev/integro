"""Celery application for background work (C07).

Broker and result backend come from the single existing ``REDIS_URL``
setting: db 0 carries the broker, db 1 the result backend. The result DSN
is derived by replacing the URL path, so no new settings fields are needed.
Importing this module never connects to Redis — it only builds the app.
``REDIS_URL`` must be set: a missing variable fails loudly at import
(startup) instead of silently falling back to some default host.
"""

import os
from urllib.parse import urlparse, urlunparse

from celery import Celery  # type: ignore[import-untyped]

_REDIS_URL = os.environ["REDIS_URL"]


def _result_backend_url(redis_url: str) -> str:
    """Return the same Redis DSN with the database index switched to 1.

    Args:
        redis_url: Broker DSN, e.g. ``redis://host:6379/0``.

    Returns:
        The result-backend DSN pointing at database 1.
    """
    parts = urlparse(redis_url)
    return urlunparse(parts._replace(path="/1"))


app = Celery(
    "integro",
    # Import task modules when a worker starts so the tasks register.
    include=["app.workers.tasks", "app.workers.scheduler"],
)
app.conf.update(
    broker_url=_REDIS_URL,
    result_backend=_result_backend_url(_REDIS_URL),
)

# C24: one static periodic pass over due schedule flows, every 60 s.
app.conf.beat_schedule = {
    "tick-schedules": {
        "task": "app.workers.scheduler.tick_schedules",
        "schedule": 60.0,
    },
}
