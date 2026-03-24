"""Додати індекси та CHECK constraints для price/experience_years

Revision ID: b5e2a1d34f87
Revises: a3f7c2e91b04
Create Date: 2026-03-24 22:00:00.000000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'b5e2a1d34f87'
down_revision = 'a3f7c2e91b04'
branch_labels = None
depends_on = None


def upgrade():
    # --- Нові індекси ---
    op.create_index('ix_trainers_full_name', 'trainers', ['full_name'])
    op.create_index('ix_clinics_sort_order', 'clinics', ['sort_order'])

    # --- CHECK constraints (лише PostgreSQL) ---
    bind = op.get_bind()
    if bind.dialect.name != 'sqlite':
        op.create_check_constraint(
            'ck_events_price_non_negative', 'events',
            'price >= 0'
        )
        op.create_check_constraint(
            'ck_trainers_experience_non_negative', 'trainers',
            'experience_years >= 0'
        )
        op.create_check_constraint(
            'ck_registrations_experience_non_negative', 'event_registrations',
            'experience_years >= 0'
        )


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name != 'sqlite':
        op.drop_constraint('ck_registrations_experience_non_negative', 'event_registrations', type_='check')
        op.drop_constraint('ck_trainers_experience_non_negative', 'trainers', type_='check')
        op.drop_constraint('ck_events_price_non_negative', 'events', type_='check')

    op.drop_index('ix_clinics_sort_order', 'clinics')
    op.drop_index('ix_trainers_full_name', 'trainers')
