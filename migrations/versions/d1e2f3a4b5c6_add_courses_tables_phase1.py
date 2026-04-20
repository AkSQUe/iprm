"""Phase 1: додати таблиці courses, course_instances, course_requests
+ nullable FK-колонки course_id (program_blocks) та instance_id (event_registrations)

Ця міграція additive -- не чіпає існуючі дані в events/program_blocks/registrations.
Phase 2 (окремою міграцією) перенесе дані з events у courses+instances.

Revision ID: d1e2f3a4b5c6
Revises: e7f8a9b0c1d2
Create Date: 2026-04-21 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'd1e2f3a4b5c6'
down_revision = 'e7f8a9b0c1d2'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'courses',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('slug', sa.String(length=200), nullable=False),
        sa.Column('subtitle', sa.String(length=500), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('short_description', sa.String(length=500), nullable=True),
        sa.Column('event_type', sa.String(length=30), nullable=True),
        sa.Column('hero_image', sa.String(length=500), nullable=True),
        sa.Column('card_image', sa.String(length=500), nullable=True),
        sa.Column('target_audience', sa.JSON(), nullable=True),
        sa.Column('tags', sa.JSON(), nullable=True),
        sa.Column('speaker_info', sa.Text(), nullable=True),
        sa.Column('agenda', sa.Text(), nullable=True),
        sa.Column('faq', sa.JSON(), nullable=True),
        sa.Column('base_price', sa.Numeric(precision=10, scale=2), server_default='0', nullable=True),
        sa.Column('cpd_points', sa.Integer(), nullable=True),
        sa.Column('max_participants', sa.Integer(), nullable=True),
        sa.Column('trainer_id', sa.BigInteger(), nullable=True),
        sa.Column('created_by', sa.BigInteger(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default=sa.true(), nullable=True),
        sa.Column('is_featured', sa.Boolean(), server_default=sa.false(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['trainer_id'], ['trainers.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('slug'),
        sa.CheckConstraint(
            "event_type IN ('seminar', 'webinar', 'course', 'masterclass', 'conference')",
            name='ck_courses_event_type',
        ),
        sa.CheckConstraint('base_price >= 0', name='ck_courses_base_price_non_negative'),
        sa.CheckConstraint(
            'cpd_points >= 0 OR cpd_points IS NULL',
            name='ck_courses_cpd_points_non_negative',
        ),
        sa.CheckConstraint(
            'max_participants >= 1 OR max_participants IS NULL',
            name='ck_courses_max_participants_positive',
        ),
    )
    op.create_index('ix_courses_trainer_id', 'courses', ['trainer_id'])
    op.create_index('ix_courses_created_by', 'courses', ['created_by'])
    op.create_index('ix_courses_is_active', 'courses', ['is_active'])
    op.create_index('ix_courses_active_featured', 'courses', ['is_active', 'is_featured'])
    op.create_index('ix_courses_created_at', 'courses', ['created_at'])

    op.create_table(
        'course_instances',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('course_id', sa.BigInteger(), nullable=False),
        sa.Column('start_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('end_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('event_format', sa.String(length=20), nullable=True),
        sa.Column('price', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('cpd_points', sa.Integer(), nullable=True),
        sa.Column('max_participants', sa.Integer(), nullable=True),
        sa.Column('location', sa.String(length=255), nullable=True),
        sa.Column('online_link', sa.String(length=500), nullable=True),
        sa.Column('trainer_id', sa.BigInteger(), nullable=True),
        sa.Column('status', sa.String(length=20), server_default='draft', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['course_id'], ['courses.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['trainer_id'], ['trainers.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint(
            "event_format IN ('online', 'offline', 'hybrid')",
            name='ck_course_instances_event_format',
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'published', 'active', 'completed', 'cancelled')",
            name='ck_course_instances_status',
        ),
        sa.CheckConstraint(
            'price >= 0 OR price IS NULL',
            name='ck_course_instances_price_non_negative',
        ),
        sa.CheckConstraint(
            'cpd_points >= 0 OR cpd_points IS NULL',
            name='ck_course_instances_cpd_points_non_negative',
        ),
        sa.CheckConstraint(
            'max_participants >= 1 OR max_participants IS NULL',
            name='ck_course_instances_max_participants_positive',
        ),
    )
    op.create_index('ix_course_instances_course_id', 'course_instances', ['course_id'])
    op.create_index('ix_course_instances_trainer_id', 'course_instances', ['trainer_id'])
    op.create_index('ix_course_instances_status', 'course_instances', ['status'])
    op.create_index('ix_course_instances_start_date', 'course_instances', ['start_date'])
    op.create_index('ix_course_instances_course_status', 'course_instances', ['course_id', 'status'])

    op.create_table(
        'course_requests',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('course_id', sa.BigInteger(), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=True),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('phone', sa.String(length=20), nullable=True),
        sa.Column('message', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=20), server_default='pending', nullable=False),
        sa.Column('admin_notes', sa.Text(), nullable=True),
        sa.Column('resolved_by_id', sa.BigInteger(), nullable=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['course_id'], ['courses.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['resolved_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint(
            "status IN ('pending', 'responded', 'scheduled', 'dismissed')",
            name='ck_course_requests_status',
        ),
    )
    op.create_index('ix_course_requests_course_id', 'course_requests', ['course_id'])
    op.create_index('ix_course_requests_user_id', 'course_requests', ['user_id'])
    op.create_index('ix_course_requests_email', 'course_requests', ['email'])
    op.create_index('ix_course_requests_status', 'course_requests', ['status'])
    op.create_index('ix_course_requests_course_status', 'course_requests', ['course_id', 'status'])
    op.create_index('ix_course_requests_created_at', 'course_requests', ['created_at'])

    # Nullable FK на нові таблиці -- існуючі рядки отримають NULL
    with op.batch_alter_table('program_blocks', schema=None) as batch_op:
        batch_op.add_column(sa.Column('course_id', sa.BigInteger(), nullable=True))
        batch_op.create_foreign_key(
            'fk_program_blocks_course_id',
            'courses',
            ['course_id'],
            ['id'],
            ondelete='CASCADE',
        )
        batch_op.create_index('ix_program_blocks_course_id', ['course_id'])

    with op.batch_alter_table('event_registrations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('instance_id', sa.BigInteger(), nullable=True))
        batch_op.create_foreign_key(
            'fk_event_registrations_instance_id',
            'course_instances',
            ['instance_id'],
            ['id'],
            ondelete='CASCADE',
        )
        batch_op.create_index('ix_event_registrations_instance_id', ['instance_id'])


def downgrade():
    with op.batch_alter_table('event_registrations', schema=None) as batch_op:
        batch_op.drop_index('ix_event_registrations_instance_id')
        batch_op.drop_constraint('fk_event_registrations_instance_id', type_='foreignkey')
        batch_op.drop_column('instance_id')

    with op.batch_alter_table('program_blocks', schema=None) as batch_op:
        batch_op.drop_index('ix_program_blocks_course_id')
        batch_op.drop_constraint('fk_program_blocks_course_id', type_='foreignkey')
        batch_op.drop_column('course_id')

    op.drop_index('ix_course_requests_created_at', table_name='course_requests')
    op.drop_index('ix_course_requests_course_status', table_name='course_requests')
    op.drop_index('ix_course_requests_status', table_name='course_requests')
    op.drop_index('ix_course_requests_email', table_name='course_requests')
    op.drop_index('ix_course_requests_user_id', table_name='course_requests')
    op.drop_index('ix_course_requests_course_id', table_name='course_requests')
    op.drop_table('course_requests')

    op.drop_index('ix_course_instances_course_status', table_name='course_instances')
    op.drop_index('ix_course_instances_start_date', table_name='course_instances')
    op.drop_index('ix_course_instances_status', table_name='course_instances')
    op.drop_index('ix_course_instances_trainer_id', table_name='course_instances')
    op.drop_index('ix_course_instances_course_id', table_name='course_instances')
    op.drop_table('course_instances')

    op.drop_index('ix_courses_created_at', table_name='courses')
    op.drop_index('ix_courses_active_featured', table_name='courses')
    op.drop_index('ix_courses_is_active', table_name='courses')
    op.drop_index('ix_courses_created_by', table_name='courses')
    op.drop_index('ix_courses_trainer_id', table_name='courses')
    op.drop_table('courses')
