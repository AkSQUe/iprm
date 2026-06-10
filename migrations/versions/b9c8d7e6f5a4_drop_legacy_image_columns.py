"""drop legacy image string columns (media registry -- phase 6)

Revision ID: b9c8d7e6f5a4
Revises: a2b3c4d5e6f7
Create Date: 2026-06-10

Прибирає legacy-рядкові колонки зображень після повного переходу на медіа-реєстр
(Фази 3-5 + data-міграції на prod):
  blog_posts.cover_image, trainers.photo, courses.hero_image, courses.card_image.

trainers.signature НЕ чіпаємо -- це окремий друкований ассет сертифікатів, не
частина публічного медіа-реєстру.

ЗАХИСТ ВІД ВТРАТИ ДАНИХ: перед drop рахуємо рядки, де legacy-колонка заповнена,
але відповідний *_media_id NULL (тобто зображення ще не мігроване). Якщо такі є
-- міграція аварійно зупиняється (транзакція відкочується), щоб адмін спершу
запустив *-media-migrate або вручну вирішив долю цих посилань.
"""
from alembic import op
import sqlalchemy as sa


revision = 'b9c8d7e6f5a4'
down_revision = 'a2b3c4d5e6f7'
branch_labels = None
depends_on = None


# (таблиця, legacy-колонка, media-FK-колонка)
_CHECKS = [
    ('blog_posts', 'cover_image', 'cover_media_id'),
    ('trainers', 'photo', 'photo_media_id'),
    ('courses', 'hero_image', 'hero_media_id'),
    ('courses', 'card_image', 'card_media_id'),
]


def _guard_no_unmigrated(bind):
    problems = []
    for table, legacy, fk in _CHECKS:
        count = bind.execute(sa.text(
            f"SELECT COUNT(*) FROM {table} "
            f"WHERE {legacy} IS NOT NULL AND {legacy} <> '' AND {fk} IS NULL"
        )).scalar()
        if count:
            problems.append(f'{table}.{legacy}: {count}')
    if problems:
        raise RuntimeError(
            'Phase 6 aborted -- є немігровані зображення (legacy заповнено, '
            'media_id порожній): ' + '; '.join(problems) + '. Спершу запустіть '
            'відповідний *-media-migrate (з попереднього релізу) або очистіть '
            'ці посилання, потім повторіть upgrade.'
        )


def upgrade():
    bind = op.get_bind()
    _guard_no_unmigrated(bind)

    with op.batch_alter_table('blog_posts', schema=None) as batch_op:
        batch_op.drop_column('cover_image')
    with op.batch_alter_table('trainers', schema=None) as batch_op:
        batch_op.drop_column('photo')
    with op.batch_alter_table('courses', schema=None) as batch_op:
        batch_op.drop_column('hero_image')
        batch_op.drop_column('card_image')


def downgrade():
    # Відновлюємо колонки (порожні -- дані не повертаються; це безпечний best-effort).
    with op.batch_alter_table('courses', schema=None) as batch_op:
        batch_op.add_column(sa.Column('card_image', sa.String(length=500), nullable=True))
        batch_op.add_column(sa.Column('hero_image', sa.String(length=500), nullable=True))
    with op.batch_alter_table('trainers', schema=None) as batch_op:
        batch_op.add_column(sa.Column('photo', sa.String(length=500), nullable=True))
    with op.batch_alter_table('blog_posts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('cover_image', sa.String(length=500), nullable=True))
