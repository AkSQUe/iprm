"""Drop legacy events table та event_id колонки.

Після того як:
  * всі event_registrations мають instance_id (Phase 2 + Phase 5)
  * всі program_blocks мають course_id (Phase 2)
  * жоден код більше не посилається на Event model (Phase 8)

Видаляємо:
  * event_registrations.event_id + FK + старий індекс + CHECK constraint
  * program_blocks.event_id + FK + старий індекс
  * таблицю events (каскадно дропає FK з інших таблиць)

Revision ID: c7d8e9f0a1b2
Revises: b5c6d7e8f9a0
Create Date: 2026-04-21 02:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'c7d8e9f0a1b2'
down_revision = 'b5c6d7e8f9a0'
branch_labels = None
depends_on = None


def upgrade():
    # event_registrations: зробити instance_id NOT NULL, прибрати event_id
    with op.batch_alter_table('event_registrations', schema=None) as batch_op:
        batch_op.drop_constraint('ck_registrations_target_not_null', type_='check')
        batch_op.drop_index('ix_registrations_event_status')
        batch_op.create_index(
            'ix_registrations_instance_status', ['instance_id', 'status'],
        )
        batch_op.alter_column('instance_id', existing_type=sa.BigInteger(), nullable=False)
        batch_op.drop_constraint('event_registrations_event_id_fkey', type_='foreignkey')
        batch_op.drop_index('ix_event_registrations_event_id')
        batch_op.drop_column('event_id')

    # program_blocks: course_id NOT NULL, прибрати event_id
    with op.batch_alter_table('program_blocks', schema=None) as batch_op:
        batch_op.alter_column('course_id', existing_type=sa.BigInteger(), nullable=False)
        batch_op.drop_constraint('program_blocks_event_id_fkey', type_='foreignkey')
        batch_op.drop_index('ix_program_blocks_event_id')
        batch_op.drop_column('event_id')

    # Нарешті -- таблиця events
    op.drop_table('events')


def downgrade():
    # Відновлення не тривіальне (втрачаємо event_id mapping). Створюємо
    # порожню таблицю events + nullable event_id колонки, але дані
    # не відновлюються -- це навмисна односпрямована міграція.
    op.create_table(
        'events',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('slug', sa.String(length=200), nullable=False),
        sa.Column('subtitle', sa.String(length=500), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('short_description', sa.String(length=500), nullable=True),
        sa.Column('event_type', sa.String(length=30), nullable=True),
        sa.Column('event_format', sa.String(length=20), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=True),
        sa.Column('start_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('end_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('max_participants', sa.Integer(), nullable=True),
        sa.Column('price', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('location', sa.String(length=255), nullable=True),
        sa.Column('online_link', sa.String(length=500), nullable=True),
        sa.Column('hero_image', sa.String(length=500), nullable=True),
        sa.Column('card_image', sa.String(length=500), nullable=True),
        sa.Column('cpd_points', sa.Integer(), nullable=True),
        sa.Column('target_audience', sa.JSON(), nullable=True),
        sa.Column('tags', sa.JSON(), nullable=True),
        sa.Column('speaker_info', sa.Text(), nullable=True),
        sa.Column('agenda', sa.Text(), nullable=True),
        sa.Column('faq', sa.JSON(), nullable=True),
        sa.Column('is_featured', sa.Boolean(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('created_by', sa.BigInteger(), nullable=True),
        sa.Column('trainer_id', sa.BigInteger(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('slug'),
    )
    with op.batch_alter_table('program_blocks', schema=None) as batch_op:
        batch_op.add_column(sa.Column('event_id', sa.BigInteger(), nullable=True))
        batch_op.create_index('ix_program_blocks_event_id', ['event_id'])
        batch_op.create_foreign_key(
            'program_blocks_event_id_fkey', 'events', ['event_id'], ['id'],
            ondelete='CASCADE',
        )
        batch_op.alter_column('course_id', existing_type=sa.BigInteger(), nullable=True)

    with op.batch_alter_table('event_registrations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('event_id', sa.BigInteger(), nullable=True))
        batch_op.create_index('ix_event_registrations_event_id', ['event_id'])
        batch_op.create_foreign_key(
            'event_registrations_event_id_fkey', 'events', ['event_id'], ['id'],
            ondelete='CASCADE',
        )
        batch_op.alter_column('instance_id', existing_type=sa.BigInteger(), nullable=True)
        batch_op.drop_index('ix_registrations_instance_status')
        batch_op.create_index('ix_registrations_event_status', ['event_id', 'status'])
        batch_op.create_check_constraint(
            'ck_registrations_target_not_null',
            'event_id IS NOT NULL OR instance_id IS NOT NULL',
        )
