"""Liveness, readiness and metrics endpoints (C06).

``/health`` never performs I/O. ``/ready`` probes DB and Redis in parallel
under a fixed timeout and reports which dependency failed — it never raises
and never hangs. ``/metrics`` exposes the process Prometheus registry in
text exposition format (no auth: the port is not published in C07).
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, generate_latest

from app.db.engine import check_database
from app.db.redis import check_redis

logger = logging.getLogger(__name__)

router = APIRouter()

# Fixed per-probe ceiling for /ready so a dead dependency can never hang
# the endpoint; intentionally a module constant, not a deployment setting.
READY_PROBE_TIMEOUT_SECONDS = 2.0

DependencyCheck = Callable[[], Awaitable[None]]

_DEPENDENCY_CHECKS: dict[str, DependencyCheck] = {
    "db": check_database,
    "redis": check_redis,
}


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe: answers without touching DB or Redis."""
    return {"status": "ok"}


async def _probe(name: str, check: DependencyCheck) -> tuple[str, bool]:
    """Run one readiness check under the timeout; any failure means False."""
    try:
        async with asyncio.timeout(READY_PROBE_TIMEOUT_SECONDS):
            await check()
    except Exception:  # noqa: BLE001 — readiness must map every failure to False
        logger.warning("readiness check failed: %s", name)
        return name, False
    return name, True


@router.get("/ready")
async def ready() -> Any:
    """Readiness probe: DB and Redis checked in parallel under a timeout.

    Returns 200 only when every check passes; otherwise 503 with the failing
    dependency names in ``failed`` (sorted). Never raises, never hangs.
    """
    outcomes = await asyncio.gather(
        *(_probe(name, check) for name, check in _DEPENDENCY_CHECKS.items())
    )
    failed = sorted(name for name, ok in outcomes if not ok)
    body: dict[str, Any] = {name: ok for name, ok in outcomes}
    if not failed:
        return body
    body["failed"] = failed
    return JSONResponse(status_code=503, content=body)


@router.get("/metrics")
async def metrics() -> Response:
    """Prometheus text-format exposition of the process registry."""
    return Response(content=generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)
