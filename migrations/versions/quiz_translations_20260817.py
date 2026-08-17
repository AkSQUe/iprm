"""Тест: JSON-колонка translations на course_quizzes

Revision ID: quiz_trans_20260817
Revises: quiz_intro_20260817
Create Date: 2026-08-17

Why
---
``CourseQuiz`` успадковує ``TranslatableMixin`` (заради перекладного
``intro``), а мікcин оголошує колонку ``translations``. У базі її не було:
``quiz_20260817`` створював таблицю ще до перекладів і додав ``translations``
лише в ``quiz_questions``, а ``quiz_intro_20260817`` додав сам ``intro``, але
про колонку перекладів забув.

Розбіжність не видно доти, доки хтось не прочитає CourseQuiz із бази: SELECT
тягне всі колонки моделі, і Postgres відповідає 42703. Саме так лягла
/admin/registrations -- ``quiz_service.build_batch_context()`` вантажить тести
пачкою для колонки «тест» у списку реєстрацій.

Колонка nullable і без ``server_default`` -- як в ``i18n_translations_20260724``
для решти контентних таблиць: відсутність перекладів означає українську.
"""
import sqlalchemy as sa
from alembic import op

revision = 'quiz_trans_20260817'
down_revision = 'quiz_intro_20260817'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('course_quizzes',
                  sa.Column('translations', sa.JSON(), nullable=True))


def downgrade():
    op.drop_column('course_quizzes', 'translations')
