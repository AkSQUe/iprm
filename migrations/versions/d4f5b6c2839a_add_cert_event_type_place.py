"""add certificate event_type_label + event_place snapshots

Revision ID: d4f5b6c2839a
Revises: c3e4a6b27839
Create Date: 2026-06-03 17:10:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'd4f5b6c2839a'
down_revision = 'c3e4a6b27839'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('certificates', schema=None) as batch_op:
        batch_op.add_column(sa.Column('event_type_label', sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column('event_place', sa.String(length=255), nullable=True))


def downgrade():
    with op.batch_alter_table('certificates', schema=None) as batch_op:
        batch_op.drop_column('event_place')
        batch_op.drop_column('event_type_label')
