"""Блок «Умови отримання сертифікату» на публічній сторінці курсу.

Партіал `_event_certificate.html` довго лежав непідключеним і обіцяв
«тестування з результатом не менше 70%», хоч тестування в проєкті не існувало
взагалі. Тепер він показується ЛИШЕ коли тест реально можна скласти й за нього
реально видадуть сертифікат, а числа беруться з налаштувань, а не зашиті.

Ці тести стежать саме за цим: блок не має з'являтися, поки обіцянка не
виконується.
"""
from itertools import count
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_quiz import CourseQuiz, QuizQuestion
from app.models.site_settings import SiteSettings

_event_numbers = count(6000000)

MARKER = 'Умови отримання'


@pytest.fixture(autouse=True)
def provider_number(app):
    settings = SiteSettings.get()
    settings.bpr_provider_number = '2738'
    db.session.flush()
    return settings


def _course(event_num=None, cpd_points=12):
    course = Course(
        title=f'Курс {uuid4().hex[:4]}', slug=f'cb-{uuid4().hex[:6]}',
        is_active=True, event_type='course', cpd_points=cpd_points,
        bpr_event_number=(event_num if event_num is not None
                          else str(next(_event_numbers))),
    )
    db.session.add(course)
    db.session.flush()
    return course


def _quiz(course, bank=10, per_attempt=10, passing=8, active=True):
    quiz = CourseQuiz(
        course_id=course.id, questions_per_attempt=per_attempt,
        passing_score=passing, is_active=active,
    )
    db.session.add(quiz)
    db.session.flush()
    for i in range(bank):
        db.session.add(QuizQuestion(
            quiz_id=quiz.id, text=f'Питання {i + 1}?', sort_order=i,
            answers=[{'text': f'Варіант {j + 1}', 'is_correct': j == 0}
                     for j in range(4)]))
    db.session.flush()
    return quiz


def _html(client, course):
    resp = client.get(f'/courses/{course.slug}')
    assert resp.status_code == 200
    return resp.get_data(as_text=True)


def test_block_hidden_without_quiz(client, app):
    """Без тесту блок не показуємо -- саме через це партіал і був осиротілий."""
    assert MARKER not in _html(client, _course())


def test_block_hidden_for_inactive_quiz(client, app):
    course = _course()
    _quiz(course, active=False)
    assert MARKER not in _html(client, course)


def test_block_hidden_when_bank_too_small(client, app):
    """Увімкнений, але недостатній банк -- тест не відкриється, обіцянки не даємо."""
    course = _course()
    _quiz(course, bank=3, per_attempt=10, passing=8)
    assert MARKER not in _html(client, course)


def test_block_hidden_without_bpr_event_number(client, app):
    course = _course(event_num='')
    _quiz(course)
    assert MARKER not in _html(client, course)


def test_block_hidden_without_cpd_points(client, app):
    course = _course(cpd_points=None)
    _quiz(course)
    assert MARKER not in _html(client, course)


def test_block_hidden_without_provider_number(client, app, provider_number):
    provider_number.bpr_provider_number = ''
    db.session.flush()
    course = _course()
    _quiz(course)
    assert MARKER not in _html(client, course)


def test_block_shown_when_quiz_is_ready(client, app):
    course = _course()
    _quiz(course)
    html = _html(client, course)
    assert MARKER in html
    assert 'Анкета та тестування' in html


def test_block_uses_real_threshold_not_hardcoded_percent(client, app):
    """Числа беруться з налаштувань. Раніше тут було зашите «не менше 70%»."""
    course = _course()
    _quiz(course, bank=30, per_attempt=20, passing=15)
    html = _html(client, course)
    assert 'щонайменше 15 правильних' in html
    assert 'з 20' in html
    assert '70%' not in html


def test_block_reflects_changed_settings(client, app):
    course = _course()
    quiz = _quiz(course, bank=12, per_attempt=10, passing=8)
    assert 'щонайменше 8 правильних' in _html(client, course)

    quiz.passing_score = 9
    db.session.flush()
    assert 'щонайменше 9 правильних' in _html(client, course)


def test_instance_override_alone_does_not_show_block(client, app):
    """Сторінка курсу описує курс загалом; різні набори на датах на ній не
    описати, тож перевизначення проведення блок не піднімає."""
    from datetime import datetime, timedelta, timezone

    from app.models.course_instance import CourseInstance

    course = _course()
    inst = CourseInstance(
        course_id=course.id, status='published', event_format='offline',
        start_date=datetime.now(timezone.utc) + timedelta(days=10))
    db.session.add(inst)
    db.session.flush()
    override = CourseQuiz(instance_id=inst.id, is_active=True)
    db.session.add(override)
    db.session.flush()

    assert MARKER not in _html(client, course)
