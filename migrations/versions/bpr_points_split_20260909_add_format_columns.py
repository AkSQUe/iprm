"""Бали БПР: дробові й окремі для онлайн- та офлайн-участі

Revision ID: bpr_points_split_20260909
Revises: specialties_20260909
Create Date: 2026-09-09

Why
---
Бали зберігались цілим числом в одній колонці на захід. Це неправда двічі:
нарахування буває дробовим (4,5 / 7,5), а на гібридному заході онлайнова й
очна участь дають РІЗНУ кількість балів, і одна колонка змушувала адміна
обрати, кого саме обманути.

Перенесення даних
-----------------
Наявне значення копіюється в ОБИДВІ нові колонки: жоден чинний захід не
міняє поведінки, а онлайнове значення адмін проставить свідомо там, де воно
інше.

participation_format бекфілиться з формату тарифу реєстрації. Де тарифу
немає (xlsx-імпорт, заведення рукою адміна) -- лишається NULL і читається
моделлю: формат заходу, а для гібрида -- офлайн.
"""
from alembic import op
import sqlalchemy as sa


revision = 'bpr_points_split_20260909'
down_revision = 'specialties_20260909'
branch_labels = None
depends_on = None

POINTS_TABLES = ('courses', 'course_instances')


def copy_points_sql(table):
    return (
        f'UPDATE {table} SET cpd_points_online = cpd_points, '
        f'cpd_points_offline = cpd_points WHERE cpd_points IS NOT NULL'
    )


def collapse_points_sql(table):
    return (
        f'UPDATE {table} SET cpd_points = cpd_points_offline '
        f'WHERE cpd_points_offline IS NOT NULL'
    )


def participation_format_backfill_sql():
    return (
        "UPDATE event_registrations SET participation_format = ("
        "SELECT t.event_format FROM instance_tariffs t "
        "WHERE t.id = event_registrations.tariff_id"
        ") WHERE tariff_id IS NOT NULL AND ("
        "SELECT t.event_format FROM instance_tariffs t "
        "WHERE t.id = event_registrations.tariff_id"
        ") IN ('online', 'offline')"
    )


def upgrade():
    for table in POINTS_TABLES:
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column('cpd_points_online', sa.Numeric(5, 2)))
            batch.add_column(sa.Column('cpd_points_offline', sa.Numeric(5, 2)))
        op.execute(copy_points_sql(table))

    with op.batch_alter_table('courses') as batch:
        batch.alter_column('bpr_lecturer_points', type_=sa.Numeric(5, 2))
        batch.drop_constraint('ck_courses_cpd_points_non_negative', type_='check')
        batch.drop_column('cpd_points')
        batch.create_check_constraint(
            'ck_courses_cpd_points_online_non_negative',
            'cpd_points_online >= 0 OR cpd_points_online IS NULL',
        )
        batch.create_check_constraint(
            'ck_courses_cpd_points_offline_non_negative',
            'cpd_points_offline >= 0 OR cpd_points_offline IS NULL',
        )

    with op.batch_alter_table('course_instances') as batch:
        batch.drop_constraint(
            'ck_course_instances_cpd_points_non_negative', type_='check',
        )
        batch.drop_column('cpd_points')
        batch.create_check_constraint(
            'ck_course_instances_cpd_points_online_non_negative',
            'cpd_points_online >= 0 OR cpd_points_online IS NULL',
        )
        batch.create_check_constraint(
            'ck_course_instances_cpd_points_offline_non_negative',
            'cpd_points_offline >= 0 OR cpd_points_offline IS NULL',
        )

    with op.batch_alter_table('event_registrations') as batch:
        batch.alter_column('cpd_points_awarded', type_=sa.Numeric(5, 2))
        batch.add_column(sa.Column('participation_format', sa.String(20)))
        batch.create_check_constraint(
            'ck_event_registrations_participation_format',
            "participation_format IN ('online', 'offline') "
            "OR participation_format IS NULL",
        )
    op.execute(participation_format_backfill_sql())

    for table in ('certificates', 'lecturer_certificates', 'online_courses'):
        with op.batch_alter_table(table) as batch:
            batch.alter_column('cpd_points', type_=sa.Numeric(5, 2))


def downgrade():
    for table in ('certificates', 'lecturer_certificates', 'online_courses'):
        with op.batch_alter_table(table) as batch:
            batch.alter_column('cpd_points', type_=sa.Integer())

    with op.batch_alter_table('event_registrations') as batch:
        batch.drop_constraint(
            'ck_event_registrations_participation_format', type_='check',
        )
        batch.drop_column('participation_format')
        batch.alter_column('cpd_points_awarded', type_=sa.Integer())

    for table in POINTS_TABLES:
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column('cpd_points', sa.Integer()))
        op.execute(collapse_points_sql(table))
        with op.batch_alter_table(table) as batch:
            batch.drop_column('cpd_points_online')
            batch.drop_column('cpd_points_offline')

    with op.batch_alter_table('courses') as batch:
        batch.alter_column('bpr_lecturer_points', type_=sa.Integer())
