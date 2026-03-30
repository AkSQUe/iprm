"""Add show_labs and show_clinics toggles to site_settings

Revision ID: f5a6b7c8d9e0
Revises: e4f5a6b7c8d9
Create Date: 2026-03-30 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'f5a6b7c8d9e0'
down_revision = 'e4f5a6b7c8d9'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        batch_op.add_column(sa.Column('show_labs', sa.Boolean(), nullable=False, server_default='1'))
        batch_op.add_column(sa.Column('show_clinics', sa.Boolean(), nullable=False, server_default='1'))


def downgrade():
    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        batch_op.drop_column('show_clinics')
        batch_op.drop_column('show_labs')
