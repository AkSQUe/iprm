"""Рівень складності конкретного проведення

Revision ID: instance_difficulty_20260910
Revises: instance_topic_20260910
Create Date: 2026-09-10 00:00:00.000000

Рівень був властивістю лише курсу, тож усі його дати оголошувались
однаково базовими чи поглибленими. Насправді дати одного курсу
відрізняються підготовкою: та сама програма раз іде базовим модулем, а раз
-- поглибленим.

Колонка nullable і без server_default: NULL означає «як у курсу», тож
наявні проведення нічого не змінюють у поведінці. Шкалу 1..3 закриваємо
CHECK-обмеженням -- та сама шкала, що в Course.DIFFICULTY_LEVELS.
"""
from alembic import op
import sqlalchemy as sa


revision = 'instance_difficulty_20260910'
down_revision = 'instance_topic_20260910'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'course_instances',
        sa.Column('difficulty_level', sa.Integer(), nullable=True),
    )
    op.create_check_constraint(
        'ck_course_instances_difficulty_level_scale',
        'course_instances',
        'difficulty_level BETWEEN 1 AND 3 OR difficulty_level IS NULL',
    )


def downgrade():
    op.drop_constraint(
        'ck_course_instances_difficulty_level_scale',
        'course_instances',
        type_='check',
    )
    op.drop_column('course_instances', 'difficulty_level')
