"""Material reservation email notifications: reminder flag + 'materials' email trigger

Revision ID: mm_material_emails_20260707
Revises: mm_material_resv_20260706
Create Date: 2026-07-07 00:00:00.000000

Adds material_reservations.actuals_reminder_sent_at (idempotency for the
"submit actuals" admin reminder) and extends the email_logs trigger CHECK with
the new 'materials' trigger.
"""
from alembic import op
import sqlalchemy as sa


revision = 'mm_material_emails_20260707'
down_revision = 'mm_material_resv_20260706'
branch_labels = None
depends_on = None

_TRIGGERS_OLD = (
    "trigger IN ('registration', 'payment', 'reminder', 'status_change', "
    "'email_confirm', 'course_request', 'certificate', 'blog_comment', "
    "'password_reset', 'backup_failure', 'test')"
)
_TRIGGERS_NEW = (
    "trigger IN ('registration', 'payment', 'reminder', 'status_change', "
    "'email_confirm', 'course_request', 'certificate', 'blog_comment', "
    "'password_reset', 'backup_failure', 'materials', 'test')"
)


def upgrade():
    with op.batch_alter_table('material_reservations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('actuals_reminder_sent_at',
                                      sa.DateTime(timezone=True), nullable=True))

    op.drop_constraint('ck_email_logs_trigger', 'email_logs', type_='check')
    op.create_check_constraint('ck_email_logs_trigger', 'email_logs', _TRIGGERS_NEW)


def downgrade():
    op.drop_constraint('ck_email_logs_trigger', 'email_logs', type_='check')
    op.create_check_constraint('ck_email_logs_trigger', 'email_logs', _TRIGGERS_OLD)

    with op.batch_alter_table('material_reservations', schema=None) as batch_op:
        batch_op.drop_column('actuals_reminder_sent_at')
