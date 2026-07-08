"""Course tariffs: default pricing fork templates (copy-on-create)

Revision ID: course_tariffs_20260708
Revises: reg_tariff_20260708
Create Date: 2026-07-08 00:00:00.000000

Creates course_tariffs -- default tariff templates on the Course. When an
admin creates a CourseInstance, active templates matching the run's format
are COPIED into instance_tariffs (hybrid gets all, NULL format matches
any). instance_tariffs stays the source of truth for sales; editing
templates never mutates existing runs.
"""
from alembic import op
import sqlalchemy as sa


revision = 'course_tariffs_20260708'
down_revision = 'reg_tariff_20260708'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'course_tariffs',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('course_id', sa.BigInteger(),
                  sa.ForeignKey('courses.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('price', sa.Numeric(10, 2), nullable=False),
        sa.Column('event_format', sa.String(20), nullable=True),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint('price >= 0', name='ck_course_tariffs_price_non_negative'),
        sa.CheckConstraint("event_format IN ('online', 'offline') OR event_format IS NULL",
                           name='ck_course_tariffs_event_format'),
    )
    op.create_index('ix_course_tariffs_course_id', 'course_tariffs', ['course_id'])
    op.create_index('ix_course_tariffs_course_sort', 'course_tariffs',
                    ['course_id', 'sort_order'])


def downgrade():
    op.drop_table('course_tariffs')
