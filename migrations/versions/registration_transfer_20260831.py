"""registration_transfers -- перенесення реєстрації на інше проведення.

Revision ID: registration_transfer_20260831
Revises: 9fad58660b0d
"""
import sqlalchemy as sa
from alembic import op

revision = 'registration_transfer_20260831'
down_revision = '9fad58660b0d'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'registration_transfers',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('registration_id', sa.BigInteger(), nullable=False),
        sa.Column('from_instance_id', sa.BigInteger(), nullable=True),
        sa.Column('to_instance_id', sa.BigInteger(), nullable=True),
        sa.Column('initiator', sa.String(length=20), nullable=False),
        sa.Column('announced', sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column('reason', sa.String(length=500), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('tariff_decision', sa.String(length=20), nullable=False),
        sa.Column('to_tariff_id', sa.BigInteger(), nullable=True),
        sa.Column('old_amount', sa.Numeric(10, 2), nullable=True),
        sa.Column('new_amount', sa.Numeric(10, 2), nullable=True),
        sa.Column('difference', sa.Numeric(10, 2), nullable=True),
        sa.Column('state', sa.String(length=20), nullable=False),
        sa.Column('consent_token', sa.String(length=64), nullable=True),
        sa.Column('consent_token_expires_at', sa.DateTime(timezone=True),
                  nullable=True),
        sa.Column('responded_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('refund_request_id', sa.BigInteger(), nullable=True),
        sa.Column('surcharge_paid_at', sa.DateTime(timezone=True),
                  nullable=True),
        sa.Column('surcharge_payment_id', sa.String(length=255), nullable=True),
        sa.Column('created_by_id', sa.BigInteger(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['registration_id'], ['event_registrations.id'],
                                ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['from_instance_id'], ['course_instances.id'],
                                ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['to_instance_id'], ['course_instances.id'],
                                ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['to_tariff_id'], ['instance_tariffs.id'],
                                ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['refund_request_id'], ['refund_requests.id'],
                                ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'],
                                ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint(
            "state IN ('applied', 'awaiting_consent', 'accepted', "
            "'refund_requested')",
            name='ck_registration_transfers_state'),
        sa.CheckConstraint(
            "initiator IN ('organizer', 'participant')",
            name='ck_registration_transfers_initiator'),
        sa.CheckConstraint(
            "tariff_decision IN ('keep', 'refund_diff', 'surcharge')",
            name='ck_registration_transfers_decision'),
        sa.CheckConstraint(
            "NOT (initiator = 'organizer' AND tariff_decision = 'surcharge')",
            name='ck_registration_transfers_organizer_no_surcharge'),
    )
    op.create_index('ix_registration_transfers_registration',
                    'registration_transfers', ['registration_id'])
    op.create_index('ix_registration_transfers_state',
                    'registration_transfers', ['state'])
    op.create_index('ix_registration_transfers_consent_token',
                    'registration_transfers', ['consent_token'], unique=True)
    op.create_index(
        'uq_registration_transfers_open', 'registration_transfers',
        ['registration_id'], unique=True,
        postgresql_where=sa.text("state = 'awaiting_consent'"),
        sqlite_where=sa.text("state = 'awaiting_consent'"),
    )


def downgrade():
    op.drop_index('uq_registration_transfers_open',
                  table_name='registration_transfers')
    op.drop_index('ix_registration_transfers_consent_token',
                  table_name='registration_transfers')
    op.drop_index('ix_registration_transfers_state',
                  table_name='registration_transfers')
    op.drop_index('ix_registration_transfers_registration',
                  table_name='registration_transfers')
    op.drop_table('registration_transfers')
