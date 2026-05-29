"""Add secret rotation timestamps to site_settings

Rotation reminders (EXTEND після Q4 improve-batch). 4 нові nullable
datetime-колонки, що пишуться у property-setter'ах при оновленні
відповідного секрета. NULL означає "невідомо коли був останній сетап"
(legacy-секрети до цієї міграції -- адмін має заново зберегти, щоб
почали трекати).

Колонки:
  liqpay_private_key_set_at
  google_oauth_client_secret_set_at
  apple_private_key_set_at
  recaptcha_secret_key_set_at

Revision ID: d5e6f7a8b9c0
Revises: c9d0e1f2a3b4
Create Date: 2026-05-29 12:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'd5e6f7a8b9c0'
down_revision = 'c9d0e1f2a3b4'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'liqpay_private_key_set_at',
            sa.DateTime(timezone=True), nullable=True,
        ))
        batch_op.add_column(sa.Column(
            'google_oauth_client_secret_set_at',
            sa.DateTime(timezone=True), nullable=True,
        ))
        batch_op.add_column(sa.Column(
            'apple_private_key_set_at',
            sa.DateTime(timezone=True), nullable=True,
        ))
        batch_op.add_column(sa.Column(
            'recaptcha_secret_key_set_at',
            sa.DateTime(timezone=True), nullable=True,
        ))


def downgrade():
    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        batch_op.drop_column('recaptcha_secret_key_set_at')
        batch_op.drop_column('apple_private_key_set_at')
        batch_op.drop_column('google_oauth_client_secret_set_at')
        batch_op.drop_column('liqpay_private_key_set_at')
