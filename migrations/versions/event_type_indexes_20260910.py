"""Індекси на коди виду заходу в курсах і проведеннях

Revision ID: event_type_indexes_20260910
Revises: merge_bpr_heads_20260910
Create Date: 2026-09-10 00:00:00.000000

Сторінка довідника видів заходів рахує вагу кожного рядка двома GROUP BY
по courses.event_type і course_instances.event_type, а список курсів
відтепер уміє фільтруватись за тим самим полем. Обидва запити ходили
послідовним читанням: на нинішніх обсягах це дешево, але поле стало
робочим, а не декоративним.

Моделі несуть index=True на тих самих колонках, щоб схема, яку тести
піднімають через create_all, збігалася з міграційною.
"""
from alembic import op


revision = 'event_type_indexes_20260910'
down_revision = 'merge_bpr_heads_20260910'
branch_labels = None
depends_on = None


def upgrade():
    op.create_index('ix_courses_event_type', 'courses', ['event_type'])
    op.create_index(
        'ix_course_instances_event_type', 'course_instances', ['event_type'])


def downgrade():
    op.drop_index('ix_course_instances_event_type', table_name='course_instances')
    op.drop_index('ix_courses_event_type', table_name='courses')
