"""Довідник видів заходів БПР

Revision ID: bpr_event_types_20260909
Revises: transfer_after_days_20260908
Create Date: 2026-09-09 00:00:00.000000

Створює таблицю event_types, сідає номенклатуру, знімає CHECK із
courses.event_type і додає перевизначення типу проведенню.
"""
from alembic import op
import sqlalchemy as sa


revision = 'bpr_event_types_20260909'
down_revision = 'transfer_after_days_20260908'
branch_labels = None
depends_on = None


# Копія app.models.event_type.SEED_ROWS, свідома: міграція -- застигла
# історія, і імпорт з моделі означав би, що вже застосована ревізія
# змінює поведінку разом із наступними правками номенклатури.
# Розбіжність ловить tests/test_db/test_migration_bpr_event_types.py.
SEED_ROWS = (
    {'code': 'seminar', 'name': 'Семінар',
     'name_accusative': 'семінар', 'name_genitive': 'семінару',
     'sort_order': 1, 'is_active': True},
    {'code': 'scientific_conference', 'name': 'Наукова конференція',
     'name_accusative': 'наукову конференцію',
     'name_genitive': 'наукової конференції',
     'sort_order': 2, 'is_active': True},
    {'code': 'elearning_course', 'name': 'Електронний навчальний курс',
     'name_accusative': 'електронний навчальний курс',
     'name_genitive': 'електронного навчального курсу',
     'sort_order': 3, 'is_active': True},
    {'code': 'congress', 'name': 'Конгрес',
     'name_accusative': 'конгрес', 'name_genitive': 'конгресу',
     'sort_order': 4, 'is_active': True},
    {'code': 'practical_conference', 'name': 'Науково-практична конференція',
     'name_accusative': 'науково-практичну конференцію',
     'name_genitive': 'науково-практичної конференції',
     'sort_order': 5, 'is_active': True},
    {'code': 'symposium', 'name': 'Симпозіум',
     'name_accusative': 'симпозіум', 'name_genitive': 'симпозіуму',
     'sort_order': 6, 'is_active': True},
    {'code': 'convention', 'name': 'З\'їзд',
     'name_accusative': 'з\'їзд', 'name_genitive': 'з\'їзду',
     'sort_order': 7, 'is_active': True},
    {'code': 'simulation_training', 'name': 'Симуляційний тренінг',
     'name_accusative': 'симуляційний тренінг',
     'name_genitive': 'симуляційного тренінгу',
     'sort_order': 8, 'is_active': True},
    {'code': 'skills_training',
     'name': 'Тренінг з оволодіння практичними навичками',
     'name_accusative': 'тренінг з оволодіння практичними навичками',
     'name_genitive': 'тренінгу з оволодіння практичними навичками',
     'sort_order': 9, 'is_active': True},
    {'code': 'training', 'name': 'Тренінг',
     'name_accusative': 'тренінг', 'name_genitive': 'тренінгу',
     'sort_order': 10, 'is_active': True},
    {'code': 'masterclass', 'name': 'Майстер-клас',
     'name_accusative': 'майстер-клас', 'name_genitive': 'майстер-класу',
     'sort_order': 11, 'is_active': True},
    {'code': 'professional_school', 'name': 'Фахова (тематична) школа',
     'name_accusative': 'фахову (тематичну) школу',
     'name_genitive': 'фахової (тематичної) школи',
     'sort_order': 12, 'is_active': True},
    {'code': 'course', 'name': 'Курс',
     'name_accusative': 'курс', 'name_genitive': 'курсу',
     'sort_order': 90, 'is_active': False},
    {'code': 'webinar', 'name': 'Вебінар',
     'name_accusative': 'вебінар', 'name_genitive': 'вебінару',
     'sort_order': 91, 'is_active': False},
    {'code': 'conference', 'name': 'Конференція',
     'name_accusative': 'конференцію', 'name_genitive': 'конференції',
     'sort_order': 92, 'is_active': False},
)


def upgrade():
    op.create_table(
        'event_types',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('code', sa.String(length=30), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('name_accusative', sa.String(length=120), nullable=True),
        sa.Column('name_genitive', sa.String(length=120), nullable=True),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('translations', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code', name='uq_event_types_code'),
    )
    op.create_index('ix_event_types_is_active', 'event_types', ['is_active'])

    # sa.table/sa.column, а не return-значення create_table: bulk_insert
    # уникає dialect-специфічного синтаксису серіалізації.
    seed_table = sa.table(
        'event_types',
        sa.column('code', sa.String),
        sa.column('name', sa.String),
        sa.column('name_accusative', sa.String),
        sa.column('name_genitive', sa.String),
        sa.column('sort_order', sa.Integer),
        sa.column('is_active', sa.Boolean),
    )
    op.bulk_insert(seed_table, [dict(row) for row in SEED_ROWS])

    # CHECK перелічував п'ять старих кодів. Тепер перелік живе в довіднику,
    # а не в схемі: інакше кожна зміна номенклатури тягла б міграцію, чого
    # ця задача якраз і позбувається.
    bind = op.get_bind()
    if bind.dialect.name != 'sqlite':
        # IF EXISTS: продова послідовність констрейнт має (ставить
        # d1e2f3a4b5c6), але Postgres-база, піднята напряму через
        # db.create_all() (dev/тести), його не отримує -- без IF EXISTS
        # міграція там аварійно спинялась би на цьому кроці.
        op.execute('ALTER TABLE courses DROP CONSTRAINT IF EXISTS ck_courses_event_type')

    op.add_column('course_instances',
                  sa.Column('event_type', sa.String(length=30), nullable=True))


def downgrade():
    op.drop_column('course_instances', 'event_type')

    # Односторонній крок: курси, яким уже проставили новий код
    # (congress, convention, ...), цей CHECK не пройдуть. Перед відкатом
    # такі курси треба повернути на старі п'ять кодів вручну.
    bind = op.get_bind()
    if bind.dialect.name != 'sqlite':
        op.create_check_constraint(
            'ck_courses_event_type', 'courses',
            "event_type IN ('seminar', 'webinar', 'course', 'masterclass', 'conference')",
        )

    op.drop_index('ix_event_types_is_active', table_name='event_types')
    op.drop_table('event_types')
