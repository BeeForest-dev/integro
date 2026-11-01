"""Background tasks (C07).

Currently only the ``ping`` task, used to prove the
api -> Redis -> worker -> result-backend path end to end.
"""

from app.workers.celery_app import app


@app.task
def ping() -> str:
    """Return "pong"; verifies the worker pipeline end to end."""
    return "pong"
