"""i18n: JSON-колонка translations на контентних таблицях

Revision ID: i18n_translations_20260724
Revises: reviews_20260716
Create Date: 2026-07-24 16:30:00.000000

Мультимовність (Фаза 2, docs/i18n.md): переклади ru/en контенту БД.
Українська лишається в наявних колонках (канонічна), переклади -- у
JSON {"ru": {<поле>: <значення>}, "en": {...}} (TranslatableMixin,
app/models/mixins.py). Колонка nullable -- міграція additive і безпечна
для коду, що вже працює (старий код її не читає).
"""
from alembic import op
import sqlalchemy as sa


revision = 'i18n_translations_20260724'
down_revision = 'reviews_20260716'
branch_labels = None
depends_on = None

TABLES = (
    'courses',
    'course_tariffs',
    'instance_tariffs',
    'blog_posts',
    'trainers',
    'clinics',
    'program_blocks',
    'site_settings',
    'reviews',
)


def upgrade():
    for table in TABLES:
        op.add_column(table, sa.Column('translations', sa.JSON(), nullable=True))


def downgrade():
    for table in reversed(TABLES):
        op.drop_column(table, 'translations')
