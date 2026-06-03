"""add lecturer certificate fields: trainer dative name + course lecturer points

Revision ID: f6b7d8e94a51
Revises: e5a6c7d39b40
Create Date: 2026-06-03 20:10:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'f6b7d8e94a51'
down_revision = 'e5a6c7d39b40'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('trainers', schema=None) as batch_op:
        batch_op.add_column(sa.Column('full_name_dative', sa.String(length=200), nullable=True))
    with op.batch_alter_table('courses', schema=None) as batch_op:
        batch_op.add_column(sa.Column('bpr_lecturer_points', sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table('courses', schema=None) as batch_op:
        batch_op.drop_column('bpr_lecturer_points')
    with op.batch_alter_table('trainers', schema=None) as batch_op:
        batch_op.drop_column('full_name_dative')
