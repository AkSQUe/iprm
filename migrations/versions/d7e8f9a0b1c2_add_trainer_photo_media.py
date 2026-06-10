"""add photo_media_id to trainers (media registry integration -- phase 4)

Revision ID: d7e8f9a0b1c2
Revises: b1c2d3e4f5a6
Create Date: 2026-06-10

Додає FK trainers.photo_media_id -> media_files.id (SET NULL). Legacy-рядок
photo лишається (прибирання -- Фаза 6). Сертифікати/патенти-скани мігрують у
реєстр у межах JSON-полів (media_id) через CLI `flask trainer-media-migrate`.
"""
from alembic import op
import sqlalchemy as sa


revision = 'd7e8f9a0b1c2'
down_revision = 'b1c2d3e4f5a6'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('trainers', schema=None) as batch_op:
        batch_op.add_column(sa.Column('photo_media_id', sa.BigInteger(), nullable=True))
        batch_op.create_foreign_key(
            'fk_trainers_photo_media_id', 'media_files',
            ['photo_media_id'], ['id'], ondelete='SET NULL',
        )


def downgrade():
    with op.batch_alter_table('trainers', schema=None) as batch_op:
        batch_op.drop_constraint('fk_trainers_photo_media_id', type_='foreignkey')
        batch_op.drop_column('photo_media_id')
