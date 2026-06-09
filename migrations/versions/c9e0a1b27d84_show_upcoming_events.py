"""add SiteSettings.show_upcoming_events

Revision ID: c9e0a1b27d84
Revises: e7d6c5b4a3f2
Create Date: 2026-06-03 22:10:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'c9e0a1b27d84'
down_revision = 'e7d6c5b4a3f2'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('site_settings', sa.Column(
        'show_upcoming_events', sa.Boolean(),
        nullable=False, server_default=sa.false(),
    ))


def downgrade():
    op.drop_column('site_settings', 'show_upcoming_events')
