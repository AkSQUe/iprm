"""Обкладинка онлайн-курсу з Sintegrum

Revision ID: online_cover_20260817
Revises: promo_online_20260817
Create Date: 2026-08-17 19:05:00.000000

Фід Sintegrum віддає недокументоване `avatar_link` -- публічне посилання на
файл обкладинки. Ми затягуємо картинку у власний медіа-реєстр (WebP +
варіант `card`), а тут з'являється мітка про те, З ЯКОГО посилання зроблено
поточну `card_media`.

Без цієї мітки синхронізація не змогла б відрізнити три випадки: своєї
картинки ще немає, картинку затягнули ми (можна оновити), картинку поставила
людина (чіпати не можна). Порівнюємо саме посилання, а не `avatar_id`: коли
файл на тому боці підмінюють, змінюється токен в URL.

Колонка nullable і нічого не переносить: для наявних курсів вона порожня,
тобто перший же прогін синхронізації затягне обкладинки.
"""
from alembic import op
import sqlalchemy as sa


revision = 'online_cover_20260817'
down_revision = 'promo_online_20260817'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('online_courses') as batch:
        batch.add_column(sa.Column('card_avatar_src', sa.String(1000), nullable=True))


def downgrade():
    with op.batch_alter_table('online_courses') as batch:
        batch.drop_column('card_avatar_src')
