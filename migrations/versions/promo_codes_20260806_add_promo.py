"""Add promo codes: promo_codes, promo_redemptions + discount on registrations

Revision ID: promo_codes_20260806
Revises: d4e5f6a7b8c9
Create Date: 2026-08-06 12:00:00.000000

Промокоди зі знижкою (відсоток або сума), лімітами (загальний і на одну
людину), вікном дії та опційною прив'язкою до курсу/проведення.
promo_redemptions -- реєстр застосувань (джерело правди для лічильника).
На event_registrations -- promo_code_id (FK SET NULL, реєстрація переживає
видалення коду) і discount_amount (знімок для звітів).
"""
from alembic import op
import sqlalchemy as sa


revision = 'promo_codes_20260806'
down_revision = 'd4e5f6a7b8c9'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'promo_codes',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('code', sa.String(length=64), nullable=False),
        sa.Column('code_norm', sa.String(length=64), nullable=False),
        sa.Column('description', sa.String(length=255), nullable=True),
        sa.Column('discount_type', sa.String(length=10), nullable=False,
                  server_default='percent'),
        sa.Column('discount_value', sa.Numeric(10, 2), nullable=False),
        sa.Column('max_uses', sa.Integer(), nullable=True),
        # Без server_default: NULL тут означає "без обмежень", і дефолт на
        # рівні БД перетворював би цей вибір на "1 раз" (див. модель).
        sa.Column('per_user_limit', sa.Integer(), nullable=True),
        sa.Column('used_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('valid_from', sa.DateTime(timezone=True), nullable=True),
        sa.Column('valid_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('course_id', sa.BigInteger(), nullable=True),
        sa.Column('instance_id', sa.BigInteger(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_by_id', sa.BigInteger(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['course_id'], ['courses.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['instance_id'], ['course_instances.id'],
                                ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint("discount_type IN ('percent', 'amount')",
                           name='ck_promo_codes_discount_type'),
        sa.CheckConstraint('discount_value > 0',
                           name='ck_promo_codes_discount_positive'),
        sa.CheckConstraint("discount_type <> 'percent' OR discount_value <= 100",
                           name='ck_promo_codes_percent_range'),
        sa.CheckConstraint('max_uses IS NULL OR max_uses >= 1',
                           name='ck_promo_codes_max_uses'),
        sa.CheckConstraint('per_user_limit IS NULL OR per_user_limit >= 1',
                           name='ck_promo_codes_per_user_limit'),
        sa.CheckConstraint('used_count >= 0', name='ck_promo_codes_used_count'),
    )
    op.create_index('ix_promo_codes_code_norm', 'promo_codes', ['code_norm'],
                    unique=True)
    op.create_index('ix_promo_codes_course_id', 'promo_codes', ['course_id'])
    op.create_index('ix_promo_codes_instance_id', 'promo_codes', ['instance_id'])

    op.create_table(
        'promo_redemptions',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('promo_code_id', sa.BigInteger(), nullable=False),
        sa.Column('registration_id', sa.BigInteger(), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=True),
        sa.Column('original_amount', sa.Numeric(10, 2), nullable=False),
        sa.Column('discount_amount', sa.Numeric(10, 2), nullable=False),
        sa.Column('final_amount', sa.Numeric(10, 2), nullable=False),
        sa.Column('status', sa.String(length=10), nullable=False,
                  server_default='applied'),
        sa.Column('voided_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('notes', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['promo_code_id'], ['promo_codes.id'],
                                ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['registration_id'], ['event_registrations.id'],
                                ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint("status IN ('applied', 'voided')",
                           name='ck_promo_redemptions_status'),
        sa.CheckConstraint('discount_amount >= 0',
                           name='ck_promo_redemptions_discount_non_negative'),
    )
    op.create_index('ix_promo_redemptions_promo_code_id', 'promo_redemptions',
                    ['promo_code_id'])
    op.create_index('ix_promo_redemptions_registration_id', 'promo_redemptions',
                    ['registration_id'])
    # Активне списання на реєстрацію -- рівно одне; анульовані рядки
    # (заміна коду, повернення коштів) лишаються в історії.
    op.create_index('uq_promo_redemptions_active_reg', 'promo_redemptions',
                    ['registration_id'], unique=True,
                    postgresql_where=sa.text("status = 'applied'"))
    op.create_index('ix_promo_redemptions_user_id', 'promo_redemptions', ['user_id'])
    op.create_index('ix_promo_redemptions_status', 'promo_redemptions', ['status'])
    op.create_index('ix_promo_redemptions_code_user', 'promo_redemptions',
                    ['promo_code_id', 'user_id', 'status'])

    # batch_alter_table -- як у reg_tariff_20260708: на PostgreSQL це
    # звичайний ALTER, а на SQLite (dev/тести) -- copy-and-move, без якого
    # ALTER ... ADD CONSTRAINT там не працює зовсім.
    with op.batch_alter_table('event_registrations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('promo_code_id', sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column('discount_amount', sa.Numeric(10, 2), nullable=True))
        batch_op.create_index('ix_event_registrations_promo_code_id',
                              ['promo_code_id'])
        batch_op.create_foreign_key(
            'fk_event_registrations_promo_code', 'promo_codes',
            ['promo_code_id'], ['id'], ondelete='SET NULL',
        )
        batch_op.create_check_constraint(
            'ck_registrations_discount_non_negative',
            'discount_amount >= 0 OR discount_amount IS NULL',
        )


def downgrade():
    with op.batch_alter_table('event_registrations', schema=None) as batch_op:
        batch_op.drop_constraint('ck_registrations_discount_non_negative',
                                 type_='check')
        batch_op.drop_constraint('fk_event_registrations_promo_code',
                                 type_='foreignkey')
        batch_op.drop_index('ix_event_registrations_promo_code_id')
        batch_op.drop_column('discount_amount')
        batch_op.drop_column('promo_code_id')

    op.drop_index('ix_promo_redemptions_code_user', table_name='promo_redemptions')
    op.drop_index('uq_promo_redemptions_active_reg', table_name='promo_redemptions')
    op.drop_index('ix_promo_redemptions_status', table_name='promo_redemptions')
    op.drop_index('ix_promo_redemptions_user_id', table_name='promo_redemptions')
    op.drop_index('ix_promo_redemptions_registration_id',
                  table_name='promo_redemptions')
    op.drop_index('ix_promo_redemptions_promo_code_id',
                  table_name='promo_redemptions')
    op.drop_table('promo_redemptions')

    op.drop_index('ix_promo_codes_instance_id', table_name='promo_codes')
    op.drop_index('ix_promo_codes_course_id', table_name='promo_codes')
    op.drop_index('ix_promo_codes_code_norm', table_name='promo_codes')
    op.drop_table('promo_codes')
