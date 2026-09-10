"""Тема окремого проведення

Revision ID: instance_topic_20260910
Revises: event_type_indexes_20260910
Create Date: 2026-09-10 00:00:00.000000

Дати одного курсу можуть відрізнятися тематичним акцентом, і саме він, а не
загальна назва курсу, має йти в документи БПР. Тому в проведення додається
необов'язкова тема: порожня -- назва береться з курсу (CourseInstance
.effective_title), заповнена -- підміняє її скрізь, де захід називають.

Тема перекладна, як і назва курсу, тож поруч з'являється звичний для
перекладних сутностей бакет translations ({"ru": {...}, "en": {...}}).
Бекфілу немає: наявні проведення далі беруть назву курсу.
"""
from alembic import op
import sqlalchemy as sa


revision = 'instance_topic_20260910'
down_revision = 'event_type_indexes_20260910'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('course_instances') as batch:
        batch.add_column(sa.Column('topic', sa.String(length=255), nullable=True))
        batch.add_column(sa.Column('translations', sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table('course_instances') as batch:
        batch.drop_column('translations')
        batch.drop_column('topic')
