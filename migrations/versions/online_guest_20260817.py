"""Гостьова покупка онлайн-курсу: токен сторінки замовлення.

Покупець без акаунта мусить якось повернутись до оплати, рахунка й
створення кабінету. Токен -- той самий механізм, що в заходів
(registrations.completion_token), і живе він до оплати, тоді як
access_token видається вже після неї.

Revision ID: online_guest_20260817
Revises: quiz_trans_20260817
"""
import sqlalchemy as sa
from alembic import op

revision = 'online_guest_20260817'
down_revision = 'quiz_trans_20260817'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('online_enrollments') as batch:
        batch.add_column(sa.Column('order_token', sa.String(64), nullable=True))
        batch.add_column(
            sa.Column('order_token_expires_at', sa.DateTime(timezone=True),
                      nullable=True))
        # unique=True, а не просто index: токен -- ключ до сторінки
        # замовлення, і два однакові означали б чужу покупку у видачі.
        batch.create_index('ix_online_enrollments_order_token',
                           ['order_token'], unique=True)


def downgrade():
    with op.batch_alter_table('online_enrollments') as batch:
        batch.drop_index('ix_online_enrollments_order_token')
        batch.drop_column('order_token_expires_at')
        batch.drop_column('order_token')
