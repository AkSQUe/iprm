"""Add retry_count to email_logs

Revision ID: a1b2c3d4e5f6
Revises: bbfd90f9e6c3
Create Date: 2026-03-25 21:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = 'bbfd90f9e6c3'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('email_logs', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('retry_count', sa.Integer(), nullable=False, server_default='0')
        )


def downgrade():
    with op.batch_alter_table('email_logs', schema=None) as batch_op:
        batch_op.drop_column('retry_count')
