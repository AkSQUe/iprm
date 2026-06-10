"""add media_files registry table

Revision ID: b8c9d0e1f2a3
Revises: d1f2e3a4b5c6
Create Date: 2026-06-10 09:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'b8c9d0e1f2a3'
down_revision = 'd1f2e3a4b5c6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'media_files',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('uploaded_by', sa.BigInteger(), nullable=True),
        sa.Column('filename', sa.String(length=255), nullable=False),
        sa.Column('original_name', sa.String(length=255), nullable=True),
        sa.Column('file_path', sa.String(length=500), nullable=False),
        sa.Column('mime_type', sa.String(length=100), nullable=False, server_default='application/octet-stream'),
        sa.Column('file_size', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('width', sa.Integer(), nullable=True),
        sa.Column('height', sa.Integer(), nullable=True),
        sa.Column('alt_text', sa.String(length=255), nullable=True),
        sa.Column('entity_type', sa.String(length=50), nullable=True),
        sa.Column('entity_id', sa.BigInteger(), nullable=True),
        sa.Column('usage_type', sa.String(length=50), nullable=False, server_default='main'),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('responsive_variants', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['uploaded_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint('file_size >= 0', name='ck_media_files_size_non_negative'),
    )
    with op.batch_alter_table('media_files', schema=None) as batch_op:
        batch_op.create_index('ix_media_files_uploaded_by', ['uploaded_by'], unique=False)
        batch_op.create_index('ix_media_files_entity_type', ['entity_type'], unique=False)
        batch_op.create_index('ix_media_files_entity_id', ['entity_id'], unique=False)
        batch_op.create_index('ix_media_files_usage_type', ['usage_type'], unique=False)
        batch_op.create_index('ix_media_files_is_active', ['is_active'], unique=False)
        batch_op.create_index('ix_media_entity_usage_active', ['entity_type', 'entity_id', 'usage_type', 'is_active'], unique=False)


def downgrade():
    with op.batch_alter_table('media_files', schema=None) as batch_op:
        batch_op.drop_index('ix_media_entity_usage_active')
        batch_op.drop_index('ix_media_files_is_active')
        batch_op.drop_index('ix_media_files_usage_type')
        batch_op.drop_index('ix_media_files_entity_id')
        batch_op.drop_index('ix_media_files_entity_type')
        batch_op.drop_index('ix_media_files_uploaded_by')
    op.drop_table('media_files')
