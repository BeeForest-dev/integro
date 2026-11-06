"""membership integrity

Revision ID: ac7e068c9197
Revises: 55f4a25579a2
Create Date: 2026-11-06 23:20:00.000000

Adds the integrity constraints that back the membership concept:
one membership per (user, organization) pair, and a database-level
CHECK keeping the role inside the contract set.

Batch mode is used so the migration also runs on the SQLite scratch
databases of the C05 fast unit tests.
"""
from collections.abc import Sequence

from alembic import op

revision: str = 'ac7e068c9197'
down_revision: str | None = '55f4a25579a2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('memberships') as batch_op:
        batch_op.create_unique_constraint(
            'uq_memberships_user_organization',
            ['user_id', 'organization_id'],
        )
        batch_op.create_check_constraint(
            'ck_memberships_role',
            "role IN ('owner', 'admin', 'member', 'viewer')",
        )


def downgrade() -> None:
    with op.batch_alter_table('memberships') as batch_op:
        batch_op.drop_constraint('ck_memberships_role')
        batch_op.drop_constraint('uq_memberships_user_organization')
