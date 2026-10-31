"""Журнал оплат: джерело 'bank' (підтвердження оплати з банківської виписки)

Revision ID: payment_txn_bank_source_20261031
Revises: cancelled_at_20261010
Create Date: 2026-10-31

Why
---
Сайт mm-medic звіряє банківську виписку і просить ІПРМ підтвердити
реєстрацію, оплачену переказом. Такий платіж пишеться в журнал оплат з
джерелом 'bank', якого CHECK ck_payment_transactions_source досі не знав.

Деплой
------
Міграція йде ДО перезапуску, а нове джерело пише лише новий код, тож
розширення списку допустимих значень безпечне в будь-якому порядку.
На PostgreSQL обмеження додається NOT VALID: наявні рядки задовольняють і
старий список, а блокування на час повної перевірки таблиці не потрібне.
На SQLite -- batch_alter_table (ALTER TABLE не вміє міняти CHECK).
"""
from alembic import op


revision = 'payment_txn_bank_source_20261031'
down_revision = 'cancelled_at_20261010'
branch_labels = None
depends_on = None

TABLE = 'payment_transactions'
CHECK = 'ck_payment_transactions_source'
NEW_SQL = "source IN ('callback', 'status_check', 'refund', 'manual', 'bank')"
OLD_SQL = "source IN ('callback', 'status_check', 'refund', 'manual')"


def _swap(check_sql):
    bind = op.get_bind()
    if bind.dialect.name == 'postgresql':
        op.execute(f'ALTER TABLE {TABLE} DROP CONSTRAINT IF EXISTS {CHECK}')
        op.execute(f'ALTER TABLE {TABLE} ADD CONSTRAINT {CHECK} '
                   f'CHECK ({check_sql}) NOT VALID')
    else:
        with op.batch_alter_table(TABLE) as batch:
            batch.drop_constraint(CHECK, type_='check')
            batch.create_check_constraint(CHECK, check_sql)


def upgrade():
    _swap(NEW_SQL)


def downgrade():
    # Рядки з джерелом 'bank' не пройдуть старий CHECK -- прибираємо їх,
    # інакше відкат міграції впаде на валідації (SQLite) або лишить
    # непідтверджене обмеження (PostgreSQL).
    op.execute(f"DELETE FROM {TABLE} WHERE source = 'bank'")
    _swap(OLD_SQL)
