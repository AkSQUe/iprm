"""Номер сертифіката більше не рахується як COUNT(*)

Revision ID: bpr_counter_20260817
Revises: partner_events_20260814
Create Date: 2026-08-17

Why
---
Сегмент «номер учасника» у номері сертифіката (РРРР-ПППП-ЗЗЗЗЗЗЗ-УУУУУУ)
збирався як ``COUNT(*) + 1`` по таблиці сертифікатів. За ручної видачі це
ніколи не проявлялось -- за весь час видано три сертифікати. Але видача
перестає бути ручною (автовидача після тестування), і обидва режими відмови
стають досяжними:

1. Дві одночасні видачі отримували ОДНЕ значення. Retry-петля при цьому не
   сходилась: після rollback вона перераховувала ту саму кількість, палила всі
   п'ять спроб і кидала RuntimeError.
2. Після видалення будь-якого сертифіката лічильник ішов НАЗАД і колізія з уже
   виданим номером ставала постійною -- видача ламалась назовсім.

Тому лічильники стають явними й монотонними: значення видаються під
блокуванням singleton-рядка ``site_settings`` (SELECT ... FOR UPDATE), тож
паралельні видачі не можуть узяти те саме, а видалення рядків на нумерацію
більше не впливає. Пропуски допустимі -- монотонність важливіша за щільність.

Окремі лічильники для учасників і лекторів: лекторські номери живуть у
діапазоні 1xxxxx (``LECTURER_NUMBER_OFFSET``), і спільний лічильник змішав би
діапазони.

Бекфіл
------
Стартові значення беремо з уже виданих номерів, щоб нумерація продовжилась, а
не почалась заново (інакше перший же новий номер зіткнувся б з наявним):

* учасники -- максимальний 4-й сегмент по ``certificates``;
* лектори -- максимальний 4-й сегмент по ``lecturer_certificates`` мінус зсув.

Номери, що не відповідають шаблону, у бекфілі не враховуються: у проді є один
legacy-рядок старого формату (``IPRM-2026-000001``), у якого 4-го сегмента
просто немає.

Розбір номерів зроблено у Python, а не через ``SPLIT_PART``/``~``: ті
конструкції є лише в Postgres, а міграції в цьому проєкті прогоняються і на
SQLite (див. tests/test_db/test_migration_i18n_srckey.py). Рядків тут одиниці,
тож ціна вибірки нульова.
"""
import re

from alembic import op
import sqlalchemy as sa


revision = 'bpr_counter_20260817'
down_revision = 'partner_events_20260814'
branch_labels = None
depends_on = None

# Мусить збігатися з app.models.lecturer_certificate.LECTURER_NUMBER_OFFSET.
LECTURER_NUMBER_OFFSET = 100000

# Тільки 4-сегментні номери з цифр -- саме з них можна взяти сегмент учасника.
_NUMBER_RE = re.compile(r'^\d{4}-\d+-\d+-(\d+)$')


def _segment_of(number):
    """Сегмент "номер учасника" з номера; None -- номер не того формату.

    Легасі-номери (напр. ``IPRM-2026-000001``) 4-го сегмента не мають і мусять
    бути проігноровані, а не впасти на int().
    """
    match = _NUMBER_RE.match((number or '').strip())
    return int(match.group(1)) if match else None


def _max_segment(bind, table):
    """Максимальний сегмент "номер учасника" серед номерів таблиці."""
    rows = bind.execute(sa.text(f'SELECT number FROM {table}')).fetchall()
    segments = [s for s in (_segment_of(row[0]) for row in rows) if s is not None]
    return max(segments) if segments else 0


def upgrade():
    op.add_column('site_settings', sa.Column(
        'bpr_participant_counter', sa.Integer(),
        nullable=False, server_default='0',
    ))
    op.add_column('site_settings', sa.Column(
        'bpr_lecturer_counter', sa.Integer(),
        nullable=False, server_default='0',
    ))

    bind = op.get_bind()
    participant = _max_segment(bind, 'certificates')
    # Лекторські номери зберігаються ВЖЕ зі зсувом -- у лічильнику тримаємо
    # значення без нього, бо зсув додається при видачі.
    lecturer = max(_max_segment(bind, 'lecturer_certificates') - LECTURER_NUMBER_OFFSET, 0)

    bind.execute(sa.text(
        'UPDATE site_settings SET bpr_participant_counter = :p, '
        'bpr_lecturer_counter = :l'
    ), {'p': participant, 'l': lecturer})


def downgrade():
    op.drop_column('site_settings', 'bpr_lecturer_counter')
    op.drop_column('site_settings', 'bpr_participant_counter')
