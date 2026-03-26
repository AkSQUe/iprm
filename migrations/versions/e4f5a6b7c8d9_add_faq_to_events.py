"""Add faq JSON column to events

Revision ID: e4f5a6b7c8d9
Revises: a20d49aa9261
Create Date: 2026-03-26 23:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'e4f5a6b7c8d9'
down_revision = 'a20d49aa9261'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('events', schema=None) as batch_op:
        batch_op.add_column(sa.Column('faq', sa.JSON(), nullable=True, server_default='[]'))


def downgrade():
    with op.batch_alter_table('events', schema=None) as batch_op:
        batch_op.drop_column('faq')
