"""Add MM Medic reservation integration fields to site_settings

Revision ID: mm_medic_settings_20260706
Revises: 5e29997c6998
Create Date: 2026-07-06 00:00:00.000000

Adds the outgoing MM Medic materials-reservation API config. The request-signing
secret is reused from partner_webhook_secret, so only an enable flag and the API
base URL are added.
"""
from alembic import op
import sqlalchemy as sa


revision = 'mm_medic_settings_20260706'
down_revision = '5e29997c6998'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'mm_medic_integration_enabled',
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ))
        batch_op.add_column(sa.Column(
            'mm_medic_api_base_url',
            sa.String(length=500),
            nullable=True,
            server_default='',
        ))


def downgrade():
    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        batch_op.drop_column('mm_medic_api_base_url')
        batch_op.drop_column('mm_medic_integration_enabled')
