"""Промокоди на онлайн-курси

Revision ID: promo_online_20260817
Revises: online_enroll_20260817
Create Date: 2026-08-17 18:10:00.000000

Промокоди досі знали лише про реєстрації на заходи: `promo_redemptions`
жорстко посилався на `event_registrations`, а знижка жила в полях
реєстрації. Онлайн-курс -- другий тип замовлення, і для нього потрібне
те саме.

Реєстр застосувань лишається СПІЛЬНИМ, як і журнал платежів: ліміт «на
одну людину» й лічильник використань мають рахуватися одним запитом.
Розводити їх по двох таблицях означало б, що код з max_uses=1 можна
використати двічі -- по разу в кожному типі замовлення.

УВАГА: правка грошової таблиці.

`registration_id` стає NULLABLE, з'являється `enrollment_id` і CHECK
«рівно одне з двох». Наявні рядки не змінюються: у всіх заповнений
`registration_id`, тож нове обмеження виконується для них автоматично.

Відкат повертає NOT NULL, а для цього треба прибрати рядки із заповненим
`enrollment_id` -- тобто ВИДАЛЯЄ історію знижок на онлайн-курси. На проді
з реальними застосуваннями робити це без попереднього вивантаження не можна.
"""
from alembic import op
import sqlalchemy as sa


revision = 'promo_online_20260817'
down_revision = 'online_enroll_20260817'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('online_enrollments') as batch:
        batch.add_column(sa.Column('promo_code_id', sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column('discount_amount', sa.Numeric(10, 2),
                                   nullable=True))
        batch.create_foreign_key(
            'fk_online_enrollments_promo_code_id', 'promo_codes',
            ['promo_code_id'], ['id'], ondelete='SET NULL',
        )
    op.create_index('ix_online_enrollments_promo_code_id', 'online_enrollments',
                    ['promo_code_id'])

    with op.batch_alter_table('promo_redemptions') as batch:
        batch.alter_column('registration_id', existing_type=sa.BigInteger(),
                           nullable=True)
        batch.add_column(sa.Column('enrollment_id', sa.BigInteger(), nullable=True))
        batch.create_foreign_key(
            'fk_promo_redemptions_enrollment_id', 'online_enrollments',
            ['enrollment_id'], ['id'], ondelete='CASCADE',
        )
        batch.create_check_constraint(
            'ck_promo_redemptions_single_owner',
            '(registration_id IS NULL) <> (enrollment_id IS NULL)',
        )
    op.create_index('ix_promo_redemptions_enrollment_id', 'promo_redemptions',
                    ['enrollment_id'])
    # Дзеркало `uq_promo_redemptions_active_reg`: активне списання на
    # замовлення -- рівно одне, анульовані лишаються в історії.
    op.create_index(
        'uq_promo_redemptions_active_enrollment', 'promo_redemptions',
        ['enrollment_id'], unique=True,
        postgresql_where=sa.text("status = 'applied'"),
        sqlite_where=sa.text("status = 'applied'"),
    )


def downgrade():
    op.drop_index('uq_promo_redemptions_active_enrollment',
                  table_name='promo_redemptions')
    op.drop_index('ix_promo_redemptions_enrollment_id',
                  table_name='promo_redemptions')
    # Свідоме й незворотне видалення -- див. попередження у шапці файлу.
    op.execute('DELETE FROM promo_redemptions WHERE enrollment_id IS NOT NULL')
    with op.batch_alter_table('promo_redemptions') as batch:
        batch.drop_constraint('ck_promo_redemptions_single_owner', type_='check')
        batch.drop_constraint('fk_promo_redemptions_enrollment_id',
                              type_='foreignkey')
        batch.drop_column('enrollment_id')
        batch.alter_column('registration_id', existing_type=sa.BigInteger(),
                           nullable=False)

    op.drop_index('ix_online_enrollments_promo_code_id',
                  table_name='online_enrollments')
    with op.batch_alter_table('online_enrollments') as batch:
        batch.drop_constraint('fk_online_enrollments_promo_code_id',
                              type_='foreignkey')
        batch.drop_column('discount_amount')
        batch.drop_column('promo_code_id')
