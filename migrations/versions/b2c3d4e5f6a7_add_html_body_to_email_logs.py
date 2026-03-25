"""Add html_body to email_logs for retry support

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-03-25 22:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'b2c3d4e5f6a7'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('email_logs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('html_body', sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table('email_logs', schema=None) as batch_op:
        batch_op.drop_column('html_body')
