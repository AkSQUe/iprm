"""Site settings: seats_low_threshold for the public seats counter

Revision ID: seats_threshold_20260708
Revises: mm_material_emails_20260707
Create Date: 2026-07-08 00:00:00.000000

Adds site_settings.seats_low_threshold: when seats left on an instance is at
or below this value, the public "seats left" counter is highlighted as a
warning. 0 disables the highlight. Editable at /admin/settings.
"""
from alembic import op
import sqlalchemy as sa


revision = 'seats_threshold_20260708'
down_revision = 'mm_material_emails_20260707'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        batch_op.add_column(sa.Column('seats_low_threshold', sa.Integer(),
                                      nullable=False, server_default='5'))


def downgrade():
    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        batch_op.drop_column('seats_low_threshold')
