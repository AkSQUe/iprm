"""Додати індекси, CHECK constraints та CASCADE правила

Revision ID: a3f7c2e91b04
Revises: 6481b908cc37
Create Date: 2026-03-24 18:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a3f7c2e91b04'
down_revision = '6481b908cc37'
branch_labels = None
depends_on = None


def upgrade():
    # --- events: нові індекси ---
    op.create_index('ix_events_start_date', 'events', ['start_date'])
    op.create_index('ix_events_created_by', 'events', ['created_by'])
    op.create_index('ix_events_trainer_id', 'events', ['trainer_id'])
    op.create_index('ix_events_active_status', 'events', ['is_active', 'status'])

    # --- event_registrations: нові індекси ---
    op.create_index('ix_registrations_event_status', 'event_registrations', ['event_id', 'status'])
    op.create_index('ix_registrations_created_at', 'event_registrations', ['created_at'])

    # --- events: CHECK constraints ---
    # SQLite не підтримує ALTER TABLE ADD CONSTRAINT, тому перевіряємо dialect
    bind = op.get_bind()
    if bind.dialect.name != 'sqlite':
        op.create_check_constraint(
            'ck_events_event_type', 'events',
            "event_type IN ('seminar', 'webinar', 'course', 'masterclass', 'conference')"
        )
        op.create_check_constraint(
            'ck_events_event_format', 'events',
            "event_format IN ('online', 'offline', 'hybrid')"
        )
        op.create_check_constraint(
            'ck_events_status', 'events',
            "status IN ('draft', 'published', 'active', 'completed', 'cancelled')"
        )

        # --- event_registrations: CHECK constraints ---
        op.create_check_constraint(
            'ck_registrations_status', 'event_registrations',
            "status IN ('pending', 'confirmed', 'cancelled', 'completed')"
        )
        op.create_check_constraint(
            'ck_registrations_payment_status', 'event_registrations',
            "payment_status IN ('unpaid', 'pending', 'paid', 'refunded')"
        )

    # --- CASCADE правила: потребують batch mode для SQLite ---
    with op.batch_alter_table('events') as batch_op:
        batch_op.drop_constraint('events_created_by_fkey', type_='foreignkey')
        batch_op.create_foreign_key(
            'events_created_by_fkey', 'users',
            ['created_by'], ['id'], ondelete='SET NULL'
        )
        batch_op.drop_constraint('events_trainer_id_fkey', type_='foreignkey')
        batch_op.create_foreign_key(
            'events_trainer_id_fkey', 'trainers',
            ['trainer_id'], ['id'], ondelete='SET NULL'
        )

    with op.batch_alter_table('program_blocks') as batch_op:
        batch_op.drop_constraint('program_blocks_event_id_fkey', type_='foreignkey')
        batch_op.create_foreign_key(
            'program_blocks_event_id_fkey', 'events',
            ['event_id'], ['id'], ondelete='CASCADE'
        )

    with op.batch_alter_table('event_registrations') as batch_op:
        batch_op.drop_constraint('event_registrations_user_id_fkey', type_='foreignkey')
        batch_op.create_foreign_key(
            'event_registrations_user_id_fkey', 'users',
            ['user_id'], ['id'], ondelete='CASCADE'
        )
        batch_op.drop_constraint('event_registrations_event_id_fkey', type_='foreignkey')
        batch_op.create_foreign_key(
            'event_registrations_event_id_fkey', 'events',
            ['event_id'], ['id'], ondelete='CASCADE'
        )


def downgrade():
    # --- Видалити CASCADE правила (повернути без ondelete) ---
    with op.batch_alter_table('event_registrations') as batch_op:
        batch_op.drop_constraint('event_registrations_event_id_fkey', type_='foreignkey')
        batch_op.create_foreign_key(
            'event_registrations_event_id_fkey', 'events',
            ['event_id'], ['id']
        )
        batch_op.drop_constraint('event_registrations_user_id_fkey', type_='foreignkey')
        batch_op.create_foreign_key(
            'event_registrations_user_id_fkey', 'users',
            ['user_id'], ['id']
        )

    with op.batch_alter_table('program_blocks') as batch_op:
        batch_op.drop_constraint('program_blocks_event_id_fkey', type_='foreignkey')
        batch_op.create_foreign_key(
            'program_blocks_event_id_fkey', 'events',
            ['event_id'], ['id']
        )

    with op.batch_alter_table('events') as batch_op:
        batch_op.drop_constraint('events_trainer_id_fkey', type_='foreignkey')
        batch_op.create_foreign_key(
            'events_trainer_id_fkey', 'trainers',
            ['trainer_id'], ['id']
        )
        batch_op.drop_constraint('events_created_by_fkey', type_='foreignkey')
        batch_op.create_foreign_key(
            'events_created_by_fkey', 'users',
            ['created_by'], ['id']
        )

    # --- Видалити CHECK constraints ---
    bind = op.get_bind()
    if bind.dialect.name != 'sqlite':
        op.drop_constraint('ck_registrations_payment_status', 'event_registrations', type_='check')
        op.drop_constraint('ck_registrations_status', 'event_registrations', type_='check')
        op.drop_constraint('ck_events_status', 'events', type_='check')
        op.drop_constraint('ck_events_event_format', 'events', type_='check')
        op.drop_constraint('ck_events_event_type', 'events', type_='check')

    # --- Видалити індекси ---
    op.drop_index('ix_registrations_created_at', 'event_registrations')
    op.drop_index('ix_registrations_event_status', 'event_registrations')
    op.drop_index('ix_events_active_status', 'events')
    op.drop_index('ix_events_trainer_id', 'events')
    op.drop_index('ix_events_created_by', 'events')
    op.drop_index('ix_events_start_date', 'events')
