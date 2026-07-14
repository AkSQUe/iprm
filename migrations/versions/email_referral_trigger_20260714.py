"""Allow 'referral' trigger in email_logs CHECK

Revision ID: email_referral_trigger_20260714
Revises: referral_rewards_20260714
Create Date: 2026-07-14 02:00:00.000000

Реферальні листи (сповіщення реферера про нарахування) використовують
trigger='referral'. Розширюємо ck_email_logs_trigger, інакше INSERT листа
впаде на CHECK (та сама пастка, що з 'materials').
"""
from alembic import op


revision = 'email_referral_trigger_20260714'
down_revision = 'referral_rewards_20260714'
branch_labels = None
depends_on = None

_OLD = ("trigger IN ('registration', 'payment', 'reminder', 'status_change', "
        "'email_confirm', 'course_request', 'certificate', 'blog_comment', "
        "'password_reset', 'backup_failure', 'materials', 'test')")
_NEW = ("trigger IN ('registration', 'payment', 'reminder', 'status_change', "
        "'email_confirm', 'course_request', 'certificate', 'blog_comment', "
        "'password_reset', 'backup_failure', 'materials', 'referral', 'test')")


def upgrade():
    op.drop_constraint('ck_email_logs_trigger', 'email_logs', type_='check')
    op.create_check_constraint('ck_email_logs_trigger', 'email_logs', _NEW)


def downgrade():
    op.execute("UPDATE email_logs SET trigger = NULL WHERE trigger = 'referral'")
    op.drop_constraint('ck_email_logs_trigger', 'email_logs', type_='check')
    op.create_check_constraint('ck_email_logs_trigger', 'email_logs', _OLD)
