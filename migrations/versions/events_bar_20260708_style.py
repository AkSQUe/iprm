"""Site settings: upcoming_events_style (popup vs sticky bar)

Revision ID: events_bar_20260708
Revises: courses_order_20260708
Create Date: 2026-07-08 00:00:00.000000

Adds site_settings.upcoming_events_style: how the public "upcoming events"
block is rendered -- 'popup' (floating bottom-left card, previous behavior)
or 'bar' (sticky full-width strip under the header). Editable at
/admin/settings alongside the existing show_upcoming_events toggle.
"""
from alembic import op
import sqlalchemy as sa


revision = 'events_bar_20260708'
down_revision = 'courses_order_20260708'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        batch_op.add_column(sa.Column('upcoming_events_style', sa.String(10),
                                      nullable=False, server_default='popup'))


def downgrade():
    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        batch_op.drop_column('upcoming_events_style')
