"""Формат участі в тарифі проведення

Revision ID: instance_tariff_format_20260731
Revises: cities_glossary_20260731
Create Date: 2026-07-31 12:00:00.000000

instance_tariffs.event_format ('online'|'offline'|NULL). Шаблонний
course_tariffs.event_format існував і раніше, але при копіюванні у
проведення губився -- тариф проведення не знав, очна це участь чи ні.

Через це на ГІБРИДНОМУ проведенні форма реєстрації вимагала підтвердження
"я точно приїду" навіть у того, хто обрав онлайн-тариф.

Бекфіл: зіставляємо тариф проведення з активним шаблоном того самого курсу
за назвою (копіювання переносить назву дослівно). Неоднозначні збіги й
відсутні шаблони лишаємо NULL -- код трактує NULL як очну участь, тобто
поведінка не змінюється, доки адмін не проставить формат явно.
"""
from alembic import op
import sqlalchemy as sa


revision = 'instance_tariff_format_20260731'
down_revision = 'cities_glossary_20260731'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('instance_tariffs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('event_format', sa.String(length=20),
                                      nullable=True))
        batch_op.create_check_constraint(
            'ck_instance_tariffs_event_format',
            "event_format IN ('online', 'offline') OR event_format IS NULL",
        )

    conn = op.get_bind()
    # Один шаблон на (курс, назва) -- інакше не вгадаємо, з якого копіювали.
    rows = conn.execute(sa.text("""
        SELECT it.id AS tariff_id, ct.event_format AS fmt
        FROM instance_tariffs it
        JOIN course_instances ci ON ci.id = it.instance_id
        JOIN course_tariffs ct ON ct.course_id = ci.course_id
                              AND ct.name = it.name
        WHERE ct.event_format IS NOT NULL
    """)).mappings().all()

    counts = {}
    for row in rows:
        counts[row['tariff_id']] = counts.get(row['tariff_id'], 0) + 1

    filled = 0
    for row in rows:
        if counts[row['tariff_id']] != 1:
            continue  # неоднозначно -- лишаємо NULL
        conn.execute(
            sa.text('UPDATE instance_tariffs SET event_format = :fmt '
                    'WHERE id = :id'),
            {'fmt': row['fmt'], 'id': row['tariff_id']},
        )
        filled += 1

    print(f'  instance_tariff_format: проставлено формат для {filled} тарифів '
          f'із {len(counts)} зіставлених')


def downgrade():
    with op.batch_alter_table('instance_tariffs', schema=None) as batch_op:
        batch_op.drop_constraint('ck_instance_tariffs_event_format',
                                 type_='check')
        batch_op.drop_column('event_format')
