"""add password_reset trigger to email_logs

Revision ID: 9e14e2c0dbf1
Revises: c4e5f6a7b8d9
Create Date: 2026-06-24 20:25:57.013048

Backstory: EmailService.send_password_reset шле email з trigger='password_reset';
без цього значення у CHECK ck_email_logs_trigger INSERT email_logs падав, лист
відновлення пароля ніколи не надсилався (виняток ковтався у forgot_password).
Та сама причина, що свого часу з 'certificate' / 'blog_comment'.
"""
from alembic import op


revision = '9e14e2c0dbf1'
down_revision = 'c4e5f6a7b8d9'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint('ck_email_logs_trigger', 'email_logs', type_='check')
    op.create_check_constraint(
        'ck_email_logs_trigger',
        'email_logs',
        "trigger IN ('registration', 'payment', 'reminder', 'status_change', "
        "'email_confirm', 'course_request', 'certificate', 'blog_comment', "
        "'password_reset', 'test')",
    )


def downgrade():
    op.drop_constraint('ck_email_logs_trigger', 'email_logs', type_='check')
    op.create_check_constraint(
        'ck_email_logs_trigger',
        'email_logs',
        "trigger IN ('registration', 'payment', 'reminder', 'status_change', "
        "'email_confirm', 'course_request', 'certificate', 'blog_comment', 'test')",
    )
