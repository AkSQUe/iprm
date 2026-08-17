"""Тестування учасників: налаштування тесту, банк питань, спроби

Revision ID: quiz_20260817
Revises: bpr_counter_20260817
Create Date: 2026-08-17

Why
---
Сертифікат з балами БПР має видаватися лише тому, хто засвоїв матеріал. Досі
жодного механізму перевірки не існувало: публічний блок «Умови отримання
сертифікату» обіцяв тестування, а видача була ручною дією адміна без будь-яких
умов.

Три таблиці, а не одна:

* ``course_quizzes`` -- налаштування (скільки питань на спробу, поріг, ліміт
  спроб). Прив'язка XOR: або курс, або проведення. Курс проводиться багато разів
  (у «Базового курсу з плазмотерапії» вже 12 проведень), тож тримати питання на
  проведенні означало б копіювати їх щоразу; перевизначення на проведенні
  лишається для випадків іншої програми.
* ``quiz_questions`` -- банк. Варіанти відповідей -- JSON-колонка, а не окрема
  таблиця: прецедент ``program_blocks.items``/``courses.faq``, і механізм
  перекладів це вже вміє (``walk_leaves`` обходить лише str-листя, тож булеве
  ``is_correct`` ігнорується сам собою). За варіантами ніколи не фільтруємо.
* ``quiz_attempts`` -- спроби з ЗАФІКСОВАНИМ набором питань і порядком
  варіантів. Без фіксації кожне перезавантаження сторінки перемішувало б тест, а
  спроб лише три.

``quiz_attempts.quiz_id`` -- SET NULL, а не CASCADE: видалений тест не має
стирати історію складань. ``passing_score`` і ``total`` -- знімки на момент
спроби, щоб зміна налаштувань не переоцінювала вже зігране.

Поля в ``event_registrations``: ``quiz_passed_at`` -- денормалізація заради
лістингів і гейта (джерело правди лишається у ``quiz_attempts``);
``quiz_extra_attempts`` -- додаткові спроби від адміна числом, а не прапорцем,
щоб можна було видати рівно одну.

Partial-unique індекси (``uq_course_quizzes_course``/``_instance``) замість
звичайних unique: друга колонка у своєму рядку завжди NULL, і звичайний unique
на NULL-ах поводився б по-різному в різних СУБД. Той самий підхід уже
застосований у ``uq_registrations_instance_place`` і
``uq_promo_redemptions_active_reg``.

Даних міграція не чіпає: тести створюються з нуля в адмінці.
"""
from alembic import op
import sqlalchemy as sa


revision = 'quiz_20260817'
down_revision = 'bpr_counter_20260817'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'course_quizzes',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('course_id', sa.BigInteger(), nullable=True),
        sa.Column('instance_id', sa.BigInteger(), nullable=True),
        sa.Column('questions_per_attempt', sa.Integer(), nullable=False,
                  server_default='10'),
        sa.Column('passing_score', sa.Integer(), nullable=False, server_default='8'),
        sa.Column('max_attempts', sa.Integer(), nullable=False, server_default='3'),
        sa.Column('shuffle_answers', sa.Boolean(), nullable=False,
                  server_default=sa.true()),
        sa.Column('is_active', sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['course_id'], ['courses.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['instance_id'], ['course_instances.id'],
                                ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint(
            '(course_id IS NOT NULL AND instance_id IS NULL) OR '
            '(course_id IS NULL AND instance_id IS NOT NULL)',
            name='ck_course_quizzes_owner',
        ),
        sa.CheckConstraint('questions_per_attempt >= 1',
                           name='ck_course_quizzes_per_attempt'),
        sa.CheckConstraint('passing_score >= 1',
                           name='ck_course_quizzes_passing_positive'),
        sa.CheckConstraint('passing_score <= questions_per_attempt',
                           name='ck_course_quizzes_passing_within'),
        sa.CheckConstraint('max_attempts >= 1',
                           name='ck_course_quizzes_max_attempts'),
    )
    op.create_index('ix_course_quizzes_course_id', 'course_quizzes', ['course_id'])
    op.create_index('ix_course_quizzes_instance_id', 'course_quizzes',
                    ['instance_id'])
    op.create_index('uq_course_quizzes_course', 'course_quizzes', ['course_id'],
                    unique=True, postgresql_where=sa.text('course_id IS NOT NULL'),
                    sqlite_where=sa.text('course_id IS NOT NULL'))
    op.create_index('uq_course_quizzes_instance', 'course_quizzes', ['instance_id'],
                    unique=True,
                    postgresql_where=sa.text('instance_id IS NOT NULL'),
                    sqlite_where=sa.text('instance_id IS NOT NULL'))

    op.create_table(
        'quiz_questions',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('quiz_id', sa.BigInteger(), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('answers', sa.JSON(), nullable=False),
        sa.Column('sort_order', sa.Integer(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False,
                  server_default=sa.true()),
        sa.Column('translations', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['quiz_id'], ['course_quizzes.id'],
                                ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_quiz_questions_quiz_id', 'quiz_questions', ['quiz_id'])

    op.create_table(
        'quiz_attempts',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('registration_id', sa.BigInteger(), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('quiz_id', sa.BigInteger(), nullable=True),
        sa.Column('attempt_number', sa.Integer(), nullable=False),
        sa.Column('question_ids', sa.JSON(), nullable=False),
        sa.Column('answer_order', sa.JSON(), nullable=False),
        sa.Column('submitted_answers', sa.JSON(), nullable=False),
        sa.Column('score', sa.Integer(), nullable=True),
        sa.Column('total', sa.Integer(), nullable=False),
        sa.Column('passing_score', sa.Integer(), nullable=False),
        sa.Column('passed', sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['registration_id'], ['event_registrations.id'],
                                ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['quiz_id'], ['course_quizzes.id'],
                                ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('registration_id', 'attempt_number',
                            name='uq_quiz_attempts_registration_number'),
        sa.CheckConstraint('attempt_number >= 1', name='ck_quiz_attempts_number'),
        sa.CheckConstraint('score IS NULL OR score >= 0',
                           name='ck_quiz_attempts_score'),
        sa.CheckConstraint('total >= 1', name='ck_quiz_attempts_total'),
    )
    op.create_index('ix_quiz_attempts_registration_id', 'quiz_attempts',
                    ['registration_id'])
    op.create_index('ix_quiz_attempts_user_id', 'quiz_attempts', ['user_id'])
    op.create_index('ix_quiz_attempts_quiz_id', 'quiz_attempts', ['quiz_id'])

    op.add_column('event_registrations',
                  sa.Column('quiz_passed_at', sa.DateTime(timezone=True),
                            nullable=True))
    op.add_column('event_registrations',
                  sa.Column('quiz_extra_attempts', sa.Integer(), nullable=False,
                            server_default='0'))


def downgrade():
    op.drop_column('event_registrations', 'quiz_extra_attempts')
    op.drop_column('event_registrations', 'quiz_passed_at')

    op.drop_index('ix_quiz_attempts_quiz_id', table_name='quiz_attempts')
    op.drop_index('ix_quiz_attempts_user_id', table_name='quiz_attempts')
    op.drop_index('ix_quiz_attempts_registration_id', table_name='quiz_attempts')
    op.drop_table('quiz_attempts')

    op.drop_index('ix_quiz_questions_quiz_id', table_name='quiz_questions')
    op.drop_table('quiz_questions')

    op.drop_index('uq_course_quizzes_instance', table_name='course_quizzes')
    op.drop_index('uq_course_quizzes_course', table_name='course_quizzes')
    op.drop_index('ix_course_quizzes_instance_id', table_name='course_quizzes')
    op.drop_index('ix_course_quizzes_course_id', table_name='course_quizzes')
    op.drop_table('course_quizzes')
