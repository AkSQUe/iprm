"""Referral maturity + manual adjustments ledger

Revision ID: referral_ledger_20260714
Revises: referral_config_20260714
Create Date: 2026-07-14 04:00:00.000000

Фаза B: дозрівання балів (status 'pending' + matures_at) і ручні корекції
балансу (referral_adjustments).
"""
from alembic import op
import sqlalchemy as sa


revision = 'referral_ledger_20260714'
down_revision = 'referral_config_20260714'
branch_labels = None
depends_on = None

_STATUS_OLD = "status IN ('granted', 'voided')"
_STATUS_NEW = "status IN ('pending', 'granted', 'voided')"


def upgrade():
    # 1. Дозрівання нарахувань.
    with op.batch_alter_table('referral_rewards', schema=None) as batch_op:
        batch_op.add_column(sa.Column('matures_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.drop_constraint('ck_referral_rewards_status', type_='check')
        batch_op.create_check_constraint('ck_referral_rewards_status', _STATUS_NEW)
        batch_op.create_index('ix_referral_rewards_matures', ['status', 'matures_at'])

    # 2. Ручні корекції балансу.
    op.create_table(
        'referral_adjustments',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('referrer_kind', sa.String(length=10), nullable=False),
        sa.Column('referrer_id', sa.BigInteger(), nullable=False),
        sa.Column('points', sa.Integer(), nullable=False),
        sa.Column('reason', sa.String(length=255), nullable=False),
        sa.Column('created_by_id', sa.BigInteger(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint("referrer_kind IN ('user', 'trainer')",
                           name='ck_referral_adjustments_kind'),
    )
    op.create_index('ix_referral_adjustments_referrer', 'referral_adjustments',
                    ['referrer_kind', 'referrer_id'])


def downgrade():
    op.drop_index('ix_referral_adjustments_referrer', table_name='referral_adjustments')
    op.drop_table('referral_adjustments')
    # Перед звуженням CHECK гасимо 'pending' -> 'granted'.
    op.execute("UPDATE referral_rewards SET status = 'granted' WHERE status = 'pending'")
    with op.batch_alter_table('referral_rewards', schema=None) as batch_op:
        batch_op.drop_index('ix_referral_rewards_matures')
        batch_op.drop_constraint('ck_referral_rewards_status', type_='check')
        batch_op.create_check_constraint('ck_referral_rewards_status', _STATUS_OLD)
        batch_op.drop_column('matures_at')
