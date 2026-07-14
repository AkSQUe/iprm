"""Add referral program fields (User/Trainer codes + site settings)

Revision ID: referral_program_20260714
Revises: certdata_nag_20260708
Create Date: 2026-07-14 00:00:00.000000

Фаза 1 реферальної програми:
  - users.referral_code, trainers.referral_code -- унікальні коди рефереров
    (nullable, генеруються лениво; unique-індекс);
  - site_settings.referral_enabled, referral_points_per_paid -- гейт і ставка
    нарахування бонусних балів за оплачену реєстрацію.
"""
from alembic import op
import sqlalchemy as sa


revision = 'referral_program_20260714'
down_revision = 'certdata_nag_20260708'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('referral_code', sa.String(length=32), nullable=True))
        batch_op.create_index(
            'ix_users_referral_code', ['referral_code'], unique=True,
        )

    with op.batch_alter_table('trainers', schema=None) as batch_op:
        batch_op.add_column(sa.Column('referral_code', sa.String(length=32), nullable=True))
        batch_op.create_index(
            'ix_trainers_referral_code', ['referral_code'], unique=True,
        )

    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'referral_enabled', sa.Boolean(), nullable=False,
            server_default=sa.false(),
        ))
        batch_op.add_column(sa.Column(
            'referral_points_per_paid', sa.Integer(), nullable=False,
            server_default='1',
        ))


def downgrade():
    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        batch_op.drop_column('referral_points_per_paid')
        batch_op.drop_column('referral_enabled')

    with op.batch_alter_table('trainers', schema=None) as batch_op:
        batch_op.drop_index('ix_trainers_referral_code')
        batch_op.drop_column('referral_code')

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_index('ix_users_referral_code')
        batch_op.drop_column('referral_code')
