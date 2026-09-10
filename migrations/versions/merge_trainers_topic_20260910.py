"""Злиття голів: тренери заходу (course_trainers) і тема проведення (instance_topic).

Порожня ревізія -- обидві гілки відгалузились від merge_bpr_heads_20260910
паралельно і схему правили в різних місцях (таблиця звʼязку
course_instance_trainers проти колонки course_instances.topic), тож зводити
руками нема чого. Ревізія існує лише для того, щоб `flask db upgrade` мав
одну голову: із двома він відмовляється працювати взагалі.

Revision ID: merge_trainers_topic_20260910
Revises: course_trainers_20260910, instance_topic_20260910
Create Date: 2026-09-10 21:17:38.860353

"""
# revision identifiers, used by Alembic.
revision = 'merge_trainers_topic_20260910'
down_revision = ('course_trainers_20260910', 'instance_topic_20260910')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
