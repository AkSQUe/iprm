"""М'яке видалення для undo: deleted_at у reviews, blog_comments, media_files

Revision ID: soft_delete_undo_20260725
Revises: perf_drop_page_idx_20260725
Create Date: 2026-07-25 00:00:00.000000

Видалення відгуку, коментаря і медіафайлу більше не питає підтвердження --
натомість дія виконується одразу, а адмін дістає тост із кнопкою "Повернути".
Щоб відкат був можливим, рядок не зникає, а отримує позначку deleted_at;
остаточно чистить фонова задача purge_soft_deleted.

Колонка nullable без дефолту: наявні рядки лишаються живими (NULL).
Індекс потрібен, бо deleted_at IS NULL стоїть у кожному списковому запиті.
"""
from alembic import op
import sqlalchemy as sa


revision = 'soft_delete_undo_20260725'
down_revision = 'perf_drop_page_idx_20260725'
branch_labels = None
depends_on = None

_TABLES = ('reviews', 'blog_comments', 'media_files')


def upgrade():
    for table in _TABLES:
        op.add_column(
            table, sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index(f'ix_{table}_deleted_at', table, ['deleted_at'])


def downgrade():
    for table in _TABLES:
        op.drop_index(f'ix_{table}_deleted_at', table_name=table)
        op.drop_column(table, 'deleted_at')
