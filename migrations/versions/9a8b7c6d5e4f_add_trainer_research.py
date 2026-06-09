"""add trainer.research (scientific & research activity)

Revision ID: 9a8b7c6d5e4f
Revises: f1b2a3c4d5e6
Create Date: 2026-06-09 13:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9a8b7c6d5e4f'
down_revision = 'f1b2a3c4d5e6'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('trainers', schema=None) as batch_op:
        batch_op.add_column(sa.Column('research', sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table('trainers', schema=None) as batch_op:
        batch_op.drop_column('research')
