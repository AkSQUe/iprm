"""ck_email_logs_trigger: додати тригер 'backup_report'.

Щотижневий звіт про стан резервних копій -- окремий тригер, а не
'backup_failure': лист іде і тоді, коли все гаразд, і змішувати його з
аварійним означало б зламати фільтри в журналі листів.

CHECK перевипускається цілком -- ALTER у формі "додати значення" для нього
немає ні в SQLite, ні в Postgres. batch_alter_table робить це однаково на
обох.

Revision ID: backup_report_trigger_20260912
Revises: database_backups_20260912
"""
from alembic import op

revision = 'backup_report_trigger_20260912'
down_revision = 'database_backups_20260912'
branch_labels = None
depends_on = None

OLD = (
    "trigger IN ('registration', 'payment', 'reminder', 'status_change', "
    "'email_confirm', 'course_request', 'certificate', 'blog_comment', "
    "'password_reset', 'backup_failure', 'materials', 'referral', "
    "'meta_lead', 'transfer', 'test')"
)
NEW = (
    "trigger IN ('registration', 'payment', 'reminder', 'status_change', "
    "'email_confirm', 'course_request', 'certificate', 'blog_comment', "
    "'password_reset', 'backup_failure', 'backup_report', 'materials', "
    "'referral', 'meta_lead', 'transfer', 'test')"
)


def upgrade():
    with op.batch_alter_table('email_logs', schema=None) as batch_op:
        batch_op.drop_constraint('ck_email_logs_trigger', type_='check')
        batch_op.create_check_constraint('ck_email_logs_trigger', NEW)


def downgrade():
    # Рядки зі знятим тригером порушили б вужчий CHECK -- прибираємо їх
    # разом із ним. Це лише журнал надісланих листів, не дані користувачів.
    op.execute("DELETE FROM email_logs WHERE trigger = 'backup_report'")
    with op.batch_alter_table('email_logs', schema=None) as batch_op:
        batch_op.drop_constraint('ck_email_logs_trigger', type_='check')
        batch_op.create_check_constraint('ck_email_logs_trigger', OLD)
