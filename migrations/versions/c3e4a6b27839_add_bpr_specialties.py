"""add BPR specialties (course + certificate snapshot)

Revision ID: c3e4a6b27839
Revises: b2d3f5a16728
Create Date: 2026-06-03 16:40:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'c3e4a6b27839'
down_revision = 'b2d3f5a16728'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('courses', schema=None) as batch_op:
        batch_op.add_column(sa.Column('bpr_specialties', sa.String(length=500), nullable=True))
    with op.batch_alter_table('certificates', schema=None) as batch_op:
        batch_op.add_column(sa.Column('specialties', sa.String(length=500), nullable=True))


def downgrade():
    with op.batch_alter_table('certificates', schema=None) as batch_op:
        batch_op.drop_column('specialties')
    with op.batch_alter_table('courses', schema=None) as batch_op:
        batch_op.drop_column('bpr_specialties')
