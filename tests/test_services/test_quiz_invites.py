"""Лист «тестування відкрито» через 5 годин після початку заходу.

Дорого коштували б дві речі: лист, що не йде (людина не знає про тест і
лишається без сертифіката), і лист, що йде зайвий раз або учасникам давно
минулих заходів. Обидві тут закріплено.
"""
from datetime import datetime, timedelta, timezone
from itertools import count
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.course_quiz import CourseQuiz, QuizQuestion
from app.models.email_log import EmailLog
from app.models.email_settings import EmailSettings
from app.models.medical_profile import MedicalProfile
from app.models.registration import EventRegistration
from app.models.site_settings import SiteSettings
from app.models.user import User
from app.services import quiz_service
from app.services.email_service import EmailService

_event_numbers = count(6000000)

FULL_PROFILE = {
    'participant_type': 'doctor', 'middle_name': 'Іванович',
    'birth_date': datetime(1985, 3, 12).date(), 'education': '2010, НМУ',
    'workplace': 'Клініка', 'position': 'лікар', 'specializations': ['therapy'],
}


@pytest.fixture(autouse=True)
def bpr_ready(app):
    settings = SiteSettings.get()
    settings.bpr_provider_number = '2738'
    db.session.flush()
    return settings


@pytest.fixture
def captured(monkeypatch):
    """Перехопити відправку: хто отримав лист і в якому стані."""
    calls = []

    def fake(registration, state=None):
        calls.append((registration.id, state.status if state else None))
        return object()

    monkeypatch.setattr(EmailService, 'send_quiz_invite', staticmethod(fake))
    return calls


def _reg(started_hours_ago=6, profile=True, paid=True, bank=10):
    course = Course(
        title=f'Курс {uuid4().hex[:4]}', slug=f'qi-{uuid4().hex[:6]}',
        is_active=True, event_type='course',
        cpd_points_online=12, cpd_points_offline=12,
        bpr_event_number=str(next(_event_numbers)),
    )
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(
        course_id=course.id, status='active', event_format='offline',
        start_date=datetime.now(timezone.utc) - timedelta(hours=started_hours_ago),
    )
    db.session.add(inst)
    db.session.flush()

    quiz = CourseQuiz(course_id=course.id, questions_per_attempt=10,
                      passing_score=8, is_active=True, shuffle_answers=False)
    db.session.add(quiz)
    db.session.flush()
    for i in range(bank):
        db.session.add(QuizQuestion(
            quiz_id=quiz.id, text=f'Питання {i + 1}?', sort_order=i,
            answers=[{'text': f'Варіант {j + 1}', 'is_correct': j == 0}
                     for j in range(4)]))

    user = User.create_with_password(
        f'qi-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='Іван', last_name='Тестовий', email_confirmed=True)
    db.session.flush()
    if profile:
        prof = user.medical_profile or MedicalProfile(user_id=user.id)
        for field, value in FULL_PROFILE.items():
            setattr(prof, field, value)
        user.medical_profile = prof
        db.session.add(prof)

    reg = EventRegistration(
        user_id=user.id, instance_id=inst.id, phone='+380501234567',
        specialty='Терапія', workplace='Клініка', status='confirmed',
        payment_status='paid' if paid else 'unpaid')
    db.session.add(reg)
    db.session.flush()
    return reg


def _invited(calls, reg):
    return [status for reg_id, status in calls if reg_id == reg.id]


# ---- коли йде лист ---------------------------------------------------------

def test_invites_five_hours_after_start(app, captured):
    reg = _reg(started_hours_ago=6)
    quiz_service.send_quiz_invites()

    assert _invited(captured, reg) == [quiz_service.AVAILABLE]
    assert reg.quiz_invite_sent_at is not None


def test_no_invite_before_five_hours(app, captured):
    reg = _reg(started_hours_ago=4)
    quiz_service.send_quiz_invites()

    assert _invited(captured, reg) == []
    assert reg.quiz_invite_sent_at is None


def test_long_past_event_is_not_invited(app, captured):
    """Запобіжник деплою: минулі заходи не отримують запізнілих листів."""
    reg = _reg(started_hours_ago=24 * 8)
    quiz_service.send_quiz_invites()

    assert _invited(captured, reg) == []


def test_incomplete_profile_is_invited_too(app, captured):
    """Анкета й тест -- обидві умови сертифіката; лист веде до першої."""
    reg = _reg(profile=False)
    quiz_service.send_quiz_invites()

    assert _invited(captured, reg) == [quiz_service.PROFILE_INCOMPLETE]


def test_unpaid_registration_is_not_invited(app, captured):
    reg = _reg(paid=False)
    quiz_service.send_quiz_invites()

    assert _invited(captured, reg) == []
    assert reg.quiz_invite_sent_at is None


def test_quiz_not_ready_waits_for_next_run(app, captured):
    """Недостатній банк -- не позначаємо: адмін допише, і лист тоді піде."""
    reg = _reg(bank=3)
    quiz_service.send_quiz_invites()

    assert _invited(captured, reg) == []
    assert reg.quiz_invite_sent_at is None


def test_exhausted_attempts_are_marked_without_email(app, captured):
    reg = _reg()
    reg.quiz_extra_attempts = -3
    db.session.flush()
    quiz_service.send_quiz_invites()

    assert _invited(captured, reg) == []
    assert reg.quiz_invite_sent_at is not None


def test_second_run_does_not_resend(app, captured):
    reg = _reg()
    quiz_service.send_quiz_invites()
    quiz_service.send_quiz_invites()

    assert len(_invited(captured, reg)) == 1


def test_unsent_letter_is_retried(app, monkeypatch):
    reg = _reg()
    monkeypatch.setattr(EmailService, 'send_quiz_invite',
                        staticmethod(lambda registration, state=None: None))
    quiz_service.send_quiz_invites()

    assert reg.quiz_invite_sent_at is None


def test_quiz_trigger_ignores_unsubscribe(app):
    """Не розсилка: без тесту й анкети сертифіката не буде."""
    assert EmailLog.is_valid_trigger('quiz')
    assert not EmailLog.is_optional_trigger('quiz')


# ---- сам лист ---------------------------------------------------------------

@pytest.fixture
def email_enabled(app, monkeypatch):
    settings = EmailSettings.get()
    settings.is_enabled = True
    settings.smtp_server = 'localhost'
    settings.smtp_port = 25
    settings.smtp_username = 'noreply@test.local'
    settings.default_sender = 'noreply@test.local'
    db.session.commit()
    monkeypatch.setattr('app.services.email_service.Thread',
                        lambda *a, **kw: type('T', (), {
                            'start': lambda self: None,
                            'daemon': True,
                        })())
    yield
    settings.is_enabled = False
    db.session.commit()


def test_letter_leads_to_the_quiz(app, email_enabled):
    reg = _reg()
    log = EmailService.send_quiz_invite(reg)

    assert log is not None
    assert log.trigger == 'quiz'
    assert 'Тестування відкрито' in log.subject
    assert f'/quiz/{reg.id}' in (log.html_body or '')
    assert 'Пройти тестування' in (log.html_body or '')


def test_letter_sends_incomplete_profile_to_the_form_first(app, email_enabled):
    reg = _reg(profile=False)
    body = EmailService.send_quiz_invite(reg).html_body or ''

    assert '/auth/account/certificate-data' in body
    assert 'Заповнити анкету' in body
    assert f'/quiz/{reg.id}' in body


def test_letter_is_skipped_without_quiz(app, email_enabled):
    reg = _reg()
    CourseQuiz.query.filter_by(course_id=reg.instance.course_id).one().is_active = False
    db.session.flush()

    assert EmailService.send_quiz_invite(reg) is None
