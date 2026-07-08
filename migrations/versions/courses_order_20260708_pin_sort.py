"""Courses: custom catalog ordering (is_pinned + sort_order)

Revision ID: courses_order_20260708
Revises: seats_threshold_20260708
Create Date: 2026-07-08 00:00:00.000000

Adds courses.is_pinned (pinned courses go first in the public catalog) and
courses.sort_order (ascending manual order, ties broken by title). Both are
managed from the admin course form.
"""
from alembic import op
import sqlalchemy as sa


revision = 'courses_order_20260708'
down_revision = 'seats_threshold_20260708'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('courses', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_pinned', sa.Boolean(),
                                      nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column('sort_order', sa.Integer(),
                                      nullable=False, server_default='0'))
        batch_op.create_index('ix_courses_catalog_order',
                              ['is_pinned', 'sort_order'])


def downgrade():
    with op.batch_alter_table('courses', schema=None) as batch_op:
        batch_op.drop_index('ix_courses_catalog_order')
        batch_op.drop_column('sort_order')
        batch_op.drop_column('is_pinned')
