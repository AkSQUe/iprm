"""Додати CHECK constraint max_participants >= 1 OR NULL

Revision ID: c8f3d5a72e19
Revises: b5e2a1d34f87
Create Date: 2026-03-25 12:00:00.000000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'c8f3d5a72e19'
down_revision = 'b5e2a1d34f87'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != 'sqlite':
        op.create_check_constraint(
            'ck_events_max_participants_positive', 'events',
            'max_participants >= 1 OR max_participants IS NULL'
        )


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name != 'sqlite':
        op.drop_constraint(
            'ck_events_max_participants_positive', 'events', type_='check'
        )
