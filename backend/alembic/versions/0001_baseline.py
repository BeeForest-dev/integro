"""baseline

Revision ID: 0001_baseline
Revises:
Create Date: 2026-10-22

No tables yet — the first model migrations (C10+) branch off this
revision. Exists so that ``alembic upgrade head`` always resolves.

"""
from collections.abc import Sequence

revision: str = "0001_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply the baseline revision (schema is empty so far)."""


def downgrade() -> None:
    """Revert the baseline revision (no-op)."""
