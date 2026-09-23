"""Таблиця email_attachments: вкладення листа для повторної відправки.

Автоповтор після тимчасового збою SMTP (retry_failed_emails) і кнопка
«переслати» в адмінці (manual_resend) збирали лист заново лише з
EmailLog.html_body -- без вкладень. Рахунок до оплати, календарне
запрошення й сертифікати учасника та лектора йшли повторно БЕЗ файлу, про
який у листі написано.

Байти (data) тримаються лише доти, доки лист може знадобитися відправити
знову: після успіху їх стирає код, для листа, що не дійшов, -- через 7 днів
(email_service.ATTACHMENT_FAILED_RETENTION_DAYS). Рядок із data IS NULL --
маркер «вкладення було», за яким повторна відправка відмовляє замість слати
лист без файлу. Бекфілу немає: для вже надісланих листів байтів ніде нема.

Revision ID: email_attachments_20260923
Revises: trainer_prof_certs_20260922
"""
import sqlalchemy as sa
from alembic import op

revision = 'email_attachments_20260923'
down_revision = 'trainer_prof_certs_20260922'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'email_attachments',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('email_log_id', sa.BigInteger(),
                  sa.ForeignKey('email_logs.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('filename', sa.String(length=255), nullable=False),
        sa.Column('mimetype', sa.String(length=100), nullable=False),
        sa.Column('data', sa.LargeBinary()),
        sa.Column('created_at', sa.DateTime(timezone=True)),
        sa.Column('updated_at', sa.DateTime(timezone=True)),
    )
    op.create_index('ix_email_attachments_email_log_id', 'email_attachments',
                    ['email_log_id'])


def downgrade():
    op.drop_index('ix_email_attachments_email_log_id', table_name='email_attachments')
    op.drop_table('email_attachments')
