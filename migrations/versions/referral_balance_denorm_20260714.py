"""Denormalized referral_balance + attribution CHECK

Revision ID: referral_balance_denorm_20260714
Revises: referral_clicks_20260714
Create Date: 2026-07-14 07:00:00.000000

O3: денормалізований баланс (users.referral_balance, trainers.referral_balance)
для швидкого читання без SUM. O6: CHECK на site_settings.referral_attribution.
Бекфіл балансів робиться окремо (recompute) або лишається 0 до першої мутації.
"""
from alembic import op
import sqlalchemy as sa


revision = 'referral_balance_denorm_20260714'
down_revision = 'referral_clicks_20260714'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('referral_balance', sa.Integer(),
                                      nullable=False, server_default='0'))
    with op.batch_alter_table('trainers', schema=None) as batch_op:
        batch_op.add_column(sa.Column('referral_balance', sa.Integer(),
                                      nullable=False, server_default='0'))

    # Бекфіл із наявних нарахувань/корекцій (щоб не чекати першої мутації).
    op.execute("""
        UPDATE users SET referral_balance = COALESCE((
            SELECT SUM(points) FROM referral_rewards
            WHERE referrer_kind = 'user' AND referrer_id = users.id
              AND status = 'granted'
        ), 0) + COALESCE((
            SELECT SUM(points) FROM referral_adjustments
            WHERE referrer_kind = 'user' AND referrer_id = users.id
        ), 0)
    """)
    op.execute("""
        UPDATE trainers SET referral_balance = COALESCE((
            SELECT SUM(points) FROM referral_rewards
            WHERE referrer_kind = 'trainer' AND referrer_id = trainers.id
              AND status = 'granted'
        ), 0) + COALESCE((
            SELECT SUM(points) FROM referral_adjustments
            WHERE referrer_kind = 'trainer' AND referrer_id = trainers.id
        ), 0)
    """)

    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        batch_op.create_check_constraint(
            'ck_site_settings_referral_attribution',
            "referral_attribution IN ('first', 'last')")


def downgrade():
    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        batch_op.drop_constraint('ck_site_settings_referral_attribution', type_='check')
    with op.batch_alter_table('trainers', schema=None) as batch_op:
        batch_op.drop_column('referral_balance')
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('referral_balance')
