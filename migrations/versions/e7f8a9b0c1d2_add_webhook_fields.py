"""Add partner webhook fields to site_settings

Revision ID: e7f8a9b0c1d2
Revises: c4d5e6f7a8b9
Create Date: 2026-04-17 17:45:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'e7f8a9b0c1d2'
down_revision = 'c4d5e6f7a8b9'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'partner_webhook_enabled',
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ))
        batch_op.add_column(sa.Column(
            'partner_webhook_url',
            sa.String(length=500),
            nullable=True,
            server_default='',
        ))
        batch_op.add_column(sa.Column(
            'partner_webhook_secret',
            sa.String(length=500),
            nullable=True,
            server_default='',
        ))


def downgrade():
    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        batch_op.drop_column('partner_webhook_secret')
        batch_op.drop_column('partner_webhook_url')
        batch_op.drop_column('partner_webhook_enabled')
