"""Бали БПР лектору -- перевизначення на рівні проведення.

До цього лекторська норма жила лише на курсі, тож усі його дати давали
лектору однаково. Колонка nullable: NULL означає «як у курсу»
(CourseInstance.effective_lecturer_points), а не «нуль балів», -- саме тому
бекфілу тут немає і бути не може.

Revision ID: instance_lect_points_20260910
Revises: merge_trainers_topic_20260910
Create Date: 2026-09-10

"""
import sqlalchemy as sa
from alembic import op


revision = 'instance_lect_points_20260910'
down_revision = 'merge_trainers_topic_20260910'
branch_labels = None
depends_on = None


CHECK_NAME = 'ck_course_instances_bpr_lecturer_points_non_negative'


def upgrade():
    with op.batch_alter_table('course_instances') as batch:
        batch.add_column(sa.Column('bpr_lecturer_points', sa.Numeric(5, 2)))
        # Дзеркало обмежень на бали учасника: від'ємна норма -- це не
        # «нічого», а зіпсований сертифікат, і ловити її треба в БД.
        batch.create_check_constraint(
            CHECK_NAME,
            'bpr_lecturer_points >= 0 OR bpr_lecturer_points IS NULL',
        )


def downgrade():
    with op.batch_alter_table('course_instances') as batch:
        batch.drop_constraint(CHECK_NAME, type_='check')
        batch.drop_column('bpr_lecturer_points')
