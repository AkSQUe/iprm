"""Site settings: ROI calculator toggle

Revision ID: roi_calc_20260708
Revises: notif_materials_20260708
Create Date: 2026-07-08 00:00:00.000000

Adds site_settings.show_roi_calculator -- toggles the payback (ROI)
calculator block on course pages (Multimed reference, Блок 6). Enabled
by default; switchable at /admin/settings.
"""
from alembic import op
import sqlalchemy as sa


revision = 'roi_calc_20260708'
down_revision = 'notif_materials_20260708'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        batch_op.add_column(sa.Column('show_roi_calculator', sa.Boolean(),
                                      nullable=False, server_default=sa.true()))


def downgrade():
    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        batch_op.drop_column('show_roi_calculator')
