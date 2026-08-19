"""Заявки учасників на повернення коштів (Політика розділ 6).

Окрема таблиця, а не поле на замовленні: заявка має власне життя --
подана, розглянута, відхилена з поясненням, -- і власну дату, від якої
§4.2 велить рахувати відсоток. Тримати це в замовленні означало б
загубити дату подання при першому ж перерахунку.

Дві часткові унікальності стежать, щоб на замовлення була не більш як одна
ВІДКРИТА заявка: закриті (задоволені/відхилені) накопичуються в історії,
бо повторне звернення після відмови -- нормальний сценарій.

Revision ID: refund_requests_20260819
Revises: refunds_20260819
"""
import sqlalchemy as sa
from alembic import op

revision = 'refund_requests_20260819'
down_revision = 'refunds_20260819'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'refund_requests',
        sa.Column('id', sa.BigInteger().with_variant(sa.Integer, 'sqlite'),
                  primary_key=True),
        sa.Column('registration_id', sa.BigInteger, nullable=True),
        sa.Column('enrollment_id', sa.BigInteger, nullable=True),
        sa.Column('user_id', sa.BigInteger, nullable=False),
        sa.Column('reason', sa.Text, nullable=False),
        sa.Column('payout_details', sa.String(500), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='new'),
        sa.Column('quoted_percent', sa.Integer, nullable=True),
        sa.Column('quoted_amount', sa.Numeric(10, 2), nullable=True),
        sa.Column('quoted_code', sa.String(30), nullable=True),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('decided_by_id', sa.BigInteger, nullable=True),
        sa.Column('decision_note', sa.String(500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['registration_id'], ['event_registrations.id'],
                                ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['enrollment_id'], ['online_enrollments.id'],
                                ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['decided_by_id'], ['users.id'],
                                ondelete='SET NULL'),
        sa.CheckConstraint("status IN ('new', 'approved', 'rejected')",
                           name='ck_refund_requests_status'),
        sa.CheckConstraint('(registration_id IS NULL) <> (enrollment_id IS NULL)',
                           name='ck_refund_requests_single_owner'),
    )

    op.create_index('ix_refund_requests_registration_id', 'refund_requests',
                    ['registration_id'])
    op.create_index('ix_refund_requests_enrollment_id', 'refund_requests',
                    ['enrollment_id'])
    op.create_index('ix_refund_requests_user_id', 'refund_requests', ['user_id'])
    op.create_index('ix_refund_requests_status', 'refund_requests', ['status'])
    op.create_index('ix_refund_requests_created_at', 'refund_requests',
                    ['created_at'])

    op.create_index(
        'uq_refund_requests_open_registration', 'refund_requests',
        ['registration_id'], unique=True,
        postgresql_where=sa.text("status = 'new' AND registration_id IS NOT NULL"),
        sqlite_where=sa.text("status = 'new' AND registration_id IS NOT NULL"),
    )
    op.create_index(
        'uq_refund_requests_open_enrollment', 'refund_requests',
        ['enrollment_id'], unique=True,
        postgresql_where=sa.text("status = 'new' AND enrollment_id IS NOT NULL"),
        sqlite_where=sa.text("status = 'new' AND enrollment_id IS NOT NULL"),
    )


def downgrade():
    op.drop_table('refund_requests')
