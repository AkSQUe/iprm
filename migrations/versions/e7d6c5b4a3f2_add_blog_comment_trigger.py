"""Add 'blog_comment' to allowed values of email_logs.trigger

Revision ID: e7d6c5b4a3f2
Revises: 9a8b7c6d5e4f
Create Date: 2026-06-09 14:00:00.000000

Backstory: EmailService.send_blog_comment_notification шле email з
trigger='blog_comment'; без цього значення у CHECK ck_email_logs_trigger
INSERT email_logs падав, псуючи сесію (як свого часу з 'certificate').
"""
from alembic import op


revision = 'e7d6c5b4a3f2'
down_revision = '9a8b7c6d5e4f'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint('ck_email_logs_trigger', 'email_logs', type_='check')
    op.create_check_constraint(
        'ck_email_logs_trigger',
        'email_logs',
        "trigger IN ('registration', 'payment', 'reminder', 'status_change', "
        "'email_confirm', 'course_request', 'certificate', 'blog_comment', 'test')",
    )


def downgrade():
    op.drop_constraint('ck_email_logs_trigger', 'email_logs', type_='check')
    op.create_check_constraint(
        'ck_email_logs_trigger',
        'email_logs',
        "trigger IN ('registration', 'payment', 'reminder', 'status_change', "
        "'email_confirm', 'course_request', 'certificate', 'test')",
    )
