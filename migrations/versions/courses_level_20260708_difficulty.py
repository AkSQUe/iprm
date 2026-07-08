"""Courses: difficulty_level attribute (1..3)

Revision ID: courses_level_20260708
Revises: events_bar_20260708
Create Date: 2026-07-08 00:00:00.000000

Adds courses.difficulty_level (1 base / 2 advanced / 3 expert, NULL = not
set). Shown as a "Рівень N/3" badge on catalog cards and the course page;
edited in the admin course form. Multimed reference feature.
"""
from alembic import op
import sqlalchemy as sa


revision = 'courses_level_20260708'
down_revision = 'events_bar_20260708'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('courses', schema=None) as batch_op:
        batch_op.add_column(sa.Column('difficulty_level', sa.Integer(), nullable=True))
        batch_op.create_check_constraint(
            'ck_courses_difficulty_level_range',
            'difficulty_level BETWEEN 1 AND 3 OR difficulty_level IS NULL',
        )


def downgrade():
    with op.batch_alter_table('courses', schema=None) as batch_op:
        batch_op.drop_constraint('ck_courses_difficulty_level_range', type_='check')
        batch_op.drop_column('difficulty_level')
