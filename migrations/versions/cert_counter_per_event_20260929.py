"""Нумерація сертифікатів у межах заходу: лічильник на кожен префікс

Revision ID: cert_counter_per_event_20260929
Revises: trainer_presentations_20260924
Create Date: 2026-09-29

Why
---
Сегмент «номер учасника» (РРРР-ПППП-ЗЗЗЗЗЗЗ-УУУУУУ) видавався одним
лічильником на весь сайт (site_settings.bpr_participant_counter /
bpr_lecturer_counter). Через це номери заходу йшли не з одиниці, а
сертифікат, дописаний до минулого заходу після видачі наступного, отримував
номер з-за хвоста наступного -- у звіті реєстру вони перемішувались.

Тепер лічильник свій у кожного заходу: таблиця certificate_number_counters,
ключ -- (префікс РРРР-ПППП-ЗЗЗЗЗЗЗ, вид).

Бекфіл
------
Для кожного префікса, що вже трапляється у виданих номерах, лічильник =
максимальний порядковий сегмент у ньому (у тренерів -- без зсуву 100000).
Інакше перша ж нова видача в заході з уже виданими сертифікатами взяла б
000001 і наткнулась на зайнятий номер. Легасі-номери іншої форми
(``IPRM-2026-000001``) пропускаються. Уже видані номери не змінюються:
перенумерувати захід -- окрема явна дія адміна в картці проведення.

Колонки site_settings НЕ видаляються тут
----------------------------------------
Деплой -- ``flask db upgrade``, а потім перезапуск: у проміжку старі воркери
ще живі й читають site_settings на кожному запиті повним переліком колонок.
Видалення колонок цим же кроком дало б 500 на всіх сторінках до
перезапуску. Модель їх більше не знає (у них server_default 0, тож вставки не
страждають); прибрати -- окремою міграцією в наступному релізі.

Розбір номерів -- у Python, а не через SPLIT_PART: міграції проганяються і на
SQLite.
"""
import re

from alembic import op
import sqlalchemy as sa


revision = 'cert_counter_per_event_20260929'
down_revision = 'trainer_presentations_20260924'
branch_labels = None
depends_on = None

# Мусить збігатися з app.models.lecturer_certificate.LECTURER_NUMBER_OFFSET.
LECTURER_NUMBER_OFFSET = 100000

_NUMBER_RE = re.compile(r'^(\d+-\d+-\d+)-(\d+)$')


def split_number(number):
    """(префікс, порядковий) або None для номера іншої форми."""
    match = _NUMBER_RE.match((number or '').strip())
    return (match.group(1), int(match.group(2))) if match else None


def collect_counters(participant_numbers, lecturer_numbers):
    """{(префікс, вид): останній порядковий} з уже виданих номерів.

    Тренерський сегмент зберігається зі зсувом, а лічильник -- без нього
    (зсув додається при видачі).
    """
    counters = {}
    for kind, numbers, offset in (
        ('participant', participant_numbers, 0),
        ('lecturer', lecturer_numbers, LECTURER_NUMBER_OFFSET),
    ):
        for number in numbers:
            parsed = split_number(number)
            if parsed is None:
                continue
            prefix, segment = parsed
            value = max(segment - offset, 0)
            key = (prefix, kind)
            counters[key] = max(counters.get(key, 0), value)
    return counters


def upgrade():
    counters_table = op.create_table(
        'certificate_number_counters',
        sa.Column('prefix', sa.String(length=64), nullable=False),
        sa.Column('kind', sa.String(length=20), nullable=False),
        sa.Column('last_value', sa.Integer(), nullable=False, server_default='0'),
        sa.CheckConstraint(
            "kind IN ('participant', 'lecturer')",
            name='ck_certificate_number_counters_kind',
        ),
        sa.PrimaryKeyConstraint('prefix', 'kind'),
    )

    bind = op.get_bind()
    participant = [row[0] for row in bind.execute(sa.text('SELECT number FROM certificates'))]
    lecturer = [row[0] for row in bind.execute(sa.text('SELECT number FROM lecturer_certificates'))]
    rows = [
        {'prefix': prefix, 'kind': kind, 'last_value': value}
        for (prefix, kind), value in sorted(collect_counters(participant, lecturer).items())
    ]
    if rows:
        op.bulk_insert(counters_table, rows)


def downgrade():
    # Колонки site_settings цей крок не чіпав: стара нумерація після відкату
    # продовжиться з загального лічильника, а номер, що встиг зайняти
    # лічильник заходу, стара видача й так пропускає (_next_free_number).
    op.drop_table('certificate_number_counters')
