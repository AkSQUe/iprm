"""Registrations: chosen tariff link (E1 phase 4)

Revision ID: reg_tariff_20260708
Revises: instance_tariffs_20260708
Create Date: 2026-07-08 00:00:00.000000

Adds event_registrations.tariff_id (FK instance_tariffs, SET NULL) -- the
participation option chosen on the registration form. payment_amount is
snapshotted from the tariff at registration time, so later tariff edits
do not affect existing registrations.
"""
from alembic import op
import sqlalchemy as sa


revision = 'reg_tariff_20260708'
down_revision = 'instance_tariffs_20260708'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('event_registrations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('tariff_id', sa.BigInteger(), nullable=True))
        batch_op.create_foreign_key(
            'fk_event_registrations_tariff_id', 'instance_tariffs',
            ['tariff_id'], ['id'], ondelete='SET NULL',
        )
        batch_op.create_index('ix_event_registrations_tariff_id', ['tariff_id'])


def downgrade():
    with op.batch_alter_table('event_registrations', schema=None) as batch_op:
        batch_op.drop_index('ix_event_registrations_tariff_id')
        batch_op.drop_constraint('fk_event_registrations_tariff_id', type_='foreignkey')
        batch_op.drop_column('tariff_id')
