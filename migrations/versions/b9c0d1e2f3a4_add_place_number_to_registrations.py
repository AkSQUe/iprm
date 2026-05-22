"""Add place_number to event_registrations (Фаза 3)

Revision ID: b9c0d1e2f3a4
Revises: a8b9c0d1e2f3
Create Date: 2026-05-22 19:00:00.000000

Sequential номер місця учасника в межах конкретного CourseInstance.
Призначається в момент 'paid'-транзишн (LiqPay callback) або одразу
при створенні безкоштовної реєстрації.

Partial unique index гарантує що два paid-учасники не можуть мати
один номер на тому самому курсі. NULL дозволено для unpaid/cancelled.
"""
from alembic import op
import sqlalchemy as sa


revision = 'b9c0d1e2f3a4'
down_revision = 'a8b9c0d1e2f3'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'event_registrations',
        sa.Column('place_number', sa.Integer(), nullable=True),
    )
    op.create_index(
        'uq_registrations_instance_place',
        'event_registrations',
        ['instance_id', 'place_number'],
        unique=True,
        postgresql_where=sa.text('place_number IS NOT NULL'),
    )


def downgrade():
    op.drop_index(
        'uq_registrations_instance_place',
        table_name='event_registrations',
    )
    op.drop_column('event_registrations', 'place_number')
