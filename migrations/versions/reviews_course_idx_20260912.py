"""Індекси відгуків: (course_id, is_published) і (online_course_id, is_published)

Revision ID: reviews_course_idx_20260912
Revises: instance_bpr_number_20260912
Create Date: 2026-09-12 00:00:00.000000

Сторінка курсу й сторінка онлайн-курсу роблять по ДВА запити з рівно цією
парою колонок: список відгуків і окремий COUNT/AVG для AggregateRating. До
цього жодна з двох не мала індексу взагалі -- обидва FK лишались голими, і
кожна віддача публічної сторінки курсу сканувала таблицю відгуків цілком.

Пара, а не голий FK: відбір за самим course_id повернув би й неопубліковані,
тобто на курсі з чернетками більшу частину рядків. Провідна колонка пари
водночас покриває сам FK -- це той індекс, якого ON DELETE SET NULL шукає
при видаленні курсу.

Автогенерацію тут вжито лише як чернетку: у dev-базі лежать таблиці
course_trainers і course_instance_trainers із ще не злитої гілки, і
`flask db migrate` запропонував їх видалити. Міграція свідомо їх не чіпає --
їх створює й прибирає та гілка.
"""
from alembic import op


revision = 'reviews_course_idx_20260912'
down_revision = 'instance_bpr_number_20260912'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('reviews', schema=None) as batch_op:
        batch_op.create_index(
            'ix_reviews_course_published', ['course_id', 'is_published'],
            unique=False)
        batch_op.create_index(
            'ix_reviews_online_course_published',
            ['online_course_id', 'is_published'], unique=False)


def downgrade():
    with op.batch_alter_table('reviews', schema=None) as batch_op:
        batch_op.drop_index('ix_reviews_online_course_published')
        batch_op.drop_index('ix_reviews_course_published')
