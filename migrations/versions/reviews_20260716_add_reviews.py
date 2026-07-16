"""Add reviews table (testimonials)

Revision ID: reviews_20260716
Revises: home_founding_year_20260716
Create Date: 2026-07-16 01:00:00.000000

Відгуки випускників для блоку "Після навчання" на Головній (адмін-CRUD).
"""
from alembic import op
import sqlalchemy as sa


revision = 'reviews_20260716'
down_revision = 'home_founding_year_20260716'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'reviews',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('author_name', sa.String(length=120), nullable=False),
        sa.Column('author_role', sa.String(length=160), nullable=True),
        sa.Column('city', sa.String(length=120), nullable=True),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('rating', sa.Integer(), nullable=False, server_default='5'),
        sa.Column('is_published', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('course_id', sa.BigInteger(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['course_id'], ['courses.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint('rating >= 1 AND rating <= 5', name='ck_reviews_rating'),
    )
    op.create_index('ix_reviews_is_published', 'reviews', ['is_published'])
    op.create_index('ix_reviews_published_sort', 'reviews', ['is_published', 'sort_order'])


def downgrade():
    op.drop_index('ix_reviews_published_sort', table_name='reviews')
    op.drop_index('ix_reviews_is_published', table_name='reviews')
    op.drop_table('reviews')
