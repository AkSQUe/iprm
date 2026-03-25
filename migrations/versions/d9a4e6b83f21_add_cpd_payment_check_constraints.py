"""Додати CHECK constraints для cpd_points, cpd_points_awarded, payment_amount

Revision ID: d9a4e6b83f21
Revises: c8f3d5a72e19
Create Date: 2026-03-25 14:00:00.000000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'd9a4e6b83f21'
down_revision = 'c8f3d5a72e19'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != 'sqlite':
        op.create_check_constraint(
            'ck_events_cpd_points_non_negative', 'events',
            'cpd_points >= 0 OR cpd_points IS NULL'
        )
        op.create_check_constraint(
            'ck_registrations_cpd_non_negative', 'event_registrations',
            'cpd_points_awarded >= 0 OR cpd_points_awarded IS NULL'
        )
        op.create_check_constraint(
            'ck_registrations_payment_amount_non_negative', 'event_registrations',
            'payment_amount >= 0 OR payment_amount IS NULL'
        )


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name != 'sqlite':
        op.drop_constraint(
            'ck_registrations_payment_amount_non_negative',
            'event_registrations', type_='check'
        )
        op.drop_constraint(
            'ck_registrations_cpd_non_negative',
            'event_registrations', type_='check'
        )
        op.drop_constraint(
            'ck_events_cpd_points_non_negative',
            'events', type_='check'
        )
