"""email suppression unsubscribe idempotency bounce

Revision ID: 5e29997c6998
Revises: 9e14e2c0dbf1
Create Date: 2026-06-24 20:50:44.876025

Додає:
- email_suppressions -- список адрес, на які не шлемо (bounce/unsubscribe);
- users.email_opt_out / users.unsubscribe_token -- відписка від необов'язкових;
- email_logs.idempotency_key -- захист від подвійної відправки;
- email_settings.bounce_polling_enabled -- вмикач IMAP-полінгу баунсів.
"""
from alembic import op
import sqlalchemy as sa


revision = '5e29997c6998'
down_revision = '9e14e2c0dbf1'
branch_labels = None
depends_on = None


def upgrade():
    # 'backup_failure' використовується scheduler-ом (сповіщення про збій
    # бекапу), але був відсутній у CHECK -> INSERT email_logs падав і лист не
    # йшов. Додаємо у дозволені значення (як свого часу password_reset).
    op.drop_constraint('ck_email_logs_trigger', 'email_logs', type_='check')
    op.create_check_constraint(
        'ck_email_logs_trigger', 'email_logs',
        "trigger IN ('registration', 'payment', 'reminder', 'status_change', "
        "'email_confirm', 'course_request', 'certificate', 'blog_comment', "
        "'password_reset', 'backup_failure', 'test')",
    )

    op.create_table(
        'email_suppressions',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('reason', sa.String(length=50), nullable=False),
        sa.Column('source', sa.String(length=50), nullable=True),
        sa.Column('detail', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_email_suppressions_email', 'email_suppressions', ['email'], unique=True)

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'email_opt_out', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column('unsubscribe_token', sa.String(length=64), nullable=True))
        batch_op.create_index('ix_users_unsubscribe_token', ['unsubscribe_token'], unique=True)

    with op.batch_alter_table('email_logs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('idempotency_key', sa.String(length=64), nullable=True))
        batch_op.create_index('ix_email_logs_idempotency_key', ['idempotency_key'], unique=False)

    with op.batch_alter_table('email_settings', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'bounce_polling_enabled', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    with op.batch_alter_table('email_settings', schema=None) as batch_op:
        batch_op.drop_column('bounce_polling_enabled')

    with op.batch_alter_table('email_logs', schema=None) as batch_op:
        batch_op.drop_index('ix_email_logs_idempotency_key')
        batch_op.drop_column('idempotency_key')

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_index('ix_users_unsubscribe_token')
        batch_op.drop_column('unsubscribe_token')
        batch_op.drop_column('email_opt_out')

    op.drop_index('ix_email_suppressions_email', table_name='email_suppressions')
    op.drop_table('email_suppressions')

    op.drop_constraint('ck_email_logs_trigger', 'email_logs', type_='check')
    op.create_check_constraint(
        'ck_email_logs_trigger', 'email_logs',
        "trigger IN ('registration', 'payment', 'reminder', 'status_change', "
        "'email_confirm', 'course_request', 'certificate', 'blog_comment', "
        "'password_reset', 'test')",
    )
