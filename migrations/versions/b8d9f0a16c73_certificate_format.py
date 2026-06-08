"""add SiteSettings.certificate_format

Revision ID: b8d9f0a16c73
Revises: a7c8e9f05b62
Create Date: 2026-06-03 21:10:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'b8d9f0a16c73'
down_revision = 'a7c8e9f05b62'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('site_settings', sa.Column(
        'certificate_format', sa.String(length=20),
        nullable=False, server_default='a4',
    ))


def downgrade():
    op.drop_column('site_settings', 'certificate_format')
