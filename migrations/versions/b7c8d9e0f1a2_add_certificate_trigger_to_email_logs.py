"""Add 'certificate' to allowed values of email_logs.trigger

Revision ID: b7c8d9e0f1a2
Revises: a1c2e3f40516
Create Date: 2026-05-31 18:00:00.000000

Backstory: EmailService.send_certificate шле email з trigger='certificate',
але CHECK ck_email_logs_trigger такого значення не містив -- INSERT падав
з ProgrammingError. Сесія залишалась у rolled-back-стані, тож подальші
звернення до експайрнутих атрибутів Certificate (cert.number у flash)
ловили PendingRollbackError. Видача сертифіката повністю ламалась.
"""
from alembic import op


revision = 'b7c8d9e0f1a2'
down_revision = 'a1c2e3f40516'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint('ck_email_logs_trigger', 'email_logs', type_='check')
    op.create_check_constraint(
        'ck_email_logs_trigger',
        'email_logs',
        "trigger IN ('registration', 'payment', 'reminder', 'status_change', "
        "'email_confirm', 'course_request', 'certificate', 'test')",
    )


def downgrade():
    op.drop_constraint('ck_email_logs_trigger', 'email_logs', type_='check')
    op.create_check_constraint(
        'ck_email_logs_trigger',
        'email_logs',
        "trigger IN ('registration', 'payment', 'reminder', 'status_change', "
        "'email_confirm', 'course_request', 'test')",
    )
