"""add liqpay fields to site_settings

Revision ID: 4bfb2835d444
Revises: a7b8c9d0e1f2
Create Date: 2026-03-30 17:07:14.333320

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4bfb2835d444'
down_revision = 'a7b8c9d0e1f2'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        batch_op.add_column(sa.Column('liqpay_public_key', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('liqpay_private_key', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('liqpay_sandbox', sa.Boolean(), nullable=True))


def downgrade():
    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        batch_op.drop_column('liqpay_sandbox')
        batch_op.drop_column('liqpay_private_key')
        batch_op.drop_column('liqpay_public_key')
