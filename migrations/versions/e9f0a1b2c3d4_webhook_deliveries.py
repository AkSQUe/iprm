"""Add webhook_deliveries table -- persisted partner webhook queue.

Revision ID: e9f0a1b2c3d4
Revises: d8e9f0a1b2c3
Create Date: 2026-04-21 04:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'e9f0a1b2c3d4'
down_revision = 'd8e9f0a1b2c3'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'webhook_deliveries',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('course_id', sa.BigInteger(), nullable=False),
        sa.Column('course_slug', sa.String(length=200), nullable=False),
        sa.Column('action', sa.String(length=20), nullable=False),
        sa.Column('event_uuid', sa.String(length=32), nullable=False),
        sa.Column('target_url', sa.String(length=500), nullable=False),
        sa.Column('status', sa.String(length=20), server_default='pending', nullable=False),
        sa.Column('attempts', sa.Integer(), server_default='0', nullable=False),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('last_http_status', sa.Integer(), nullable=True),
        sa.Column('next_retry_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('event_uuid'),
        sa.CheckConstraint(
            "action IN ('created', 'updated', 'deleted')",
            name='ck_webhook_deliveries_action',
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'sent', 'failed', 'retrying')",
            name='ck_webhook_deliveries_status',
        ),
        sa.CheckConstraint(
            'attempts >= 0',
            name='ck_webhook_deliveries_attempts_non_negative',
        ),
    )
    op.create_index('ix_webhook_deliveries_course_id', 'webhook_deliveries', ['course_id'])
    op.create_index('ix_webhook_deliveries_status', 'webhook_deliveries', ['status'])
    op.create_index('ix_webhook_deliveries_next_retry_at', 'webhook_deliveries', ['next_retry_at'])
    op.create_index('ix_webhook_deliveries_status_retry', 'webhook_deliveries', ['status', 'next_retry_at'])


def downgrade():
    op.drop_index('ix_webhook_deliveries_status_retry', table_name='webhook_deliveries')
    op.drop_index('ix_webhook_deliveries_next_retry_at', table_name='webhook_deliveries')
    op.drop_index('ix_webhook_deliveries_status', table_name='webhook_deliveries')
    op.drop_index('ix_webhook_deliveries_course_id', table_name='webhook_deliveries')
    op.drop_table('webhook_deliveries')
