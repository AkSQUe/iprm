"""Add course_request_audits table -- журнал змін статусу CourseRequest.

Revision ID: d8e9f0a1b2c3
Revises: c7d8e9f0a1b2
Create Date: 2026-04-21 03:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'd8e9f0a1b2c3'
down_revision = 'c7d8e9f0a1b2'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'course_request_audits',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('request_id', sa.BigInteger(), nullable=False),
        sa.Column('from_status', sa.String(length=20), nullable=True),
        sa.Column('to_status', sa.String(length=20), nullable=False),
        sa.Column('changed_by_id', sa.BigInteger(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['request_id'], ['course_requests.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['changed_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_course_request_audits_request_id',
        'course_request_audits', ['request_id'],
    )
    op.create_index(
        'ix_course_request_audits_changed_by_id',
        'course_request_audits', ['changed_by_id'],
    )


def downgrade():
    op.drop_index('ix_course_request_audits_changed_by_id', table_name='course_request_audits')
    op.drop_index('ix_course_request_audits_request_id', table_name='course_request_audits')
    op.drop_table('course_request_audits')
