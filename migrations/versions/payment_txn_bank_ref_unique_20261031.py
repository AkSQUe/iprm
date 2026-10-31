"""Журнал оплат: одна банківська операція -- один рядок

Revision ID: payment_txn_bank_ref_unique_20261031
Revises: payment_txn_bank_source_20261031
Create Date: 2026-10-31

Why
---
Ідемпотентність підтвердження оплати з виписки тримається на перевірці
«чи є вже рядок source='bank' з цим bank_tx_ref» під блокуванням рядка
замовлення. Блокування захищає одне замовлення, а та сама операція,
надіслана для двох різних замовлень, його обходить. Часткова унікальність
робить цей захист властивістю бази, а не лише порядку викликів у коді.

Деплой
------
Рядків source='bank' до цього релізу немає (джерело додала попередня
міграція), тож індекс будується миттєво й конфліктів не має. Для інших
джерел payment_id не обмежується: LiqPay повторює payment_id у callback.
"""
from alembic import op
import sqlalchemy as sa


revision = 'payment_txn_bank_ref_unique_20261031'
down_revision = 'payment_txn_bank_source_20261031'
branch_labels = None
depends_on = None

TABLE = 'payment_transactions'
INDEX = 'uq_payment_transactions_bank_ref'
WHERE = sa.text("source = 'bank'")


def upgrade():
    op.create_index(
        INDEX, TABLE, ['payment_id'], unique=True,
        postgresql_where=WHERE, sqlite_where=WHERE,
        if_not_exists=True,
    )


def downgrade():
    op.drop_index(INDEX, table_name=TABLE, if_exists=True)
