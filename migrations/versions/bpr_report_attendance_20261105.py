"""Присутність у три стани, прапорець закриття звітом, дата подачі звіту БПР

Revision ID: bpr_report_attendance_20261105
Revises: email_attach_cid_20261101
Create Date: 2026-11-05

Why
---
`event_registrations.attended` був так/ні зі значенням за замовчуванням
False, тож «не з'явився» і «ніхто не відмічав» були неотримувані. Тепер
NULL = не відмічено, False = не з'явився, True = був. Наявні False ніхто
свідомо не ставив -- це було значення за замовчуванням, тому upgrade
переводить їх у NULL.

`completed_by_report` -- рядок став «Завершено» подачею звіту (а не
вручну), потрібно для чистого скасування подачі.
`course_instances.bpr_report_submitted_on/_by_id` -- дата й автор подачі
звіту до Центру тестування БПР.

Деплой
------
Старий код читає `attended` як bool і при NULL поводиться як при False,
тож порядок «міграція -> перезапуск» безпечний. Downgrade повертає NULL у
False, відновлює NOT NULL і прибирає нові колонки.
"""
import sqlalchemy as sa
from alembic import op


revision = 'bpr_report_attendance_20261105'
down_revision = 'email_attach_cid_20261101'
branch_labels = None
depends_on = None


def _columns(table):
    return {c['name'] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade():
    reg_cols = _columns('event_registrations')
    inst_cols = _columns('course_instances')

    with op.batch_alter_table('event_registrations') as batch:
        batch.alter_column('attended', existing_type=sa.Boolean(),
                           nullable=True)
        if 'completed_by_report' not in reg_cols:
            batch.add_column(sa.Column(
                'completed_by_report', sa.Boolean(), nullable=False,
                server_default=sa.false(),
            ))

    op.execute('UPDATE event_registrations SET attended = NULL '
               'WHERE attended = false')

    with op.batch_alter_table('course_instances') as batch:
        if 'bpr_report_submitted_on' not in inst_cols:
            batch.add_column(sa.Column('bpr_report_submitted_on', sa.Date()))
        if 'bpr_report_submitted_by_id' not in inst_cols:
            batch.add_column(sa.Column(
                'bpr_report_submitted_by_id', sa.BigInteger(), nullable=True,
            ))
            batch.create_foreign_key(
                'fk_course_instances_bpr_report_submitted_by',
                'users', ['bpr_report_submitted_by_id'], ['id'],
                ondelete='SET NULL',
            )


def downgrade():
    inst_cols = _columns('course_instances')
    reg_cols = _columns('event_registrations')

    with op.batch_alter_table('course_instances') as batch:
        if 'bpr_report_submitted_by_id' in inst_cols:
            batch.drop_constraint(
                'fk_course_instances_bpr_report_submitted_by',
                type_='foreignkey',
            )
            batch.drop_column('bpr_report_submitted_by_id')
        if 'bpr_report_submitted_on' in inst_cols:
            batch.drop_column('bpr_report_submitted_on')

    op.execute('UPDATE event_registrations SET attended = false '
               'WHERE attended IS NULL')
    with op.batch_alter_table('event_registrations') as batch:
        batch.alter_column('attended', existing_type=sa.Boolean(),
                           nullable=False)
        if 'completed_by_report' in reg_cols:
            batch.drop_column('completed_by_report')
