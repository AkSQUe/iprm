"""Тест: вступний текст і дедлайн складання

Revision ID: quiz_intro_20260817
Revises: thankyou_online_20260817
Create Date: 2026-08-17

Why
---
Роздатка учасникам обіцяла дві речі, яких у системі не існувало.

1. **Вступний текст.** Умови заходу, на що звернути увагу, посилання на
   матеріали -- усе це не мало де жити. Сторінка старту показувала лише
   згенеровані числа («10 питань, потрібно 8»), тож правила доводилось
   переказувати людям поза сайтом. ``course_quizzes.intro`` -- перекладна
   колонка (``CourseQuiz.__translatable__``), бо сторінку тесту читають
   українською, російською й англійською.

2. **Дедлайн.** Роздатка казала «до 23:59 у день завершення заходу», а тест
   відкривався з початком заходу і не закривався ніколи.
   ``deadline_days_after_end`` -- скільки днів після ЗАВЕРШЕННЯ захід лишається
   відкритим; NULL зберігає попередню поведінку (без обмеження), 0 означає
   рівно те, що в роздатці.

Чому днями від дати заходу, а не абсолютною міткою: тест може належати КУРСУ,
спільному для десятка проведень (у «Базового курсу з плазмотерапії» їх 12), і
одна дата на всіх там безглузда.

Чому від ``end_date``, а не від ``start_date``: на одноденному заході це те
саме, а на триденному відлік від початку закрив би тест посеред заходу. Якщо
``end_date`` не заповнене, сервіс падає назад на ``start_date`` -- інакше
багатоденні чернетки лишались би без дедлайну зовсім.

Обидві колонки nullable і без ``server_default``: наявні тести (у проді їх два)
мусять поводитись точно як досі, доки адмін не заповнить поля сам. CHECK на
невід'ємність -- щоб «-1 день» не закрив тест до початку заходу.
"""
import sqlalchemy as sa
from alembic import op

revision = 'quiz_intro_20260817'
down_revision = 'thankyou_online_20260817'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('course_quizzes') as batch:
        batch.add_column(sa.Column('intro', sa.Text(), nullable=True))
        batch.add_column(sa.Column('deadline_days_after_end',
                                   sa.Integer(), nullable=True))
        batch.create_check_constraint(
            'ck_course_quizzes_deadline_non_negative',
            'deadline_days_after_end IS NULL OR deadline_days_after_end >= 0',
        )


def downgrade():
    with op.batch_alter_table('course_quizzes') as batch:
        batch.drop_constraint('ck_course_quizzes_deadline_non_negative',
                              type_='check')
        batch.drop_column('deadline_days_after_end')
        batch.drop_column('intro')
