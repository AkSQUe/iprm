"""злиття гілок: види заходів БПР і розділення балів

Revision ID: merge_bpr_heads_20260910
Revises: bpr_event_types_20260909, bpr_points_split_20260909
Create Date: 2026-09-10 08:56:57.594338

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'merge_bpr_heads_20260910'
down_revision = ('bpr_event_types_20260909', 'bpr_points_split_20260909')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
