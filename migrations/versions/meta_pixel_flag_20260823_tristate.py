"""Meta Pixel: тристанний прапорець (аварійний рубильник).

Revision ID: meta_pixel_flag_20260823
Revises: cookie_banner_20260823

Останній з трьох трекерів, де рубильник був зламаний. PostHog
(posthog_flags_20260823) і GA (ga_flag_20260823) уже полагоджені; Meta
лишалась зі старою логікою "прапорець дивиться на наявність ID В БД", тож
при ID з env галка в адмінці не робила нічого.

УВАГА: ця міграція НЕ обнуляє наявні значення, і це головна відмінність від
posthog_flags_20260823, де UPDATE ... SET NULL був обов'язковим.

Там колонки щойно створювались із server_default=false, тобто false у рядку
означав "ніхто не вирішував" -- і залишити його значило б мовчки вимкнути
трекінг, який працював зі змінних оточення.

Тут навпаки. У проді лежить meta_pixel_enabled = true разом із реальним ID
(1768257970972779), а env META_PIXEL_ENABLED не заданий узагалі. NULL тут
означав би "спитати env", env відповів би false -- і Pixel вимкнувся б,
забравши з собою вимірювання конверсій Facebook та Instagram. Наявне true --
це свідоме рішення адміністратора, і воно лишається явним.

Тобто після міграції поведінка не змінюється ані на проді, ані на dev.
"""
import sqlalchemy as sa
from alembic import op

revision = 'meta_pixel_flag_20260823'
down_revision = 'cookie_banner_20260823'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        batch_op.alter_column(
            'meta_pixel_enabled',
            existing_type=sa.Boolean(),
            nullable=True,
            server_default=None,
        )


def downgrade():
    # NULL (успадковано з env) найближче до false у двостанній схемі.
    op.execute(
        'UPDATE site_settings SET meta_pixel_enabled = '
        'COALESCE(meta_pixel_enabled, false)'
    )
    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        batch_op.alter_column(
            'meta_pixel_enabled',
            existing_type=sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        )
