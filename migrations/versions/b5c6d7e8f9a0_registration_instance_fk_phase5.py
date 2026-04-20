"""Phase 5: registration може посилатися на instance_id (або на event_id, legacy).

Зміни:
- event_registrations.event_id -> nullable
- drop constraint uq_user_event_registration (user_id, event_id)
- add unique (user_id, instance_id) -- одна реєстрація на instance
- add CHECK: (event_id IS NOT NULL) OR (instance_id IS NOT NULL)

Revision ID: b5c6d7e8f9a0
Revises: a3b4c5d6e7f8
Create Date: 2026-04-21 01:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'b5c6d7e8f9a0'
down_revision = 'a3b4c5d6e7f8'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('event_registrations', schema=None) as batch_op:
        batch_op.alter_column('event_id', existing_type=sa.BigInteger(), nullable=True)
        batch_op.drop_constraint('uq_user_event_registration', type_='unique')
        batch_op.create_unique_constraint(
            'uq_user_instance_registration',
            ['user_id', 'instance_id'],
        )
        batch_op.create_check_constraint(
            'ck_registrations_target_not_null',
            'event_id IS NOT NULL OR instance_id IS NOT NULL',
        )


def downgrade():
    with op.batch_alter_table('event_registrations', schema=None) as batch_op:
        batch_op.drop_constraint('ck_registrations_target_not_null', type_='check')
        batch_op.drop_constraint('uq_user_instance_registration', type_='unique')
        batch_op.create_unique_constraint(
            'uq_user_event_registration',
            ['user_id', 'event_id'],
        )
        batch_op.alter_column('event_id', existing_type=sa.BigInteger(), nullable=False)
