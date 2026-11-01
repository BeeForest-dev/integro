"""Declarative base shared by all ORM models and Alembic migrations.

C05 contract: declarative base + Alembic wired to the same metadata.
Every model inherits from :class:`Base` so its table is registered in
``Base.metadata`` — the single metadata Alembic inspects on autogenerate.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models.

    Tables declared on subclasses are collected in ``Base.metadata`` and are
    therefore visible both to the ORM and to Alembic migrations.
    """
