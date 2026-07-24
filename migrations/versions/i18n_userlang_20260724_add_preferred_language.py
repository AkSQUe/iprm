"""i18n: users.preferred_language -- мова листів користувачу

Revision ID: i18n_userlang_20260724
Revises: i18n_translations_20260724
Create Date: 2026-07-24 16:31:00.000000

Мультимовність (Фаза 2, docs/i18n.md). NULL = українська (дефолт),
'ru'/'en' -- вибір користувача (реєстрація/кабінет). Використовується
для force_locale при фоновому рендері листів.
"""
from alembic import op
import sqlalchemy as sa


revision = 'i18n_userlang_20260724'
down_revision = 'i18n_translations_20260724'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('preferred_language', sa.String(length=5), nullable=True))


def downgrade():
    op.drop_column('users', 'preferred_language')
