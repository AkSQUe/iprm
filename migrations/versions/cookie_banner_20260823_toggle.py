"""Тумблер банера про cookie.

Revision ID: cookie_banner_20260823
Revises: ga_flag_20260823

Двостанний прапорець, а не тристанний як у GA/PostHog: тут немає
env-fallback'а, з яким треба було б розводити "не задано" і "вимкнено". Це
чисто відображення, а не інтеграція з чужим сервісом.

server_default=true обов'язковий: колонка NOT NULL, і без нього ALTER впав би
на наявному рядку. Значення true зберігає поточну поведінку -- банер
показується доти, доки адмін свідомо не зніме галку.
"""
import sqlalchemy as sa
from alembic import op

revision = 'cookie_banner_20260823'
down_revision = 'ga_flag_20260823'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'show_cookie_banner', sa.Boolean(),
            server_default=sa.true(), nullable=False))


def downgrade():
    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        batch_op.drop_column('show_cookie_banner')
