"""B2B requests: corporate training lead form table

Revision ID: b2b_requests_20260708
Revises: nrp_merge_20260708
Create Date: 2026-07-08 00:00:00.000000

Creates b2b_requests -- leads from the "Для команд і клінік" block on the
course catalog (Multimed reference, Блок 5.1). Admin list at
/admin/b2b-requests; admin email notification reuses the course_request
trigger/recipients.
"""
from alembic import op
import sqlalchemy as sa


revision = 'b2b_requests_20260708'
down_revision = 'nrp_merge_20260708'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'b2b_requests',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('first_name', sa.String(120), nullable=False),
        sa.Column('last_name', sa.String(120), nullable=False),
        sa.Column('phone', sa.String(20), nullable=False),
        sa.Column('email', sa.String(255), nullable=False),
        sa.Column('team_size', sa.String(10), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='new'),
        sa.Column('admin_notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('new', 'contacted', 'closed', 'dismissed')",
                           name='ck_b2b_requests_status'),
        sa.CheckConstraint("team_size IN ('3-5', '6-10', '10+')",
                           name='ck_b2b_requests_team_size'),
    )
    op.create_index('ix_b2b_requests_email', 'b2b_requests', ['email'])
    op.create_index('ix_b2b_requests_status', 'b2b_requests', ['status'])
    op.create_index('ix_b2b_requests_created_at', 'b2b_requests', ['created_at'])


def downgrade():
    op.drop_table('b2b_requests')
