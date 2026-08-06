"""Промокод-подяка в листі про оплату + походження коду

Revision ID: thankyou_promo_20260806
Revises: promo_codes_20260806
Create Date: 2026-08-06 21:00:00.000000

site_settings: вмикач, розмір знижки (%) і строк дії персонального коду,
який видається разом з листом "оплату підтверджено".

promo_codes.issued_for_registration_id: за яку реєстрацію код видано
автоматично. Це походження, а не область дії -- по ньому видача
ідемпотентна (повторний лист не плодить кодів). FK іменований явно:
event_registrations уже посилається на promo_codes, тож обмеження
навішуємо окремим ALTER (цикл між таблицями).
"""
from alembic import op
import sqlalchemy as sa


revision = 'thankyou_promo_20260806'
down_revision = 'promo_codes_20260806'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('site_settings') as batch:
        batch.add_column(sa.Column(
            'thankyou_promo_enabled', sa.Boolean(), nullable=False,
            server_default=sa.false(),
        ))
        batch.add_column(sa.Column(
            'thankyou_promo_percent', sa.Integer(), nullable=False,
            server_default='10',
        ))
        batch.add_column(sa.Column(
            'thankyou_promo_days', sa.Integer(), nullable=False,
            server_default='30',
        ))

    op.add_column(
        'promo_codes',
        sa.Column('issued_for_registration_id', sa.BigInteger(), nullable=True),
    )
    op.create_index(
        'ix_promo_codes_issued_for_registration_id', 'promo_codes',
        ['issued_for_registration_id'],
    )
    op.create_foreign_key(
        'fk_promo_codes_issued_for_registration', 'promo_codes',
        'event_registrations', ['issued_for_registration_id'], ['id'],
        ondelete='SET NULL',
    )


def downgrade():
    op.drop_constraint(
        'fk_promo_codes_issued_for_registration', 'promo_codes',
        type_='foreignkey',
    )
    op.drop_index('ix_promo_codes_issued_for_registration_id',
                  table_name='promo_codes')
    op.drop_column('promo_codes', 'issued_for_registration_id')

    with op.batch_alter_table('site_settings') as batch:
        batch.drop_column('thankyou_promo_days')
        batch.drop_column('thankyou_promo_percent')
        batch.drop_column('thankyou_promo_enabled')
