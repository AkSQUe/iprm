"""Add referral program config fields to site_settings

Revision ID: referral_config_20260714
Revises: email_referral_trigger_20260714
Create Date: 2026-07-14 03:00:00.000000

Конфіг реферальної програми в адмінці: термін cookie, модель атрибуції,
період дозрівання балів, стеля нарахувань, перемикач листа рефереру.
"""
from alembic import op
import sqlalchemy as sa


revision = 'referral_config_20260714'
down_revision = 'email_referral_trigger_20260714'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'referral_cookie_days', sa.Integer(), nullable=False,
            server_default='60'))
        batch_op.add_column(sa.Column(
            'referral_attribution', sa.String(length=10), nullable=False,
            server_default='last'))
        batch_op.add_column(sa.Column(
            'referral_maturity_days', sa.Integer(), nullable=False,
            server_default='0'))
        batch_op.add_column(sa.Column(
            'referral_max_per_referrer', sa.Integer(), nullable=False,
            server_default='0'))
        batch_op.add_column(sa.Column(
            'referral_notify_referrer', sa.Boolean(), nullable=False,
            server_default=sa.true()))


def downgrade():
    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        batch_op.drop_column('referral_notify_referrer')
        batch_op.drop_column('referral_max_per_referrer')
        batch_op.drop_column('referral_maturity_days')
        batch_op.drop_column('referral_attribution')
        batch_op.drop_column('referral_cookie_days')
