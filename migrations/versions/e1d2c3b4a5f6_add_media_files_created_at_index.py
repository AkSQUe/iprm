"""add index on media_files.created_at (sorting media library)

Revision ID: e1d2c3b4a5f6
Revises: b9c8d7e6f5a4
Create Date: 2026-06-11

Медіа-бібліотека сортує за created_at DESC; додаємо індекс, щоб уникнути
filesort у міру зростання таблиці.
"""
from alembic import op


revision = 'e1d2c3b4a5f6'
down_revision = 'b9c8d7e6f5a4'
branch_labels = None
depends_on = None


def upgrade():
    op.create_index('ix_media_files_created_at', 'media_files', ['created_at'])


def downgrade():
    op.drop_index('ix_media_files_created_at', table_name='media_files')
