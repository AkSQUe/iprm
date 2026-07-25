"""Site settings: home hero video toggle

Revision ID: home_hero_video_20260725
Revises: i18n_userlang_20260724
Create Date: 2026-07-25 00:00:00.000000

Adds site_settings.show_home_hero_video -- toggles the background video in
the home page hero. Enabled by default; switchable at /admin/settings.
Turning it off restores the pre-video hero (no video, no poster).
"""
from alembic import op
import sqlalchemy as sa


revision = 'home_hero_video_20260725'
down_revision = 'i18n_userlang_20260724'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        batch_op.add_column(sa.Column('show_home_hero_video', sa.Boolean(),
                                      nullable=False, server_default=sa.true()))


def downgrade():
    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        batch_op.drop_column('show_home_hero_video')
