"""Alembic environment wired to the application's declarative metadata.

C05 contract: ``alembic upgrade head`` produces the schema and
``alembic revision --autogenerate`` produces a reviewable diff, both driven
by the same ``Base.metadata`` the ORM uses.

The database URL is taken from the ``DATABASE_URL`` environment variable
(falling back to ``sqlalchemy.url`` in alembic.ini) and the async DSN used
by the app (``postgresql+asyncpg://``) is converted to the synchronous
psycopg DSN Alembic connects with.

Run Alembic from ``backend/`` — ``alembic.ini`` puts that directory on
``sys.path`` (``prepend_sys_path = .``), which is how this module imports
``app.db.base``.
"""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

import app.models  # noqa: F401  # register models on Base.metadata for autogenerate
from app.db.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    """Resolve the sync database URL from the environment or the ini file.

    Raises:
        RuntimeError: If neither ``DATABASE_URL`` nor ``sqlalchemy.url``
            is set.
    """
    url = os.environ.get("DATABASE_URL") or config.get_main_option("sqlalchemy.url")
    if not url:
        raise RuntimeError("DATABASE_URL is not set and alembic.ini has no sqlalchemy.url")
    return url.replace("postgresql+asyncpg://", "postgresql+psycopg://")


def run_migrations_offline() -> None:
    """Emit SQL without a live connection (``--sql`` mode)."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Apply migrations through a live connection pool."""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
