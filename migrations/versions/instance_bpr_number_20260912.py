"""Реєстраційний номер заходу БПР на проведенні (з відкатом на курс)

Revision ID: instance_bpr_number_20260912
Revises: backup_report_trigger_20260912
Create Date: 2026-09-12 00:00:00.000000

Реєстр БПР видає номер на КОЖНЕ подання окремо, а поле було одне -- на
курсі. Тож усі дати одного курсу випускали сертифікати під спільним
номером, тобто документ називав не те проведення, яке людина відвідала.

Бекфілу навмисно немає. Порожнє поле означає "береться номер курсу"
(CourseInstance.effective_bpr_event_number), тож наявні дати поводяться
рівно як раніше. Скопіювати ж курсовий номер у кожне проведення означало
б закріпити в даних саме ту помилку, від якої міграція й рятує: далі його
було б не відрізнити від номера, свідомо виписаного на цю дату.

Уже виданих сертифікатів не чіпає: їхній номер записаний у
certificates.number і не перераховується.
"""
import sqlalchemy as sa
from alembic import op


revision = 'instance_bpr_number_20260912'
down_revision = 'backup_report_trigger_20260912'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('course_instances', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('bpr_event_number', sa.String(length=20), nullable=True))


def downgrade():
    with op.batch_alter_table('course_instances', schema=None) as batch_op:
        batch_op.drop_column('bpr_event_number')
