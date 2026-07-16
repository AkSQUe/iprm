"""Add site_settings.founding_year (home counters)

Revision ID: home_founding_year_20260716
Revises: referral_balance_denorm_20260714
Create Date: 2026-07-16 00:00:00.000000

Рік заснування для лічильника "років досвіду" на новій Головній сторінці.
"""
from alembic import op
import sqlalchemy as sa


revision = 'home_founding_year_20260716'
down_revision = 'referral_balance_denorm_20260714'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        batch_op.add_column(sa.Column('founding_year', sa.Integer(),
                                      nullable=False, server_default='2015'))


def downgrade():
    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        batch_op.drop_column('founding_year')
