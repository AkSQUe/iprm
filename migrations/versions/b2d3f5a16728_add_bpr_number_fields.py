"""add BPR number fields (course event number, provider number)

Revision ID: b2d3f5a16728
Revises: a1c2e3f40516
Create Date: 2026-06-01 13:30:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'b2d3f5a16728'
down_revision = 'c8d9e0f1a2b3'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('courses', schema=None) as batch_op:
        batch_op.add_column(sa.Column('bpr_event_number', sa.String(length=20), nullable=True))
    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'bpr_provider_number', sa.String(length=20),
            nullable=False, server_default='',
        ))


def downgrade():
    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        batch_op.drop_column('bpr_provider_number')
    with op.batch_alter_table('courses', schema=None) as batch_op:
        batch_op.drop_column('bpr_event_number')
