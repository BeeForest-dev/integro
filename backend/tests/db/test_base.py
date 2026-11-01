"""Tests for C05 db.base — declarative base shared with Alembic."""

from sqlalchemy import Column, Integer
from sqlalchemy.orm import DeclarativeBase

from app.db.base import Base


def test_base_is_a_declarative_base_with_metadata():
    """Base is a SQLAlchemy 2.x DeclarativeBase carrying a MetaData object."""
    assert issubclass(Base, DeclarativeBase)
    assert Base.metadata is not None


def test_models_register_on_shared_metadata():
    """A model declared on Base lands in the metadata Alembic inspects."""
    class Probe(Base):
        __tablename__ = "probe"

        id = Column(Integer, primary_key=True)

    try:
        assert "probe" in Base.metadata.tables
        assert Base.metadata.tables["probe"] is Probe.__table__
    finally:
        Base.metadata.remove(Probe.__table__)
