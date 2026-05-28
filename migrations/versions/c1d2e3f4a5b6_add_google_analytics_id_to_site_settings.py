"""Add google_analytics_id to site_settings

Revision ID: c1d2e3f4a5b6
Revises: b9c0d1e2f3a4
Create Date: 2026-05-28 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'c1d2e3f4a5b6'
down_revision = 'b9c0d1e2f3a4'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('google_analytics_id', sa.String(length=50), nullable=False, server_default='')
        )


def downgrade():
    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        batch_op.drop_column('google_analytics_id')
