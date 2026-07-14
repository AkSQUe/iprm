"""Add referral_clicks daily aggregate (funnel analytics)

Revision ID: referral_clicks_20260714
Revises: referral_pending_20260714
Create Date: 2026-07-14 06:00:00.000000

Фаза E: денний агрегат кліків по реферальних посиланнях для воронки
"кліки -> реєстрації -> оплати".
"""
from alembic import op
import sqlalchemy as sa


revision = 'referral_clicks_20260714'
down_revision = 'referral_pending_20260714'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'referral_clicks',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('referral_code', sa.String(length=32), nullable=False),
        sa.Column('day', sa.Date(), nullable=False),
        sa.Column('count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('referral_code', 'day', name='uq_referral_clicks_code_day'),
    )
    op.create_index('ix_referral_clicks_referral_code', 'referral_clicks',
                    ['referral_code'])


def downgrade():
    op.drop_index('ix_referral_clicks_referral_code', table_name='referral_clicks')
    op.drop_table('referral_clicks')
