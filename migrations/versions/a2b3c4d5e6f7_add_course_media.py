"""add hero_media_id/card_media_id to courses (media registry -- phase 5)

Revision ID: a2b3c4d5e6f7
Revises: d7e8f9a0b1c2
Create Date: 2026-06-10

Додає FK courses.hero_media_id / card_media_id -> media_files.id (SET NULL).
Legacy-рядки hero_image/card_image лишаються (прибирання -- Фаза 6). Міграцію
наявних зображень виконує CLI `flask course-media-migrate`.
"""
from alembic import op
import sqlalchemy as sa


revision = 'a2b3c4d5e6f7'
down_revision = 'd7e8f9a0b1c2'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('courses', schema=None) as batch_op:
        batch_op.add_column(sa.Column('hero_media_id', sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column('card_media_id', sa.BigInteger(), nullable=True))
        batch_op.create_foreign_key(
            'fk_courses_hero_media_id', 'media_files', ['hero_media_id'], ['id'], ondelete='SET NULL',
        )
        batch_op.create_foreign_key(
            'fk_courses_card_media_id', 'media_files', ['card_media_id'], ['id'], ondelete='SET NULL',
        )


def downgrade():
    with op.batch_alter_table('courses', schema=None) as batch_op:
        batch_op.drop_constraint('fk_courses_card_media_id', type_='foreignkey')
        batch_op.drop_constraint('fk_courses_hero_media_id', type_='foreignkey')
        batch_op.drop_column('card_media_id')
        batch_op.drop_column('hero_media_id')
