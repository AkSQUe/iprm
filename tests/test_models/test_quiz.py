"""Моделі тестування: прив'язка тесту, банк питань, спроби.

Тут перевіряються саме інваріанти схеми й моделі -- те, що мусить триматися
незалежно від сервісу: XOR-прив'язка тесту, один тест на курс/проведення,
поріг у межах кількості питань, нормалізація варіантів відповідей і головне --
що правильність відповіді НЕ витікає у те, що можна віддати в шаблон.
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.course_quiz import (
    ANSWERS_PER_QUESTION, CourseQuiz, QuizQuestion,
)
from app.models.quiz_attempt import QuizAttempt
from app.models.registration import EventRegistration
from app.models.user import User


def _course():
    course = Course(title=f'Курс {uuid4().hex[:4]}', slug=f'q-{uuid4().hex[:6]}',
                    is_active=True, event_type='course')
    db.session.add(course)
    db.session.flush()
    return course


def _instance(course=None):
    course = course or _course()
    inst = CourseInstance(
        course_id=course.id, status='published', event_format='offline',
        start_date=datetime.now(timezone.utc) - timedelta(days=1),
    )
    db.session.add(inst)
    db.session.flush()
    return inst


def _answers(correct=0, count=ANSWERS_PER_QUESTION):
    return [
        {'text': f'Варіант {i + 1}', 'is_correct': i == correct}
        for i in range(count)
    ]


def _question(quiz, correct=0, count=ANSWERS_PER_QUESTION, text='Питання?'):
    q = QuizQuestion(quiz_id=quiz.id, text=text, answers=_answers(correct, count))
    db.session.add(q)
    db.session.flush()
    return q


def _quiz(course=None, instance=None, **kwargs):
    if course is None and instance is None:
        course = _course()
    quiz = CourseQuiz(
        course_id=course.id if course else None,
        instance_id=instance.id if instance else None,
        **kwargs,
    )
    db.session.add(quiz)
    db.session.flush()
    return quiz


# --- прив'язка ---------------------------------------------------------------

def test_quiz_binds_to_course(app):
    quiz = _quiz(course=_course())
    assert quiz.instance_id is None
    assert quiz.owner_label == 'курс'


def test_quiz_binds_to_instance(app):
    quiz = _quiz(instance=_instance())
    assert quiz.course_id is None
    assert quiz.owner_label == 'проведення'


def test_quiz_cannot_bind_to_both(app):
    """XOR: інакше було б неясно, який набір питань чинний."""
    course = _course()
    inst = _instance(course)
    db.session.add(CourseQuiz(course_id=course.id, instance_id=inst.id))
    with pytest.raises(IntegrityError):
        db.session.flush()
    db.session.rollback()


def test_quiz_cannot_bind_to_nothing(app):
    db.session.add(CourseQuiz())
    with pytest.raises(IntegrityError):
        db.session.flush()
    db.session.rollback()


def test_one_quiz_per_course(app):
    course = _course()
    _quiz(course=course)
    db.session.add(CourseQuiz(course_id=course.id))
    with pytest.raises(IntegrityError):
        db.session.flush()
    db.session.rollback()


def test_one_quiz_per_instance(app):
    inst = _instance()
    _quiz(instance=inst)
    db.session.add(CourseQuiz(instance_id=inst.id))
    with pytest.raises(IntegrityError):
        db.session.flush()
    db.session.rollback()


def test_course_and_instance_quizzes_coexist(app):
    """Перевизначення на проведенні мусить жити поруч із тестом курсу."""
    course = _course()
    inst = _instance(course)
    _quiz(course=course)
    _quiz(instance=inst)
    assert CourseQuiz.query.filter(
        (CourseQuiz.course_id == course.id) | (CourseQuiz.instance_id == inst.id)
    ).count() == 2


# --- налаштування -----------------------------------------------------------

def test_defaults(app):
    quiz = _quiz()
    assert quiz.questions_per_attempt == 10
    assert quiz.passing_score == 8
    assert quiz.max_attempts == 3
    assert quiz.shuffle_answers is True
    # Свідомо вимкнений: банку питань ще немає.
    assert quiz.is_active is False


def test_passing_score_cannot_exceed_questions(app):
    db.session.add(CourseQuiz(
        course_id=_course().id, questions_per_attempt=10, passing_score=11))
    with pytest.raises(IntegrityError):
        db.session.flush()
    db.session.rollback()


@pytest.mark.parametrize('field, value', [
    ('questions_per_attempt', 0),
    ('passing_score', 0),
    ('max_attempts', 0),
])
def test_non_positive_settings_rejected(app, field, value):
    db.session.add(CourseQuiz(course_id=_course().id, **{field: value}))
    with pytest.raises(IntegrityError):
        db.session.flush()
    db.session.rollback()


# --- банк питань ------------------------------------------------------------

def test_bank_counts_only_active(app):
    quiz = _quiz()
    _question(quiz)
    inactive = _question(quiz)
    inactive.is_active = False
    db.session.flush()
    assert quiz.bank_size == 1


def test_not_ready_when_bank_too_small(app):
    quiz = _quiz(questions_per_attempt=3, passing_score=2)
    _question(quiz)
    _question(quiz)
    assert quiz.is_ready is False


def test_ready_when_bank_sufficient(app):
    quiz = _quiz(questions_per_attempt=2, passing_score=2)
    _question(quiz)
    _question(quiz)
    assert quiz.is_ready is True


def test_not_ready_when_a_question_is_broken(app):
    """Адмін міг увімкнути тест, а потім зіпсувати питання."""
    quiz = _quiz(questions_per_attempt=2, passing_score=2)
    _question(quiz)
    broken = _question(quiz)
    broken.answers = _answers(count=3)          # три варіанти замість чотирьох
    db.session.flush()
    assert broken.is_valid is False
    assert quiz.is_ready is False


# --- варіанти відповідей ----------------------------------------------------

def test_answers_are_normalized(app):
    """Пишуться і з адмінки, і зі скриптів -- форма ключів мусить бути одна."""
    quiz = _quiz()
    q = QuizQuestion(quiz_id=quiz.id, text='П?', answers=[
        {'text': '  З пробілами  ', 'is_correct': 'yes'},
        {'text': 'Друга'},
        'сміття',
        {'text': ''},
        {'text': 'Третя', 'is_correct': 0},
    ])
    db.session.add(q)
    db.session.flush()

    assert q.answers == [
        {'text': 'З пробілами', 'is_correct': True},
        {'text': 'Друга', 'is_correct': False},
        {'text': 'Третя', 'is_correct': False},
    ]


def test_exactly_one_correct_required(app):
    quiz = _quiz()
    q = _question(quiz)
    assert q.correct_index == 0

    q.answers = [dict(a, is_correct=True) for a in _answers()]
    db.session.flush()
    assert q.correct_index is None
    assert q.is_valid is False


def test_no_correct_answer_is_invalid(app):
    quiz = _quiz()
    q = _question(quiz)
    q.answers = _answers(correct=-1)     # жоден не позначений
    db.session.flush()
    assert q.correct_index is None
    assert q.is_valid is False


def test_answer_texts_never_leak_correctness(app):
    """Найважливіше: у шаблон іде лише текст, інакше відповідь видно у HTML."""
    quiz = _quiz()
    q = _question(quiz, correct=2)
    texts = q.answer_texts()
    assert texts == ['Варіант 1', 'Варіант 2', 'Варіант 3', 'Варіант 4']
    assert all(isinstance(t, str) for t in texts)


def test_question_is_translatable(app):
    quiz = _quiz()
    q = _question(quiz)
    q.set_translation('en', 'text', 'Question?')
    db.session.flush()
    assert q.t('text', lang='en') == 'Question?'
    assert q.t('text', lang='uk') == 'Питання?'


def test_answers_translate_leaf_by_leaf_ignoring_flags(app):
    """`is_correct` -- bool, тож walk_leaves його не чіпає."""
    quiz = _quiz()
    q = _question(quiz, correct=1)
    q.set_translation('en', 'answers', {'0.text': 'Option 1'})
    db.session.flush()

    translated = q.t('answers', lang='en')
    assert translated[0]['text'] == 'Option 1'
    assert translated[0]['is_correct'] is False
    # Неперекладений варіант лишається українським, а прапорець -- на місці.
    assert translated[1]['text'] == 'Варіант 2'
    assert translated[1]['is_correct'] is True


def test_deleting_quiz_removes_questions(app):
    quiz = _quiz()
    _question(quiz)
    db.session.delete(quiz)
    db.session.flush()
    assert QuizQuestion.query.filter_by(quiz_id=quiz.id).count() == 0


# --- спроби -----------------------------------------------------------------

def _registration():
    inst = _instance()
    user = User.create_with_password(
        f'qa-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='Т', last_name='Т', email_confirmed=True)
    db.session.flush()
    reg = EventRegistration(
        user_id=user.id, instance_id=inst.id, phone='+380501234567',
        specialty='Терапія', workplace='Клініка', payment_status='paid')
    db.session.add(reg)
    db.session.flush()
    return reg


def _attempt(reg, quiz, number=1, **kwargs):
    kwargs.setdefault('question_ids', [])
    kwargs.setdefault('answer_order', {})
    kwargs.setdefault('submitted_answers', {})
    kwargs.setdefault('total', 10)
    kwargs.setdefault('passing_score', 8)
    attempt = QuizAttempt(
        registration_id=reg.id, user_id=reg.user_id, quiz_id=quiz.id,
        attempt_number=number, **kwargs,
    )
    db.session.add(attempt)
    db.session.flush()
    return attempt


def test_attempt_number_unique_per_registration(app):
    reg, quiz = _registration(), _quiz()
    _attempt(reg, quiz, number=1)
    db.session.add(QuizAttempt(
        registration_id=reg.id, user_id=reg.user_id, quiz_id=quiz.id,
        attempt_number=1, question_ids=[], answer_order={},
        submitted_answers={}, total=10, passing_score=8))
    with pytest.raises(IntegrityError):
        db.session.flush()
    db.session.rollback()


def test_attempt_numbers_are_independent_across_registrations(app):
    quiz = _quiz()
    first, second = _registration(), _registration()
    _attempt(first, quiz, number=1)
    _attempt(second, quiz, number=1)
    assert QuizAttempt.query.filter_by(attempt_number=1).count() >= 2


def test_unfinished_attempt_is_detectable(app):
    """submitted_at IS NULL -- ознака спроби, яку треба продовжити."""
    attempt = _attempt(_registration(), _quiz())
    assert attempt.is_finished is False
    attempt.submitted_at = datetime.now(timezone.utc)
    db.session.flush()
    assert attempt.is_finished is True


def test_attempt_keeps_fixed_order(app):
    """Порядок фіксується на старті -- перезавантаження не перемішує тест."""
    attempt = _attempt(
        _registration(), _quiz(),
        question_ids=[7, 3, 9], answer_order={'7': [2, 0, 3, 1]},
    )
    assert attempt.question_ids == [7, 3, 9]
    assert attempt.ordered_answer_indexes(7) == [2, 0, 3, 1]
    assert attempt.ordered_answer_indexes(3) == []


def test_chosen_position_and_count(app):
    attempt = _attempt(
        _registration(), _quiz(), submitted_answers={'7': 2, '3': 0})
    assert attempt.chosen_position(7) == 2
    assert attempt.chosen_position(9) is None
    assert attempt.answered_count == 2


def test_deleted_quiz_keeps_attempt_history(app):
    """SET NULL: історія складань не мусить зникати разом із тестом.

    CASCADE тут знищив би результати учасників мовчки -- при спробі адміна
    перестворити тест курсу.
    """
    reg, quiz = _registration(), _quiz()
    attempt = _attempt(reg, quiz)
    attempt_id = attempt.id

    db.session.delete(quiz)
    db.session.flush()
    db.session.expire_all()

    survivor = db.session.get(QuizAttempt, attempt_id)
    assert survivor is not None, 'спробу знищило разом із тестом'
    assert survivor.quiz_id is None


def test_attempt_fk_declares_set_null(app):
    """Структурна перевірка на додачу до поведінкової.

    Вище від'єднання робить ORM (зв'язок без delete-orphan). На проді працює ще
    й СУБД -- а `PRAGMA foreign_keys` у SQLite є no-op усередині транзакції, тож
    поведінково рівень БД у тестах не перевірити. Тому declared-значення
    перевіряємо окремо: якщо хтось поставить тут CASCADE, результати учасників
    почнуть зникати разом із тестом.
    """
    fk = next(
        fk for fk in QuizAttempt.__table__.foreign_keys
        if fk.column.table.name == 'course_quizzes'
    )
    assert fk.ondelete == 'SET NULL'


def test_deleting_registration_removes_attempts(app):
    reg, quiz = _registration(), _quiz()
    _attempt(reg, quiz)
    db.session.delete(reg)
    db.session.flush()
    assert QuizAttempt.query.filter_by(registration_id=reg.id).count() == 0


def test_registration_quiz_defaults(app):
    reg = _registration()
    assert reg.quiz_passed_at is None
    assert reg.quiz_extra_attempts == 0
