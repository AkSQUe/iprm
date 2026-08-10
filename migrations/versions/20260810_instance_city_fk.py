"""Місто проведення окремим полем + сід довідника й бекфіл

Партнерська вітрина (MM Medic) будує публічний розклад із фасетом «Місто».
Взяти місто було нізвідки: `course_instances.location` -- вільний текст, у
якому впереміш і голі назви ("Харків"), і повні адреси ("м. Харків, вул.
Григорія Сковороди, 80, ДУ ..."), а таблиця `cities` у проді ПОРОЖНЯ, тобто
словниковий шар, задуманий для перекладу назв, ніколи не наповнювався.

Розбирати адресу на місто в рантаймі означало б вгадувати -- саме тому
`app/services/city_glossary.py` свідомо цього не робить. Тому місто стає
окремим необов'язковим полем, а `location` лишається адресою для людини.

Бекфіл спирається на ПОВНИЙ перелік написань, що реально є в базі (9 рядків
на 106 проведень), тому підстановка тут не евристика, а закритий список:

    Київ, вул. Андрія Верхогляда, 2а            -> Київ   (x7)
    Харків                                      -> Харків (x4)
    Варшава                                     -> Варшава(x2)
    Одеса                                       -> Одеса  (x2)
    Рівне                                       -> Рівне  (x1)
    м. Одеса вул. Канатна 36                    -> Одеса  (x1)
    Київ                                        -> Київ   (x1)
    м. Харків, вул. Григорія Сковороди, 80, ... -> Харків (x1)
    м. Київ                                     -> Київ   (x1)

86 зі 106 проведень локації не мають узагалі -- їм city_id лишається NULL, і
це не помилка міграції, а стан даних. Розклад показує такі заходи з підписом
«Місце уточнюється»; заповнити їх можна пікером в адмінці.

Revision ID: instance_city_20260810
Revises: reg_email_delay_20260806
Create Date: 2026-08-10
"""
from alembic import op
import sqlalchemy as sa


revision = 'instance_city_20260810'
down_revision = 'reg_email_delay_20260806'
branch_labels = None
depends_on = None


# Місто -> написання location, які на нього вказують (у нормалізованій формі:
# без крайніх пробілів, нижній регістр, стиснуті внутрішні пробіли).
CITY_LOCATIONS = {
    'Київ': (
        'київ, вул. андрія верхогляда, 2а',
        'київ',
        'м. київ',
    ),
    'Харків': (
        'харків',
        'м. харків, вул. григорія сковороди, 80, ду «іпхс ім. проф. м. і. ситенка намн україни»',
    ),
    'Одеса': (
        'одеса',
        'м. одеса вул. канатна 36',
    ),
    'Варшава': (
        'варшава',
    ),
    'Рівне': (
        'рівне',
    ),
}


def _normalize(text):
    return ' '.join((text or '').split()).lower()


def upgrade():
    op.add_column(
        'course_instances',
        sa.Column('city_id', sa.BigInteger(), nullable=True),
    )
    op.create_index(
        'ix_course_instances_city_id', 'course_instances', ['city_id'],
    )
    op.create_foreign_key(
        'fk_course_instances_city_id', 'course_instances', 'cities',
        ['city_id'], ['id'], ondelete='SET NULL',
    )

    conn = op.get_bind()

    # 1. Довідник. Ідемпотентно: місто могли вже завести руками в адмінці.
    city_ids = {}
    for name in CITY_LOCATIONS:
        normalized = _normalize(name)
        existing = conn.execute(
            sa.text('SELECT id FROM cities WHERE name_normalized = :n'),
            {'n': normalized},
        ).scalar()
        if existing is None:
            existing = conn.execute(
                sa.text(
                    'INSERT INTO cities (name, name_normalized, created_at, updated_at) '
                    'VALUES (:name, :n, now(), now()) RETURNING id'
                ),
                {'name': name, 'n': normalized},
            ).scalar()
        city_ids[name] = existing

    # 2. Бекфіл. Нормалізація свідомо в Python, а не в SQL: так міграція не
    # залежить ні від діалекту (`regexp_replace` є не скрізь), ні від того, як
    # драйвер біндить масив у `= ANY(...)`. Порівняння йде за ТОЧНИМ рядком,
    # який реально лежить у базі.
    rows = conn.execute(
        sa.text(
            'SELECT DISTINCT location FROM course_instances '
            "WHERE location IS NOT NULL AND location <> ''"
        )
    ).fetchall()

    location_to_city = {}
    for name, normalized_forms in CITY_LOCATIONS.items():
        for form in normalized_forms:
            location_to_city[form] = name

    for (location,) in rows:
        city_name = location_to_city.get(_normalize(location))
        if city_name is None:
            # Незнайоме написання -- лишаємо порожнім. Вгадувати місто з адреси
            # означало б помилятися мовчки; порожнє поле видно в адмінці.
            continue
        # Тільки там, де місто ще не проставлене: повторний прогін не перетирає
        # ручних рішень.
        conn.execute(
            sa.text(
                'UPDATE course_instances SET city_id = :city_id '
                'WHERE city_id IS NULL AND location = :location'
            ),
            {'city_id': city_ids[city_name], 'location': location},
        )


def downgrade():
    op.drop_constraint(
        'fk_course_instances_city_id', 'course_instances', type_='foreignkey',
    )
    op.drop_index('ix_course_instances_city_id', table_name='course_instances')
    op.drop_column('course_instances', 'city_id')
    # Рядки довідника НЕ видаляємо: їх могли доповнити перекладами й
    # використати деінде, а `location` від них не залежить.
