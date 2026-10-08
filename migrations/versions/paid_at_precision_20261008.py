"""Точність дати оплати: paid_at_precision на реєстраціях і покупках курсів

Revision ID: paid_at_precision_20261008
Revises: cert_counter_per_event_20260929
Create Date: 2026-10-08

Why
---
Ручна позначка оплати й команда backfill-paid-at записують дату з виписки
полуднем за Києвом. Споживач (MM Medic, XLSX) не відрізняв такий умовний
полудень від справжнього часу платежу й показував його як справжній.
Нова колонка каже, що відомо: 'datetime' -- момент, 'date' -- лише день.

Бекфіл
------
Рядок із paid_at рівно 12:00:00.000000 за Києвом -> 'date': так виглядає
лише результат paid_moment для минулої дати (LiqPay і "зараз" дають
довільні секунди й мікросекунди). Решта заповнених -> 'datetime'. Кожен
змінений рядок отримує updated_at = зараз: MM Medic тягне зміни за
updated_since і без цього нової точності не побачив би.

Правило рахується в Python, а не в SQL: міграції проганяються й на
SQLite, і саме тут його можна перевірити тестом.

CHECK
-----
Точність заповнена тоді й лише тоді, коли заповнена дата. На PostgreSQL --
NOT VALID і окремий VALIDATE: додавання не тримає блокування на час
перевірки всієї таблиці. На SQLite CHECK не додається (ALTER TABLE його не
вміє); тестова схема бере його з моделі через create_all.

Деплой
------
`flask db upgrade` іде ДО перезапуску. У проміжку старі воркери пишуть
paid_at без точності, і CHECK відкине такий запис: оплата, що прийде саме
в ці секунди, отримає помилку. Вікно -- секунди між міграцією і
`systemctl restart iprm` у deploy.yml. Таку оплату підбирає повторна
перевірка статусу (сторінка "оплату отримано", звірка зависних у
'pending'); якщо ні -- її видно в кабінеті LiqPay і в журналі помилок.
"""
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

from alembic import op
import sqlalchemy as sa


revision = 'paid_at_precision_20261008'
down_revision = 'cert_counter_per_event_20260929'
branch_labels = None
depends_on = None

KYIV = ZoneInfo('Europe/Kyiv')

# Мусять збігатися з app.models.mixins (PAID_AT_DATETIME / PAID_AT_DATE і
# paid_at_precision_sql): міграція не імпортує код застосунку.
PRECISION_DATETIME = 'datetime'
PRECISION_DATE = 'date'
CHECK_SQL = (
    '(paid_at IS NULL AND paid_at_precision IS NULL) OR '
    '(paid_at IS NOT NULL AND paid_at_precision IS NOT NULL '
    "AND paid_at_precision IN ('datetime', 'date'))"
)

TABLES = (
    ('event_registrations', 'ck_registrations_paid_at_precision'),
    ('online_enrollments', 'ck_online_enrollments_paid_at_precision'),
)


def precision_for(paid_at):
    """Точність для вже записаної дати оплати.

    SQLite віддає дату рядком і без зони -- вона в UTC (як `ensure_utc`).
    """
    if isinstance(paid_at, str):
        paid_at = datetime.fromisoformat(paid_at)
    if paid_at.tzinfo is None:
        paid_at = paid_at.replace(tzinfo=timezone.utc)
    if paid_at.astimezone(KYIV).time() == time(12):
        return PRECISION_DATE
    return PRECISION_DATETIME


def _backfill(bind, table, now):
    rows = bind.execute(sa.text(
        f'SELECT id, paid_at FROM {table} '
        'WHERE paid_at IS NOT NULL AND paid_at_precision IS NULL'
    )).fetchall()
    update = sa.text(
        f'UPDATE {table} SET paid_at_precision = :precision, updated_at = :now '
        'WHERE id IN :ids'
    ).bindparams(sa.bindparam('ids', expanding=True))
    for precision in (PRECISION_DATE, PRECISION_DATETIME):
        ids = [row.id for row in rows if precision_for(row.paid_at) == precision]
        if ids:
            bind.execute(update, {'precision': precision, 'now': now, 'ids': ids})


def upgrade():
    bind = op.get_bind()
    postgres = bind.dialect.name == 'postgresql'
    now = datetime.now(timezone.utc)

    for table, check in TABLES:
        if postgres:
            op.execute(f'ALTER TABLE {table} '
                       'ADD COLUMN IF NOT EXISTS paid_at_precision VARCHAR(8)')
        else:
            op.add_column(table, sa.Column('paid_at_precision', sa.String(8),
                                           nullable=True))

        _backfill(bind, table, now)

        if postgres:
            exists = bind.execute(
                sa.text('SELECT 1 FROM pg_constraint WHERE conname = :name'),
                {'name': check},
            ).first()
            if exists is None:
                op.execute(f'ALTER TABLE {table} ADD CONSTRAINT {check} '
                           f'CHECK ({CHECK_SQL}) NOT VALID')
            op.execute(f'ALTER TABLE {table} VALIDATE CONSTRAINT {check}')


def downgrade():
    bind = op.get_bind()
    postgres = bind.dialect.name == 'postgresql'
    for table, check in TABLES:
        if postgres:
            op.execute(f'ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {check}')
            op.execute(f'ALTER TABLE {table} DROP COLUMN IF EXISTS paid_at_precision')
        else:
            op.drop_column(table, 'paid_at_precision')
