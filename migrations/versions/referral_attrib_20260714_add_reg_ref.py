"""Add referral attribution column to event_registrations

Revision ID: referral_attrib_20260714
Revises: referral_program_20260714
Create Date: 2026-07-14 00:30:00.000000

Фаза 2 реферальної програми: event_registrations.referral_code -- код
реферера (User/Trainer), захоплений з cookie при створенні реєстрації.
"""
from alembic import op
import sqlalchemy as sa


revision = 'referral_attrib_20260714'
down_revision = 'referral_program_20260714'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('event_registrations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('referral_code', sa.String(length=32), nullable=True))
        batch_op.create_index('ix_event_registrations_referral_code', ['referral_code'])


def downgrade():
    with op.batch_alter_table('event_registrations', schema=None) as batch_op:
        batch_op.drop_index('ix_event_registrations_referral_code')
        batch_op.drop_column('referral_code')
