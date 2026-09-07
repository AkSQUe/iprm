"""Перемикач способів оплати: LiqPay і рахунок на IBAN

Revision ID: pay_methods_20260907
Revises: transfer_min_days_20260907
Create Date: 2026-09-07 00:00:00.000000

site_settings.pay_liqpay_enabled / pay_invoice_enabled: які способи оплати
бачить покупець. Доти вибору не було -- показувались обидва завжди.

server_default = 'true' в обох: після міграції сайт поводиться точно як
досі, а вимикають спосіб у /admin/settings. Правило «обидва вимкнути не
можна» живе в коді (SiteSettings.enabled_payment_methods), а не в
CHECK-констрейнті: констрейнт на два стовпці не дав би адмінці зберегти
проміжний стан форми і перетворив би помилку користувача на 500.
"""
from alembic import op
import sqlalchemy as sa


revision = 'pay_methods_20260907'
down_revision = 'transfer_min_days_20260907'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('site_settings') as batch:
        batch.add_column(sa.Column(
            'pay_liqpay_enabled', sa.Boolean(), nullable=False,
            server_default='true',
        ))
        batch.add_column(sa.Column(
            'pay_invoice_enabled', sa.Boolean(), nullable=False,
            server_default='true',
        ))


def downgrade():
    with op.batch_alter_table('site_settings') as batch:
        batch.drop_column('pay_invoice_enabled')
        batch.drop_column('pay_liqpay_enabled')
