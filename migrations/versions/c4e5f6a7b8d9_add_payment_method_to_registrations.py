"""add payment_method to event_registrations

Revision ID: c4e5f6a7b8d9
Revises: ad0fa026fc6a
Create Date: 2026-06-20

Користувач обирає спосіб оплати під час реєстрації: 'liqpay' (онлайн, за
замовчуванням) або 'invoice' (оплата за рахунком). Існуючі рядки отримують
'liqpay' через server_default.
"""
from alembic import op
import sqlalchemy as sa


revision = 'c4e5f6a7b8d9'
down_revision = 'ad0fa026fc6a'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'event_registrations',
        sa.Column(
            'payment_method', sa.String(length=20),
            nullable=False, server_default='liqpay',
        ),
    )
    op.create_check_constraint(
        'ck_registrations_payment_method',
        'event_registrations',
        "payment_method IN ('liqpay', 'invoice')",
    )


def downgrade():
    op.drop_constraint(
        'ck_registrations_payment_method', 'event_registrations', type_='check',
    )
    op.drop_column('event_registrations', 'payment_method')
