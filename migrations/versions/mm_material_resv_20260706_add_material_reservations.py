"""Add material_reservations + material_reservation_items (IPRM-side history)

Revision ID: mm_material_resv_20260706
Revises: mm_medic_settings_20260706
Create Date: 2026-07-06 00:10:00.000000

IPRM's own audit of consumable-material reservations placed with MM Medic, keyed
to a CourseInstance. Product identity is snapshotted per line.
"""
from alembic import op
import sqlalchemy as sa


revision = 'mm_material_resv_20260706'
down_revision = 'mm_medic_settings_20260706'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'material_reservations',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('instance_id', sa.BigInteger(), nullable=False),
        sa.Column('external_ref', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='draft'),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('consumed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_response', sa.JSON(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['instance_id'], ['course_instances.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_material_reservations_instance_id'),
                    'material_reservations', ['instance_id'], unique=False)
    op.create_index(op.f('ix_material_reservations_external_ref'),
                    'material_reservations', ['external_ref'], unique=True)
    op.create_index(op.f('ix_material_reservations_status'),
                    'material_reservations', ['status'], unique=False)

    op.create_table(
        'material_reservation_items',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('reservation_id', sa.BigInteger(), nullable=False),
        sa.Column('sku', sa.String(length=100), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=True),
        sa.Column('image_url', sa.String(length=500), nullable=True),
        sa.Column('quantity_reserved', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('quantity_actual', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['reservation_id'], ['material_reservations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('reservation_id', 'sku', name='uq_material_item_sku'),
    )
    op.create_index(op.f('ix_material_reservation_items_reservation_id'),
                    'material_reservation_items', ['reservation_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_material_reservation_items_reservation_id'),
                  table_name='material_reservation_items')
    op.drop_table('material_reservation_items')
    op.drop_index(op.f('ix_material_reservations_status'), table_name='material_reservations')
    op.drop_index(op.f('ix_material_reservations_external_ref'), table_name='material_reservations')
    op.drop_index(op.f('ix_material_reservations_instance_id'), table_name='material_reservations')
    op.drop_table('material_reservations')
