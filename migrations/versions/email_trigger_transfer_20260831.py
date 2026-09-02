"""ck_email_logs_trigger: додати тригер 'transfer'.

CHECK перевипускається цілком -- ALTER для нього немає ні в SQLite, ні в
Postgres у формі "додати значення". batch_alter_table робить це однаково
на обох.

Revision ID: email_trigger_transfer_20260831
Revises: registration_transfer_20260831
"""
from alembic import op

revision = 'email_trigger_transfer_20260831'
down_revision = 'registration_transfer_20260831'
branch_labels = None
depends_on = None

OLD = (
    "trigger IN ('registration', 'payment', 'reminder', 'status_change', "
    "'email_confirm', 'course_request', 'certificate', 'blog_comment', "
    "'password_reset', 'backup_failure', 'materials', 'referral', "
    "'meta_lead', 'test')"
)
NEW = (
    "trigger IN ('registration', 'payment', 'reminder', 'status_change', "
    "'email_confirm', 'course_request', 'certificate', 'blog_comment', "
    "'password_reset', 'backup_failure', 'materials', 'referral', "
    "'meta_lead', 'transfer', 'test')"
)


def upgrade():
    with op.batch_alter_table('email_logs', schema=None) as batch_op:
        batch_op.drop_constraint('ck_email_logs_trigger', type_='check')
        batch_op.create_check_constraint('ck_email_logs_trigger', NEW)


def downgrade():
    with op.batch_alter_table('email_logs', schema=None) as batch_op:
        batch_op.drop_constraint('ck_email_logs_trigger', type_='check')
        batch_op.create_check_constraint('ck_email_logs_trigger', OLD)
