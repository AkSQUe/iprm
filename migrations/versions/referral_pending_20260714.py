"""Add users.pending_referral_code (server-side attribution)

Revision ID: referral_pending_20260714
Revises: referral_ledger_20260714
Create Date: 2026-07-14 05:00:00.000000

Фаза C: серверна атрибуція -- код реферера, зафіксований при кліку залогіненим
користувачем, переживає втрату cookie. Споживається при реєстрації.
"""
from alembic import op
import sqlalchemy as sa


revision = 'referral_pending_20260714'
down_revision = 'referral_ledger_20260714'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('pending_referral_code', sa.String(length=32), nullable=True))


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('pending_referral_code')
