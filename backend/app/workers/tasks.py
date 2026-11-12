"""Background tasks (C07).

C22 adds the event-ingestion placeholder; the real execution engine
replaces it in M3.
"""

import logging

from app.workers.celery_app import app

logger = logging.getLogger(__name__)


@app.task
def ping() -> str:
    """Return "pong"; verifies the worker pipeline end to end."""
    return "pong"


@app.task
def process_event(event_id: str) -> str:
    """Placeholder event processor (C22): log and return the event id.

    The real dispatcher/executor engine lands in M3 and will replace this
    body without changing the task name.
    """
    logger.info("process_event placeholder", extra={"event_id": event_id})
    return event_id
