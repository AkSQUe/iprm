"""add trainer profile sections: skills, education, additional_education, work_experience

Revision ID: d1f2e3a4b5c6
Revises: c9e0a1b27d84
Create Date: 2026-06-03 23:10:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'd1f2e3a4b5c6'
down_revision = 'c9e0a1b27d84'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('trainers', schema=None) as batch_op:
        batch_op.add_column(sa.Column('skills', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('education', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('additional_education', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('work_experience', sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table('trainers', schema=None) as batch_op:
        batch_op.drop_column('work_experience')
        batch_op.drop_column('additional_education')
        batch_op.drop_column('education')
        batch_op.drop_column('skills')
