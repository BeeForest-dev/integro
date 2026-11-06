"""user password hash

Revision ID: 47461697779b
Revises: ac7e068c9197
Create Date: 2026-11-07 17:00:00.000000

Adds users.password_hash (C13) so the auth services (C14/C15) can store
argon2id hashes. Nullable: users created by pre-auth fixtures and tests
have no password yet.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '47461697779b'
down_revision: str | None = 'ac7e068c9197'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('users', sa.Column('password_hash', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'password_hash')
