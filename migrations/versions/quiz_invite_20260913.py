"""Запрошення на тестування: колонка на реєстрації й тригер листа 'quiz'.

* event_registrations.quiz_invite_sent_at -- один лист «тестування
  відкрито» на реєстрацію (scheduler-джоба send_quiz_invites).
* ck_email_logs_trigger -- новий тригер 'quiz'. Лист транзакційний: без
  тесту й анкети сертифіката не буде, тож він не йде під 'reminder', який
  поважає відписку від розсилок.

CHECK перевипускається цілком через batch_alter_table (як у
email_trigger_transfer_20260831).

Бекфілу немає свідомо: джоба запрошує лише учасників заходів, що почались
не раніше ніж 7 днів тому (QUIZ_INVITE_LOOKBACK), тож минулі заходи листів не
отримають і без позначок.

Revision ID: quiz_invite_20260913
Revises: notif_cert_failed_20260913
"""
from alembic import op
import sqlalchemy as sa

revision = 'quiz_invite_20260913'
down_revision = 'notif_cert_failed_20260913'
branch_labels = None
depends_on = None

OLD = (
    "trigger IN ('registration', 'payment', 'reminder', 'status_change', "
    "'email_confirm', 'course_request', 'certificate', 'blog_comment', "
    "'password_reset', 'backup_failure', 'backup_report', 'materials', "
    "'referral', 'meta_lead', 'transfer', 'test')"
)
NEW = (
    "trigger IN ('registration', 'payment', 'reminder', 'status_change', "
    "'email_confirm', 'course_request', 'certificate', 'blog_comment', "
    "'password_reset', 'backup_failure', 'backup_report', 'materials', "
    "'referral', 'meta_lead', 'transfer', 'quiz', 'test')"
)


def upgrade():
    with op.batch_alter_table('event_registrations', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'quiz_invite_sent_at', sa.DateTime(timezone=True), nullable=True))

    with op.batch_alter_table('email_logs', schema=None) as batch_op:
        batch_op.drop_constraint('ck_email_logs_trigger', type_='check')
        batch_op.create_check_constraint('ck_email_logs_trigger', NEW)


def downgrade():
    # Перед звуженням CHECK прибираємо рядки з 'quiz', інакше constraint не
    # створиться.
    op.execute("DELETE FROM email_logs WHERE \"trigger\" = 'quiz'")
    with op.batch_alter_table('email_logs', schema=None) as batch_op:
        batch_op.drop_constraint('ck_email_logs_trigger', type_='check')
        batch_op.create_check_constraint('ck_email_logs_trigger', OLD)

    with op.batch_alter_table('event_registrations', schema=None) as batch_op:
        batch_op.drop_column('quiz_invite_sent_at')
