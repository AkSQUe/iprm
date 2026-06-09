"""add trainer regalia (certificates, patents, articles)

Revision ID: f1b2a3c4d5e6
Revises: a9f2c7d41b6e
Create Date: 2026-06-09 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f1b2a3c4d5e6'
down_revision = 'a9f2c7d41b6e'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('trainers', schema=None) as batch_op:
        batch_op.add_column(sa.Column('certificates', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('patents', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('articles', sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table('trainers', schema=None) as batch_op:
        batch_op.drop_column('articles')
        batch_op.drop_column('patents')
        batch_op.drop_column('certificates')
