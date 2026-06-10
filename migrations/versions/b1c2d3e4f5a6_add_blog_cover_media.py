"""add cover_media_id to blog_posts (media registry integration -- phase 3)

Revision ID: b1c2d3e4f5a6
Revises: b8c9d0e1f2a3
Create Date: 2026-06-10

Додає FK blog_posts.cover_media_id -> media_files.id (SET NULL). Legacy-рядок
cover_image лишається (прибирання -- у Фазі 6). Жодних даних не переноситься
тут: міграцію наявних зображень виконує CLI `flask blog-media-migrate`.
"""
from alembic import op
import sqlalchemy as sa


revision = 'b1c2d3e4f5a6'
down_revision = 'b8c9d0e1f2a3'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('blog_posts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('cover_media_id', sa.BigInteger(), nullable=True))
        batch_op.create_foreign_key(
            'fk_blog_posts_cover_media_id', 'media_files',
            ['cover_media_id'], ['id'], ondelete='SET NULL',
        )


def downgrade():
    with op.batch_alter_table('blog_posts', schema=None) as batch_op:
        batch_op.drop_constraint('fk_blog_posts_cover_media_id', type_='foreignkey')
        batch_op.drop_column('cover_media_id')
