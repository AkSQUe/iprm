"""Add referral_rewards ledger table

Revision ID: referral_rewards_20260714
Revises: referral_attrib_20260714
Create Date: 2026-07-14 01:00:00.000000

Фаза 3 реферальної програми: реєстр нарахувань бонусних балів. Один рядок на
оплачену реєстрацію (UNIQUE registration_id -> ідемпотентність). Баланс =
SUM(points) активних (granted) нарахувань реферера.
"""
from alembic import op
import sqlalchemy as sa


revision = 'referral_rewards_20260714'
down_revision = 'referral_attrib_20260714'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'referral_rewards',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('registration_id', sa.BigInteger(), nullable=False),
        sa.Column('referrer_kind', sa.String(length=10), nullable=False),
        sa.Column('referrer_id', sa.BigInteger(), nullable=False),
        sa.Column('referral_code', sa.String(length=32), nullable=False),
        sa.Column('points', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='granted'),
        sa.Column('voided_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('notes', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['registration_id'], ['event_registrations.id'],
                                ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('registration_id', name='uq_referral_rewards_registration'),
        sa.CheckConstraint("referrer_kind IN ('user', 'trainer')",
                           name='ck_referral_rewards_kind'),
        sa.CheckConstraint("status IN ('granted', 'voided')",
                           name='ck_referral_rewards_status'),
        sa.CheckConstraint('points >= 0', name='ck_referral_rewards_points_non_negative'),
    )
    op.create_index('ix_referral_rewards_registration_id', 'referral_rewards',
                    ['registration_id'])
    op.create_index('ix_referral_rewards_status', 'referral_rewards', ['status'])
    op.create_index('ix_referral_rewards_referrer', 'referral_rewards',
                    ['referrer_kind', 'referrer_id', 'status'])


def downgrade():
    op.drop_index('ix_referral_rewards_referrer', table_name='referral_rewards')
    op.drop_index('ix_referral_rewards_status', table_name='referral_rewards')
    op.drop_index('ix_referral_rewards_registration_id', table_name='referral_rewards')
    op.drop_table('referral_rewards')
