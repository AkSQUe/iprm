"""Instance tariffs: pricing fork per course run (E1 phase 1)

Revision ID: instance_tariffs_20260708
Revises: b2b_requests_20260708
Create Date: 2026-07-08 00:00:00.000000

Creates instance_tariffs -- participation options (економ -> преміум:
Онлайн / Онлайн+ / Практикум / Практикум з менторством) attached to a
CourseInstance. Prices are entered manually per tariff. When a run has
active tariffs its effective_price becomes the cheapest tariff
("від N грн"). Admin CRUD at /admin/instances/<id>/tariffs.
"""
from alembic import op
import sqlalchemy as sa


revision = 'instance_tariffs_20260708'
down_revision = 'b2b_requests_20260708'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'instance_tariffs',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('instance_id', sa.BigInteger(),
                  sa.ForeignKey('course_instances.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('price', sa.Numeric(10, 2), nullable=False),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint('price >= 0', name='ck_instance_tariffs_price_non_negative'),
    )
    op.create_index('ix_instance_tariffs_instance_id', 'instance_tariffs', ['instance_id'])
    op.create_index('ix_instance_tariffs_instance_sort', 'instance_tariffs',
                    ['instance_id', 'sort_order'])


def downgrade():
    op.drop_table('instance_tariffs')
