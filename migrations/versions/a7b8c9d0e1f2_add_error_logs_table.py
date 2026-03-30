"""Add error_logs table

Revision ID: a7b8c9d0e1f2
Revises: f5a6b7c8d9e0
Create Date: 2026-03-30 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'a7b8c9d0e1f2'
down_revision = 'f5a6b7c8d9e0'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'error_logs',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('error_code', sa.Integer(), nullable=False),
        sa.Column('error_type', sa.String(100), nullable=False),
        sa.Column('error_message', sa.Text(), nullable=False),
        sa.Column('url', sa.String(500)),
        sa.Column('method', sa.String(10)),
        sa.Column('ip_address', sa.String(45)),
        sa.Column('user_agent', sa.Text()),
        sa.Column('referrer', sa.String(500)),
        sa.Column('user_id', sa.BigInteger(), sa.ForeignKey('users.id', ondelete='SET NULL')),
        sa.Column('traceback', sa.Text()),
        sa.Column('request_data', sa.Text()),
        sa.Column('headers', sa.Text()),
        sa.Column('resolved', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('resolved_at', sa.DateTime(timezone=True)),
        sa.Column('resolved_by_id', sa.BigInteger(), sa.ForeignKey('users.id', ondelete='SET NULL')),
        sa.Column('resolution_notes', sa.Text()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_error_logs_error_code', 'error_logs', ['error_code'])
    op.create_index('ix_error_logs_error_type', 'error_logs', ['error_type'])
    op.create_index('ix_error_logs_resolved', 'error_logs', ['resolved'])
    op.create_index('ix_error_logs_user_id', 'error_logs', ['user_id'])
    op.create_index('ix_error_logs_created_at', 'error_logs', ['created_at'])
    op.create_index('ix_error_logs_resolved_by_id', 'error_logs', ['resolved_by_id'])
    op.create_index('idx_error_logs_resolved_created', 'error_logs', ['resolved', sa.text('created_at DESC')])


def downgrade():
    op.drop_table('error_logs')
