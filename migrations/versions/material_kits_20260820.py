"""Комплекти матеріалів під курс (material_kits, material_kit_items).

Revision ID: material_kits_20260820
Revises: material_cost_20260820
"""
import sqlalchemy as sa
from alembic import op

revision = 'material_kits_20260820'
down_revision = 'material_cost_20260820'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'material_kits',
        sa.Column('id', sa.BigInteger().with_variant(sa.Integer, 'sqlite'),
                  primary_key=True),
        sa.Column('course_id', sa.BigInteger, nullable=True),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('is_default', sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column('notes', sa.Text, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['course_id'], ['courses.id'], ondelete='CASCADE'),
    )
    op.create_index('ix_material_kits_course_id', 'material_kits', ['course_id'])

    op.create_table(
        'material_kit_items',
        sa.Column('id', sa.BigInteger().with_variant(sa.Integer, 'sqlite'),
                  primary_key=True),
        sa.Column('kit_id', sa.BigInteger, nullable=False),
        sa.Column('sku', sa.String(100), nullable=False),
        sa.Column('name_snapshot', sa.String(255), nullable=True),
        sa.Column('quantity', sa.Integer, nullable=False),
        sa.Column('is_required', sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column('note', sa.Text, nullable=True),
        sa.ForeignKeyConstraint(['kit_id'], ['material_kits.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('kit_id', 'sku', name='uq_material_kit_items_kit_sku'),
        sa.CheckConstraint('quantity > 0', name='ck_material_kit_items_quantity_positive'),
    )
    op.create_index('ix_material_kit_items_kit_id', 'material_kit_items', ['kit_id'])


def downgrade():
    op.drop_table('material_kit_items')
    op.drop_table('material_kits')
