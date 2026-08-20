"""Собівартість рядка резервування матеріалів.

Revision ID: material_cost_20260820
Revises: online_reminder_20260819
"""
import sqlalchemy as sa
from alembic import op

revision = 'material_cost_20260820'
down_revision = 'online_reminder_20260819'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('material_reservation_items',
                  sa.Column('cost_uah', sa.Numeric(12, 2), nullable=True))
    op.add_column('material_reservation_items',
                  sa.Column('cost_complete', sa.Boolean(), nullable=True))


def downgrade():
    op.drop_column('material_reservation_items', 'cost_complete')
    op.drop_column('material_reservation_items', 'cost_uah')
