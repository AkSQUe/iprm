"""Злиття ліній: кілька тренерів на заході + робота main.

Порожня ревізія-злиток. Гілка тренерів відгалузилась від
`merge_bpr_heads_20260910` і встигла додати власні колонки, а main за цей
час пішов своєю лінією аж до `reviews_course_idx_20260912`. Обидві лінії
самодостатні й нічого спільного не міняють, тож зводити їх нема чим -- цей
файл лише повертає єдину голову, без якої `flask db upgrade` відмовляється
працювати.

Revision ID: merge_trainers_main_20260912
Revises: instance_lect_points_20260910, reviews_course_idx_20260912
Create Date: 2026-09-12

"""

revision = 'merge_trainers_main_20260912'
down_revision = ('instance_lect_points_20260910', 'reviews_course_idx_20260912')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
