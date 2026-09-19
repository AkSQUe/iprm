"""Тригер листа 'trainer_proposal': пропозиція курсу з кабінету тренера.

Раніше лист куратору йшов під 'course_request', а dedup у EmailService
ключується на адресу+тригер з вікном 60 с: пропозиція тренера, заявка на
курс і B2B-заявка на ту саму адресу за хвилину зливались в один лист.
Власний тригер розводить ці події; дві різні пропозиції розрізняє ключ
ідемпотентності.

Без цього значення в CHECK INSERT у email_logs падає, і лист губиться
тихо -- тому тригер і CHECK змінюються разом, одним деплоєм.

CHECK перевипускається цілком через batch_alter_table (як у
quiz_invite_20260913).

Revision ID: email_trainer_proposal_20260919
Revises: trainer_cabinet_20260919
"""
from alembic import op

revision = 'email_trainer_proposal_20260919'
down_revision = 'trainer_cabinet_20260919'
branch_labels = None
depends_on = None

OLD = (
    "trigger IN ('registration', 'payment', 'reminder', 'status_change', "
    "'email_confirm', 'course_request', 'certificate', 'blog_comment', "
    "'password_reset', 'backup_failure', 'backup_report', 'materials', "
    "'referral', 'meta_lead', 'transfer', 'quiz', 'test')"
)
NEW = (
    "trigger IN ('registration', 'payment', 'reminder', 'status_change', "
    "'email_confirm', 'course_request', 'certificate', 'blog_comment', "
    "'password_reset', 'backup_failure', 'backup_report', 'materials', "
    "'referral', 'meta_lead', 'transfer', 'quiz', 'trainer_proposal', "
    "'test')"
)


def upgrade():
    with op.batch_alter_table('email_logs', schema=None) as batch_op:
        batch_op.drop_constraint('ck_email_logs_trigger', type_='check')
        batch_op.create_check_constraint('ck_email_logs_trigger', NEW)


def downgrade():
    # Старі листи про пропозиції повертаємо під 'course_request', під яким
    # вони й ішли до цієї ревізії: видаляти журнал доставки не треба, а
    # звужений CHECK інакше не створиться.
    op.execute(
        "UPDATE email_logs SET \"trigger\" = 'course_request' "
        "WHERE \"trigger\" = 'trainer_proposal'"
    )
    with op.batch_alter_table('email_logs', schema=None) as batch_op:
        batch_op.drop_constraint('ck_email_logs_trigger', type_='check')
        batch_op.create_check_constraint('ck_email_logs_trigger', OLD)
