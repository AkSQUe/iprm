"""Заявка тренера на матеріали: колонки рішення + тригер і тип події

Revision ID: mat_request_20260922
Revises: lect_cert_emailed_20260922
Create Date: 2026-09-22 00:00:00.000000

Чотири колонки в material_reservations під рішення відповідального і дві
перезаливки CHECK.

CHECK на material_reservations.status і .origin НЕМАЄ (mm_material_resv_20260706
створює лише індекс по статусу), тож нові статуси 'pending_review'/'returned' і
походження 'trainer_cabinet' міграції не потребують -- вони живуть у Python.
Перевірено grep-ом по migrations/versions перед написанням; якщо колись CHECK
з'явиться, цю ревізію треба буде доповнити, інакше нові значення відкине база.

down_revision зафіксовано на фактичну голову (`flask db heads`) на момент
написання -- lect_cert_emailed_20260922, а не email_trainer_reqs_20260919, як
було записано в плані задачі: паралельна сесія в тому самому дереві додала
власну міграцію першою.
"""
from alembic import op
import sqlalchemy as sa


revision = 'mat_request_20260922'
down_revision = 'lect_cert_emailed_20260922'
branch_labels = None
depends_on = None

_TRIGGERS_OLD = (
    "trigger IN ('registration', 'payment', 'reminder', 'status_change', "
    "'email_confirm', 'course_request', 'certificate', 'blog_comment', "
    "'password_reset', 'backup_failure', 'backup_report', 'materials', "
    "'referral', 'meta_lead', 'transfer', 'quiz', 'trainer_proposal', "
    "'trainer_requisites', 'test')"
)
_TRIGGERS_NEW = (
    "trigger IN ('registration', 'payment', 'reminder', 'status_change', "
    "'email_confirm', 'course_request', 'certificate', 'blog_comment', "
    "'password_reset', 'backup_failure', 'backup_report', 'materials', "
    "'referral', 'meta_lead', 'transfer', 'quiz', 'trainer_proposal', "
    "'trainer_requisites', 'material_request', 'test')"
)

_TYPES_OLD = ("event_type IN ('registration', 'payment', 'course_request', "
              "'status_change', 'materials', 'meta_lead', 'certificate')")
_TYPES_NEW = ("event_type IN ('registration', 'payment', 'course_request', "
              "'status_change', 'materials', 'meta_lead', 'certificate', "
              "'material_request')")


def upgrade():
    with op.batch_alter_table('material_reservations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('trainer_submitted_at',
                                      sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('reviewed_at',
                                      sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('reviewed_by_id', sa.BigInteger(),
                                      nullable=True))
        batch_op.add_column(sa.Column('review_comment', sa.Text(), nullable=True))
        batch_op.create_foreign_key('fk_material_res_reviewed_by',
                                    'users', ['reviewed_by_id'], ['id'],
                                    ondelete='SET NULL')

    with op.batch_alter_table('email_logs', schema=None) as batch_op:
        batch_op.drop_constraint('ck_email_logs_trigger', type_='check')
        batch_op.create_check_constraint('ck_email_logs_trigger', _TRIGGERS_NEW)

    op.drop_constraint('ck_notification_rules_event_type', 'notification_rules',
                       type_='check')
    op.create_check_constraint('ck_notification_rules_event_type',
                               'notification_rules', _TYPES_NEW)


def downgrade():
    # Перед звуженням CHECK прибираємо рядки з новими значеннями, інакше
    # constraint не створиться (той самий порядок, що в notif_cert_failed_20260913).
    op.execute("DELETE FROM notification_rules WHERE event_type = 'material_request'")
    op.drop_constraint('ck_notification_rules_event_type', 'notification_rules',
                       type_='check')
    op.create_check_constraint('ck_notification_rules_event_type',
                               'notification_rules', _TYPES_OLD)

    op.execute("DELETE FROM email_logs WHERE trigger = 'material_request'")
    with op.batch_alter_table('email_logs', schema=None) as batch_op:
        batch_op.drop_constraint('ck_email_logs_trigger', type_='check')
        batch_op.create_check_constraint('ck_email_logs_trigger', _TRIGGERS_OLD)

    with op.batch_alter_table('material_reservations', schema=None) as batch_op:
        batch_op.drop_constraint('fk_material_res_reviewed_by', type_='foreignkey')
        batch_op.drop_column('review_comment')
        batch_op.drop_column('reviewed_by_id')
        batch_op.drop_column('reviewed_at')
        batch_op.drop_column('trainer_submitted_at')
