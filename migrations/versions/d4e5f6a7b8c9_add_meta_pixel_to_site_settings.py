"""Add meta_pixel_enabled / meta_pixel_id to site_settings

Revision ID: d4e5f6a7b8c9
Revises: instance_tariff_format_20260731
Create Date: 2026-08-04 17:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'd4e5f6a7b8c9'
down_revision = 'instance_tariff_format_20260731'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('meta_pixel_enabled', sa.Boolean(), nullable=False,
                      server_default=sa.false())
        )
        batch_op.add_column(
            sa.Column('meta_pixel_id', sa.String(length=50), nullable=False,
                      server_default='')
        )


def downgrade():
    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        batch_op.drop_column('meta_pixel_id')
        batch_op.drop_column('meta_pixel_enabled')
