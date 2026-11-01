"""email_attachments.content_id: вбудовані зображення листа (CID)

Revision ID: email_attach_cid_20261101
Revises: pay_txn_bank_ref_uniq_20261031
Create Date: 2026-11-01

Why
---
Лист «Реєстрацію підтверджено» несе платіжний QR вбудованим зображенням:
HTML посилається на нього як `cid:<content_id>`. Автоповтор після збою SMTP
і кнопка «переслати» збирають лист зі збереженого журналу, тож content_id
мусить зберігатися поруч із байтами -- інакше QR поїде звичайним
вкладенням, а в листі лишиться порожня рамка.

Деплой
------
Nullable-колонка без значення за замовчуванням: на PostgreSQL це зміна лише
каталогу, без перезапису таблиці. Старий код колонку ігнорує, тож порядок
«міграція -> перезапуск» безпечний. Downgrade прибирає колонку; вкладення,
що чекають повтору, після нього підуть звичайними файлами.
"""
import sqlalchemy as sa
from alembic import op


revision = 'email_attach_cid_20261101'
down_revision = 'pay_txn_bank_ref_uniq_20261031'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name == 'postgresql':
        op.execute('ALTER TABLE email_attachments '
                   'ADD COLUMN IF NOT EXISTS content_id VARCHAR(255)')
    else:
        with op.batch_alter_table('email_attachments') as batch:
            batch.add_column(sa.Column('content_id', sa.String(length=255)))


def downgrade():
    with op.batch_alter_table('email_attachments') as batch:
        batch.drop_column('content_id')
