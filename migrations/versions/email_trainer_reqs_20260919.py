"""Тригер листа 'trainer_requisites': тренер змінив реквізити в анкеті.

Реквізити (IBAN, РНОКПП, номер картки, ідентифікаційний код) -- куди йде
гонорар. Їх тиха заміна (помилка тренера чи чужий доступ до акаунта)
означала б переказ не туди, тож куратор отримує лист. Власний тригер, а не
'trainer_proposal': ці події не мають зливатися в dedup, і журнал листів
має їх розрізняти.

Без цього значення в CHECK INSERT у email_logs падає, і лист губиться
тихо -- тому тригер і CHECK змінюються разом, одним деплоєм.

CHECK перевипускається цілком через batch_alter_table (як у
email_trainer_proposal_20260919).

Revision ID: email_trainer_reqs_20260919
Revises: email_trainer_proposal_20260919
"""
from alembic import op

revision = 'email_trainer_reqs_20260919'
down_revision = 'email_trainer_proposal_20260919'
branch_labels = None
depends_on = None

OLD = (
    "trigger IN ('registration', 'payment', 'reminder', 'status_change', "
    "'email_confirm', 'course_request', 'certificate', 'blog_comment', "
    "'password_reset', 'backup_failure', 'backup_report', 'materials', "
    "'referral', 'meta_lead', 'transfer', 'quiz', 'trainer_proposal', "
    "'test')"
)
NEW = (
    "trigger IN ('registration', 'payment', 'reminder', 'status_change', "
    "'email_confirm', 'course_request', 'certificate', 'blog_comment', "
    "'password_reset', 'backup_failure', 'backup_report', 'materials', "
    "'referral', 'meta_lead', 'transfer', 'quiz', 'trainer_proposal', "
    "'trainer_requisites', 'test')"
)


def upgrade():
    with op.batch_alter_table('email_logs', schema=None) as batch_op:
        batch_op.drop_constraint('ck_email_logs_trigger', type_='check')
        batch_op.create_check_constraint('ck_email_logs_trigger', NEW)


def downgrade():
    # До цієї ревізії такого листа не було, тож «повернути під старий тригер»
    # нікуди. Журнал доставки не видаляємо -- ставимо найближчий за змістом
    # 'trainer_proposal' (лист куратору з кабінету тренера), інакше звужений
    # CHECK не створиться.
    op.execute(
        "UPDATE email_logs SET \"trigger\" = 'trainer_proposal' "
        "WHERE \"trigger\" = 'trainer_requisites'"
    )
    with op.batch_alter_table('email_logs', schema=None) as batch_op:
        batch_op.drop_constraint('ck_email_logs_trigger', type_='check')
        batch_op.create_check_constraint('ck_email_logs_trigger', OLD)
