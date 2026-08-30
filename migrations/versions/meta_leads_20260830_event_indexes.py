"""Індекси черги подій Meta за часом ПРИЙОМУ.

`meta_lead_events` мала індекс на `created_time` -- це час ліда за версією
Meta. Реєстр черги сортується не ним, а `received_at` (час, коли вебхук
дійшов до нас), і на цю колонку індексу не було зовсім: кожен рендер
`/admin/meta-leads/events` сортував таблицю цілком.

Другий індекс -- той самий порядок у межах статусу. Його беруть два
споживачі: зріз черги за статусом і лічильник «збоїв за добу» на сторінці
налаштувань (`status = 'failed' AND received_at >= now() - 1 day`).
Наявний `ix_meta_lead_events_status_retry` тут не застосовний: його друга
колонка -- `next_retry_at`, вона про план повторів, а не про прийом.

Revision ID: meta_lead_events_idx_20260830
Revises: meta_form_schema_20260830
"""
import sqlalchemy as sa
from alembic import op

revision = 'meta_lead_events_idx_20260830'
down_revision = 'meta_form_schema_20260830'
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        'ix_meta_lead_events_received', 'meta_lead_events',
        [sa.text('received_at DESC')],
    )
    op.create_index(
        'ix_meta_lead_events_status_received', 'meta_lead_events',
        ['status', sa.text('received_at DESC')],
    )


def downgrade():
    op.drop_index('ix_meta_lead_events_status_received',
                  table_name='meta_lead_events')
    op.drop_index('ix_meta_lead_events_received',
                  table_name='meta_lead_events')
