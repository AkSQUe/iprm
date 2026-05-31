"""add lecturer_name to certificates

Revision ID: a1c2e3f40516
Revises: 335735f0067d
Create Date: 2026-05-31 19:40:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'a1c2e3f40516'
down_revision = '335735f0067d'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('certificates', schema=None) as batch_op:
        batch_op.add_column(sa.Column('lecturer_name', sa.String(length=200), nullable=True))


def downgrade():
    with op.batch_alter_table('certificates', schema=None) as batch_op:
        batch_op.drop_column('lecturer_name')
