"""Результати тестування проведення: ПІБ і бал ведуть у деталі учасника.

ПІБ -- у картку користувача (`user_detail`). Бал -- у розбір відповідей
(`registration_quiz_detail`): саме звідти цей бал і взявся. Гілка «немає
результату» лишається текстом -- розбирати нічого.
"""
import re
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.course_quiz import CourseQuiz, QuizQuestion
from app.models.registration import EventRegistration
from app.models.site_settings import SiteSettings
from app.models.user import User
from app.services import certificate_service, quiz_service

FULL_PROFILE = {
    'participant_type': 'doctor', 'middle_name': 'Іванович',
    'birth_date': datetime(1985, 3, 12).date(), 'education': '2010, НМУ',
    'workplace': 'Клініка', 'position': 'лікар', 'specializations': ['therapy'],
}


def _uid():
    return uuid4().hex[:8]


@pytest.fixture(autouse=True)
def bpr_ready(app):
    """Без номера заходу БПР `eligibility` відмовляє спробу ще до тесту."""
    settings = SiteSettings.get()
    settings.bpr_provider_number = '2738'
    settings.bpr_participant_counter = 0
    db.session.flush()
    return settings


@pytest.fixture
def admin(app):
    u = User.create_with_password(
        f'qrl-{_uid()}@test.com', 'password123',
        first_name='Q', last_name='A', is_admin=True, email_confirmed=True,
    )
    db.session.commit()
    yield u
    db.session.rollback()
    db.session.delete(db.session.merge(u))
    db.session.commit()


@pytest.fixture
def no_pdf(monkeypatch):
    """Справжній WeasyPrint на кожен тест зі складеним тестом -- зайва вага;
    результат сторінки від файлу сертифіката не залежить."""
    monkeypatch.setattr(certificate_service, '_write_pdf', lambda cert: '/dev/null')


def _login(client, user):
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id)


def _course():
    course = Course(
        title=f'Курс {_uid()}', slug=f'qrl-{_uid()}', is_active=True,
        event_type='course', bpr_event_number=_uid(), cpd_points=12,
    )
    db.session.add(course)
    db.session.flush()
    return course


def _instance(course):
    inst = CourseInstance(
        course_id=course.id, status='completed', event_format='offline',
        start_date=datetime.now(timezone.utc) - timedelta(days=2),
    )
    db.session.add(inst)
    db.session.flush()
    return inst


def _quiz_with_bank(course, bank=2):
    quiz = CourseQuiz(
        course_id=course.id, questions_per_attempt=bank, passing_score=1,
        max_attempts=3, shuffle_answers=False, is_active=True,
    )
    db.session.add(quiz)
    db.session.flush()
    for i in range(bank):
        db.session.add(QuizQuestion(
            quiz_id=quiz.id, text=f'Питання {i + 1}?', sort_order=i,
            answers=[{'text': 'a', 'is_correct': False},
                     {'text': 'b', 'is_correct': True},
                     {'text': 'c', 'is_correct': False},
                     {'text': 'd', 'is_correct': False}],
        ))
    db.session.flush()
    return quiz


def _registration(inst, first_name='Учасник', last_name='Тестовий'):
    user = User.create_with_password(
        f'p-{_uid()}@test.com', 'password123',
        first_name=first_name, last_name=last_name, email_confirmed=True,
    )
    db.session.flush()
    # create_with_password уже завела порожній профіль -- дозаповнюємо його,
    # інакше другий INSERT впаде на унікальному user_id.
    profile = user.medical_profile
    for field, value in FULL_PROFILE.items():
        setattr(profile, field, value)
    db.session.flush()
    reg = EventRegistration(
        user_id=user.id, instance_id=inst.id, phone='+380501234567',
        specialty='Терапія', workplace='Клініка', status='confirmed',
        payment_status='paid',
    )
    db.session.add(reg)
    db.session.flush()
    return reg


def test_participant_name_links_to_user_detail(client, admin):
    course = _course()
    inst = _instance(course)
    reg = _registration(inst)
    user_id = reg.user_id
    db.session.commit()
    _login(client, admin)
    try:
        html = client.get(f'/admin/instances/{inst.id}/quiz-results').get_data(as_text=True)
        href = f'/admin/users/{user_id}'
        assert re.search(
            rf'<a href="{re.escape(href)}">\s*{re.escape(reg.user.full_name)}', html,
        )
    finally:
        db.session.delete(db.session.merge(reg))
        db.session.delete(db.session.get(User, user_id))
        db.session.delete(db.session.merge(inst))
        db.session.delete(db.session.merge(course))
        db.session.commit()


def test_score_links_to_quiz_detail(client, admin, no_pdf):
    """Проведення з однією спробою -- бал у HTML обгорнутий у посилання на
    розбір відповідей саме цієї реєстрації."""
    course = _course()
    inst = _instance(course)
    _quiz_with_bank(course)
    reg = _registration(inst)
    user_id = reg.user_id
    db.session.commit()

    attempt = quiz_service.start_attempt(reg)
    for qid in attempt.question_ids:
        question = db.session.get(QuizQuestion, qid)
        order = attempt.ordered_answer_indexes(qid)
        quiz_service.record_answer(attempt, qid, order.index(question.correct_index))
    quiz_service.submit_attempt(attempt)
    db.session.commit()

    _login(client, admin)
    try:
        html = client.get(f'/admin/instances/{inst.id}/quiz-results').get_data(as_text=True)
        href = f'/admin/registrations/{reg.id}/quiz'
        # Всі відповіді правильні -- бал дорівнює всьому банку питань, і саме
        # це число (а не просто наявність посилання десь на сторінці) мусить
        # опинитись УСЕРЕДИНІ тегу <a>.
        score = f'{attempt.score} / {attempt.total}'
        assert re.search(
            rf'<a href="{re.escape(href)}">\s*<span[^>]*>\s*{re.escape(score)}',
            html,
        )
    finally:
        db.session.delete(db.session.merge(reg))
        db.session.delete(db.session.get(User, user_id))
        db.session.delete(db.session.merge(inst))
        db.session.delete(db.session.merge(course))
        db.session.commit()


def test_no_result_stays_plain_text(client, admin):
    course = _course()
    inst = _instance(course)
    _quiz_with_bank(course)
    reg = _registration(inst)
    user_id = reg.user_id
    db.session.commit()
    _login(client, admin)
    try:
        html = client.get(f'/admin/instances/{inst.id}/quiz-results').get_data(as_text=True)
        href = f'/admin/registrations/{reg.id}/quiz'
        assert not re.search(rf'<a href="{re.escape(href)}">', html)
    finally:
        db.session.delete(db.session.merge(reg))
        db.session.delete(db.session.get(User, user_id))
        db.session.delete(db.session.merge(inst))
        db.session.delete(db.session.merge(course))
        db.session.commit()
