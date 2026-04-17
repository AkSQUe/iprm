"""Add partner integration fields to site_settings

Revision ID: c4d5e6f7a8b9
Revises: 4bfb2835d444
Create Date: 2026-04-17 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'c4d5e6f7a8b9'
down_revision = '4bfb2835d444'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'partner_integration_enabled',
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ))
        batch_op.add_column(sa.Column(
            'partner_api_key',
            sa.String(length=500),
            nullable=True,
            server_default='',
        ))
        batch_op.add_column(sa.Column(
            'partner_prefill_secret',
            sa.String(length=500),
            nullable=True,
            server_default='',
        ))


def downgrade():
    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        batch_op.drop_column('partner_prefill_secret')
        batch_op.drop_column('partner_api_key')
        batch_op.drop_column('partner_integration_enabled')
