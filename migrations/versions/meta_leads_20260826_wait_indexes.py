"""Індекси під реальні зрізи реєстру лідів Meta.

Наявні однокололонкові індекси (`created_time`, `status`, `is_test`,
`deleted_at`) не покривають жодного із двох запитів, які сторінка виконує
на кожен рендер:

  * типовий зріз -- `deleted_at IS NULL AND is_test = false`
    ORDER BY `created_time DESC`. Композита під нього не було, а
    `ix_meta_leads_status_created` без фільтра статусу не застосовна;
  * порядок «спершу ті, до кого не дійшли руки» -- ORDER BY
    `first_touch_at IS NULL DESC, created_time ASC` на тому самому зрізі.

Обидва -- часткові індекси: рядки видалених і тестових заявок у них не
потрапляють узагалі, тож індекс лишається малим незалежно від того,
скільки сміття накопичить Lead Ads Testing Tool.

Індекси ДОДАЮТЬСЯ, нічого не знімається: три булеві однокололонкові
(`needs_attention`, `is_repeat`, `is_test`) планувальник на низькій
кардинальності майже не бере, але їхнє прибирання -- окреме рішення, а не
побічний ефект цієї міграції.

Revision ID: meta_leads_wait_idx_20260826
Revises: meta_pixel_flag_20260823
"""
import sqlalchemy as sa
from alembic import op

revision = 'meta_leads_wait_idx_20260826'
down_revision = 'meta_pixel_flag_20260823'
branch_labels = None
depends_on = None


_ACTIVE = 'deleted_at IS NULL AND is_test = false'


def upgrade():
    op.create_index(
        'ix_meta_leads_active_created', 'meta_leads',
        [sa.text('created_time DESC')],
        postgresql_where=sa.text(_ACTIVE),
    )
    op.create_index(
        'ix_meta_leads_active_wait', 'meta_leads',
        [sa.text('(first_touch_at IS NULL) DESC'), sa.text('created_time ASC')],
        postgresql_where=sa.text(_ACTIVE),
    )


def downgrade():
    op.drop_index('ix_meta_leads_active_wait', table_name='meta_leads')
    op.drop_index('ix_meta_leads_active_created', table_name='meta_leads')
