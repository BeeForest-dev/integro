"""Async SQLAlchemy engine and session factory.

C04 contract: AsyncSession via dependency injection. Opens a connection
pool to PostgreSQL. An unreachable database surfaces as 503
(``DatabaseUnavailableError``), never as an unhandled 500.
"""

from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.errors import AppError


class DatabaseUnavailableError(AppError):
    """PostgreSQL is unreachable; surfaces to clients as HTTP 503."""

    status_code = 503
    title = "Database Unavailable"


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def create_engine(database_url: str) -> AsyncEngine:
    """Create the async engine (connection pool) for the given DSN.

    Args:
        database_url: Async PostgreSQL DSN, e.g.
            ``postgresql+asyncpg://user:pass@host:5432/dbname``.

    Returns:
        An ``AsyncEngine``; no connection is opened until first use.
    """
    return create_async_engine(database_url)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create the session factory bound to the given engine.

    Args:
        engine: The engine the produced sessions will be bound to.

    Returns:
        An ``async_sessionmaker`` producing ``AsyncSession`` instances.
    """
    return async_sessionmaker(engine, expire_on_commit=False)


def init_engine(database_url: str) -> None:
    """Initialise the module-level engine and session factory.

    Args:
        database_url: Async PostgreSQL DSN.
    """
    global _engine, _session_factory
    _engine = create_engine(database_url)
    _session_factory = create_session_factory(_engine)


async def dispose_engine() -> None:
    """Close the connection pool and reset the module-level state."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
    _session_factory = None


async def check_database() -> None:
    """Probe PostgreSQL with ``SELECT 1`` through a short-lived session.

    Raises:
        RuntimeError: If ``init_engine()`` was not called first.
        DatabaseUnavailableError: If PostgreSQL is unreachable.
    """
    if _session_factory is None:
        raise RuntimeError("engine not initialised — call init_engine() first")
    async with _session_factory() as session:
        try:
            await session.execute(text("SELECT 1"))
        except Exception as exc:  # contract: 503, never 500
            raise DatabaseUnavailableError("database is unreachable") from exc


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding an ``AsyncSession``.

    Acquires a pooled connection (``SELECT 1``) before yielding, so an
    unreachable database raises ``DatabaseUnavailableError`` (HTTP 503)
    instead of letting the raw connection error escape as a 500.

    Raises:
        RuntimeError: If ``init_engine()`` was not called first.
        DatabaseUnavailableError: If PostgreSQL is unreachable.

    Yields:
        A session with a live pooled connection.
    """
    if _session_factory is None:
        raise RuntimeError("engine not initialised — call init_engine() first")
    async with _session_factory() as session:
        try:
            # The probe must catch everything a connect can raise: refused
            # connections surface as raw OSError, other failures as
            # SQLAlchemyError subclasses — all mean "no working connection".
            await session.execute(text("SELECT 1"))
        except Exception as exc:  # contract: 503, never 500
            raise DatabaseUnavailableError("database is unreachable") from exc
        yield session
