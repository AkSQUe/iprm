"""Courses: roi_hint marketing line

Revision ID: courses_roi_20260708
Revises: courses_level_20260708
Create Date: 2026-07-08 00:00:00.000000

Adds courses.roi_hint -- a short marketing payback hint (e.g. "Окупність
~ 3-4 записи за чека 6 000-9 000 грн") shown on the course hero and the
catalog card. Edited in the admin course form. Multimed reference feature.
"""
from alembic import op
import sqlalchemy as sa


revision = 'courses_roi_20260708'
down_revision = 'courses_level_20260708'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('courses', schema=None) as batch_op:
        batch_op.add_column(sa.Column('roi_hint', sa.String(200), nullable=True))


def downgrade():
    with op.batch_alter_table('courses', schema=None) as batch_op:
        batch_op.drop_column('roi_hint')
