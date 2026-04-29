"""Add 'course_request' to allowed values of email_logs.trigger

Revision ID: f1a2b3c4d5e6
Revises: e9f0a1b2c3d4
Create Date: 2026-04-29 21:00:00.000000

Backstory: EmailService.send_course_request_notification шле email з
trigger='course_request', але існуючий CHECK не дозволяв це значення --
INSERT падав, помилка ковталась try/except у роуті, адміни не отримували
жодних сповіщень про залишені користувачами запити на курс.
"""
from alembic import op


revision = 'f1a2b3c4d5e6'
down_revision = 'e9f0a1b2c3d4'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint('ck_email_logs_trigger', 'email_logs', type_='check')
    op.create_check_constraint(
        'ck_email_logs_trigger',
        'email_logs',
        "trigger IN ('registration', 'payment', 'reminder', 'status_change', "
        "'email_confirm', 'course_request', 'test')",
    )


def downgrade():
    op.drop_constraint('ck_email_logs_trigger', 'email_logs', type_='check')
    op.create_check_constraint(
        'ck_email_logs_trigger',
        'email_logs',
        "trigger IN ('registration', 'payment', 'reminder', 'status_change', "
        "'email_confirm', 'test')",
    )
