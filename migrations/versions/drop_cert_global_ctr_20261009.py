"""Прибрати загальні лічильники номерів сертифікатів із site_settings

Revision ID: drop_cert_global_ctr_20261009
Revises: trainer_recruit_20261009
Create Date: 2026-10-09

Why
---
Друга половина переходу на нумерацію в межах заходу
(``cert_counter_per_event_20260929``). Тоді колонки
``site_settings.bpr_participant_counter`` / ``bpr_lecturer_counter``
навмисно лишили в БД: між ``flask db upgrade`` і перезапуском старі воркери
ще читали site_settings повним переліком колонок, і видалення тим самим
кроком дало б 500 на всіх сторінках. Той код у проді з 29.09.2026 і колонок
не знає, тож тепер їх прибираємо.

Downgrade повертає колонки зі значеннями, з яких стара загальна нумерація
продовжиться без колізій: найбільший виданий порядковий сегмент (у тренерів
-- без зсуву 100000). Номери інших форм (``IPRM-2026-000001``)
пропускаються.

batch_alter_table -- бо міграції проганяються і на SQLite, де DROP COLUMN
через ALTER не скрізь підтримується.
"""
import re

from alembic import op
import sqlalchemy as sa


revision = 'drop_cert_global_ctr_20261009'
down_revision = 'trainer_recruit_20261009'
branch_labels = None
depends_on = None

# Мусить збігатися з app.models.lecturer_certificate.LECTURER_NUMBER_OFFSET.
LECTURER_NUMBER_OFFSET = 100000

_NUMBER_RE = re.compile(r'^\d+-\d+-\d+-(\d+)$')


def max_segment(numbers):
    """Найбільший порядковий сегмент серед номерів; 0 -- немає жодного."""
    segments = [int(m.group(1)) for m in
                (_NUMBER_RE.match((n or '').strip()) for n in numbers) if m]
    return max(segments, default=0)


def upgrade():
    with op.batch_alter_table('site_settings') as batch:
        batch.drop_column('bpr_lecturer_counter')
        batch.drop_column('bpr_participant_counter')


def downgrade():
    with op.batch_alter_table('site_settings') as batch:
        batch.add_column(sa.Column('bpr_participant_counter', sa.Integer(),
                                   nullable=False, server_default='0'))
        batch.add_column(sa.Column('bpr_lecturer_counter', sa.Integer(),
                                   nullable=False, server_default='0'))

    bind = op.get_bind()
    participant = max_segment(
        row[0] for row in bind.execute(sa.text('SELECT number FROM certificates')))
    lecturer = max(max_segment(
        row[0] for row in bind.execute(sa.text('SELECT number FROM lecturer_certificates'))
    ) - LECTURER_NUMBER_OFFSET, 0)
    bind.execute(sa.text(
        'UPDATE site_settings SET bpr_participant_counter = :p, '
        'bpr_lecturer_counter = :l'
    ), {'p': participant, 'l': lecturer})
