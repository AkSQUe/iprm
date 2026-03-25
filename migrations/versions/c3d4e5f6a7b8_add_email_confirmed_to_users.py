"""Add email_confirmed to users, email_confirm trigger to email_logs

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-03-25 23:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'c3d4e5f6a7b8'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('email_confirmed', sa.Boolean(), nullable=False, server_default=sa.text('false')))

    op.execute("UPDATE users SET email_confirmed = true")

    op.drop_constraint('ck_email_logs_trigger', 'email_logs', type_='check')
    op.create_check_constraint(
        'ck_email_logs_trigger',
        'email_logs',
        "trigger IN ('registration', 'payment', 'reminder', 'status_change', 'email_confirm', 'test')",
    )


def downgrade():
    op.drop_constraint('ck_email_logs_trigger', 'email_logs', type_='check')
    op.create_check_constraint(
        'ck_email_logs_trigger',
        'email_logs',
        "trigger IN ('registration', 'payment', 'reminder', 'status_change', 'test')",
    )

    op.drop_column('users', 'email_confirmed')
