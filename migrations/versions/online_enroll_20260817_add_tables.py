"""Замовлення онлайн-курсів + спільний журнал платежів

Revision ID: online_enroll_20260817
Revises: online_courses_20260817
Create Date: 2026-08-17 15:30:00.000000

Додає online_enrollments (купівля доступу до онлайн-курсу) і розширює
payment_transactions на другий тип замовлень.

УВАГА: правка грошової таблиці.

payment_transactions.registration_id стає NULLABLE, з'являється
enrollment_id і CHECK «рівно одне з двох». Наявні рядки не змінюються:
у всіх них registration_id заповнений, тож нове обмеження виконується
для них автоматично.

Відкат (downgrade) повертає NOT NULL, а для цього треба прибрати рядки,
де заповнений enrollment_id -- інакше ALTER не пройде. Тобто відкат
ВИДАЛЯЄ журнал платежів за онлайн-курси. Самі замовлення (і, отже,
підстава для звірки з виписками LiqPay) зникають разом із таблицею
online_enrollments. Робити це на проді з реальними оплатами не можна --
спершу вивантажте online_enrollments і відповідні payment_transactions.
"""
from alembic import op
import sqlalchemy as sa


revision = 'online_enroll_20260817'
down_revision = 'online_courses_20260817'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'online_enrollments',
        sa.Column('id', sa.BigInteger().with_variant(sa.Integer, 'sqlite'),
                  primary_key=True),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('online_course_id', sa.BigInteger(), nullable=False),

        sa.Column('status', sa.String(length=20), nullable=False,
                  server_default='pending'),
        sa.Column('payment_status', sa.String(length=20), nullable=False,
                  server_default='unpaid'),
        sa.Column('payment_amount', sa.Numeric(10, 2), nullable=True),
        sa.Column('payment_id', sa.String(length=255), nullable=True),
        sa.Column('payment_method', sa.String(length=20), nullable=False,
                  server_default='liqpay'),
        sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True),

        sa.Column('sintegrum_student_id', sa.Integer(), nullable=True),
        sa.Column('provisioned_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('provision_error', sa.Text(), nullable=True),

        sa.Column('access_token', sa.String(length=64), nullable=True),
        sa.Column('access_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('access_issued_count', sa.Integer(), nullable=False,
                  server_default='0'),
        sa.Column('access_last_opened_at', sa.DateTime(timezone=True), nullable=True),

        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),

        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['online_course_id'], ['online_courses.id'],
                                ondelete='RESTRICT'),
        sa.UniqueConstraint('access_token', name='uq_online_enrollments_access_token'),
        sa.CheckConstraint("status IN ('pending', 'active', 'cancelled')",
                           name='ck_online_enrollments_status'),
        sa.CheckConstraint(
            "payment_status IN ('unpaid', 'pending', 'paid', 'refunded')",
            name='ck_online_enrollments_payment_status'),
        sa.CheckConstraint('payment_amount >= 0 OR payment_amount IS NULL',
                           name='ck_online_enrollments_amount_non_negative'),
    )
    op.create_index('ix_online_enrollments_user_id', 'online_enrollments', ['user_id'])
    op.create_index('ix_online_enrollments_online_course_id', 'online_enrollments',
                    ['online_course_id'])
    op.create_index('ix_online_enrollments_status', 'online_enrollments', ['status'])
    op.create_index('ix_online_enrollments_payment_status', 'online_enrollments',
                    ['payment_status'])
    op.create_index('ix_online_enrollments_access_token', 'online_enrollments',
                    ['access_token'])
    # Джоба «доліковування» шукає саме оплачені без виданого доступу.
    op.create_index('ix_online_enrollments_paid_unprovisioned', 'online_enrollments',
                    ['payment_status', 'provisioned_at'])
    # Одна людина -- одна діюча покупка курсу; скасоване не блокує повторну.
    op.create_index(
        'uq_online_enrollments_user_course_live', 'online_enrollments',
        ['user_id', 'online_course_id'], unique=True,
        postgresql_where=sa.text("status <> 'cancelled'"),
        sqlite_where=sa.text("status <> 'cancelled'"),
    )

    # --- спільний журнал платежів ---
    with op.batch_alter_table('payment_transactions') as batch:
        batch.alter_column('registration_id', existing_type=sa.BigInteger(),
                           nullable=True)
        batch.add_column(sa.Column('enrollment_id', sa.BigInteger(), nullable=True))
        batch.create_foreign_key(
            'fk_payment_transactions_enrollment_id', 'online_enrollments',
            ['enrollment_id'], ['id'], ondelete='CASCADE',
        )
        batch.create_check_constraint(
            'ck_payment_transactions_single_owner',
            '(registration_id IS NULL) <> (enrollment_id IS NULL)',
        )
    op.create_index('ix_payment_transactions_enrollment_id', 'payment_transactions',
                    ['enrollment_id'])


def downgrade():
    op.drop_index('ix_payment_transactions_enrollment_id',
                  table_name='payment_transactions')
    # Рядки журналу за онлайн-курси не можуть існувати без enrollment_id,
    # а повернути registration_id NOT NULL без їх видалення неможливо.
    # Видалення СВІДОМЕ і незворотне -- див. попередження у шапці файлу.
    op.execute('DELETE FROM payment_transactions WHERE enrollment_id IS NOT NULL')
    with op.batch_alter_table('payment_transactions') as batch:
        batch.drop_constraint('ck_payment_transactions_single_owner',
                              type_='check')
        batch.drop_constraint('fk_payment_transactions_enrollment_id',
                              type_='foreignkey')
        batch.drop_column('enrollment_id')
        batch.alter_column('registration_id', existing_type=sa.BigInteger(),
                           nullable=False)

    op.drop_index('uq_online_enrollments_user_course_live',
                  table_name='online_enrollments')
    op.drop_index('ix_online_enrollments_paid_unprovisioned',
                  table_name='online_enrollments')
    op.drop_index('ix_online_enrollments_access_token',
                  table_name='online_enrollments')
    op.drop_index('ix_online_enrollments_payment_status',
                  table_name='online_enrollments')
    op.drop_index('ix_online_enrollments_status', table_name='online_enrollments')
    op.drop_index('ix_online_enrollments_online_course_id',
                  table_name='online_enrollments')
    op.drop_index('ix_online_enrollments_user_id', table_name='online_enrollments')
    op.drop_table('online_enrollments')
