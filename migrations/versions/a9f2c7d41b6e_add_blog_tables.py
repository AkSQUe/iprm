"""add blog_posts and blog_comments tables

Revision ID: a9f2c7d41b6e
Revises: b8d9f0a16c73
Create Date: 2026-06-09 09:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a9f2c7d41b6e'
down_revision = 'b8d9f0a16c73'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'blog_posts',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('slug', sa.String(length=200), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('excerpt', sa.String(length=500), nullable=True),
        sa.Column('cover_image', sa.String(length=500), nullable=True),
        sa.Column('content', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='draft'),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('author_id', sa.BigInteger(), nullable=True),
        sa.Column('meta_title', sa.String(length=200), nullable=True),
        sa.Column('meta_description', sa.String(length=500), nullable=True),
        sa.Column('views', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['author_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint("status IN ('draft', 'published')", name='ck_blog_posts_status'),
    )
    with op.batch_alter_table('blog_posts', schema=None) as batch_op:
        batch_op.create_index('ix_blog_posts_slug', ['slug'], unique=True)
        batch_op.create_index('ix_blog_posts_status', ['status'], unique=False)
        batch_op.create_index('ix_blog_posts_published_at', ['published_at'], unique=False)
        batch_op.create_index('ix_blog_posts_author_id', ['author_id'], unique=False)
        batch_op.create_index('ix_blog_posts_status_published', ['status', 'published_at'], unique=False)

    op.create_table(
        'blog_comments',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('post_id', sa.BigInteger(), nullable=False),
        sa.Column('parent_id', sa.BigInteger(), nullable=True),
        sa.Column('author_name', sa.String(length=120), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=True),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
        sa.Column('ip', sa.String(length=45), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['post_id'], ['blog_posts.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['parent_id'], ['blog_comments.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint("status IN ('pending', 'approved', 'spam')", name='ck_blog_comments_status'),
    )
    with op.batch_alter_table('blog_comments', schema=None) as batch_op:
        batch_op.create_index('ix_blog_comments_post_id', ['post_id'], unique=False)
        batch_op.create_index('ix_blog_comments_parent_id', ['parent_id'], unique=False)
        batch_op.create_index('ix_blog_comments_status', ['status'], unique=False)
        batch_op.create_index('ix_blog_comments_post_status', ['post_id', 'status'], unique=False)


def downgrade():
    with op.batch_alter_table('blog_comments', schema=None) as batch_op:
        batch_op.drop_index('ix_blog_comments_post_status')
        batch_op.drop_index('ix_blog_comments_status')
        batch_op.drop_index('ix_blog_comments_parent_id')
        batch_op.drop_index('ix_blog_comments_post_id')
    op.drop_table('blog_comments')

    with op.batch_alter_table('blog_posts', schema=None) as batch_op:
        batch_op.drop_index('ix_blog_posts_status_published')
        batch_op.drop_index('ix_blog_posts_author_id')
        batch_op.drop_index('ix_blog_posts_published_at')
        batch_op.drop_index('ix_blog_posts_status')
        batch_op.drop_index('ix_blog_posts_slug')
    op.drop_table('blog_posts')
