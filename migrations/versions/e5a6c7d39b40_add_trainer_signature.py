"""add trainer signature + certificate lecturer_signature snapshot

Revision ID: e5a6c7d39b40
Revises: d4f5b6c2839a
Create Date: 2026-06-03 19:25:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'e5a6c7d39b40'
down_revision = 'd4f5b6c2839a'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('trainers', schema=None) as batch_op:
        batch_op.add_column(sa.Column('signature', sa.String(length=500), nullable=True))
    with op.batch_alter_table('certificates', schema=None) as batch_op:
        batch_op.add_column(sa.Column('lecturer_signature', sa.String(length=500), nullable=True))


def downgrade():
    with op.batch_alter_table('certificates', schema=None) as batch_op:
        batch_op.drop_column('lecturer_signature')
    with op.batch_alter_table('trainers', schema=None) as batch_op:
        batch_op.drop_column('signature')
