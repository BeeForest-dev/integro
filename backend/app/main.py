"""FastAPI application factory and module-level app instance (C06).

``create_app()`` wires the C03 problem-details error handlers and the C06
health router. External resources (PostgreSQL engine, Redis client) are
initialised in the lifespan, so importing this module and calling
``create_app()`` never reads settings or opens connections.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import health
from app.api.middleware import RequestContextMiddleware
from app.core.config import Settings
from app.core.errors import register_error_handlers
from app.db.engine import dispose_engine, init_engine
from app.db.redis import dispose_redis, init_redis


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Initialise external resources; ``Settings()`` is read here only."""
    # Env-backed fields look like required ctor args to mypy without the
    # pydantic plugin; values come from the environment at runtime.
    settings = Settings()  # type: ignore[call-arg]
    init_engine(str(settings.DATABASE_URL))
    init_redis(settings.REDIS_URL)
    yield
    await dispose_redis()
    await dispose_engine()


def create_app() -> FastAPI:
    """Build the FastAPI application with error handlers and health routes."""
    app = FastAPI(lifespan=_lifespan)
    register_error_handlers(app)
    app.add_middleware(RequestContextMiddleware)
    app.include_router(health.router)
    return app


app = create_app()
