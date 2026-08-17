"""Промокод-подяка за покупку онлайн-курсу

Revision ID: thankyou_online_20260817
Revises: promo_online_20260817
Create Date: 2026-08-17 19:40:00.000000

`promo_codes.issued_for_registration_id` тримає ідемпотентність видачі:
повторний виклик (ретрай листа, ручна пересилка) знаходить уже виданий код
і не плодить новий. Для покупок онлайн-курсів такого зачепа не було, тож
механіка подяки на них просто не працювала.

Колонка nullable і без CHECK «рівно одне з двох»: код може бути й
загальним, не виданим ні за що конкретне -- саме такі створює адмін
руками. Тут дві колонки означають «за що видано», а не власника.
"""
from alembic import op
import sqlalchemy as sa


revision = 'thankyou_online_20260817'
down_revision = 'promo_online_20260817'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('promo_codes') as batch:
        batch.add_column(sa.Column('issued_for_enrollment_id', sa.BigInteger(),
                                   nullable=True))
        batch.create_foreign_key(
            'fk_promo_codes_issued_for_enrollment_id', 'online_enrollments',
            ['issued_for_enrollment_id'], ['id'], ondelete='SET NULL',
        )
    op.create_index('ix_promo_codes_issued_for_enrollment_id', 'promo_codes',
                    ['issued_for_enrollment_id'])


def downgrade():
    op.drop_index('ix_promo_codes_issued_for_enrollment_id',
                  table_name='promo_codes')
    with op.batch_alter_table('promo_codes') as batch:
        batch.drop_constraint('fk_promo_codes_issued_for_enrollment_id',
                              type_='foreignkey')
        batch.drop_column('issued_for_enrollment_id')
