"""ORM models.

Import every model here so its table registers on ``Base.metadata`` —
that is what the ORM and Alembic autogenerate inspect.
"""

from app.models.organization import Organization

__all__ = ["Organization"]
