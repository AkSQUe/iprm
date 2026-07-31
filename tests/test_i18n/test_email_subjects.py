"""Тема листа мовою отримувача.

Тіло листа локалізувалось через force_locale, а тема була готовим
f-рядком українською: російськомовний учасник бачив у списку пошти
українську тему і російський лист. Назва курсу в адаптері `event` теж
бралася канонічна, тож була українською і в темі, і в тілі.
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.email_settings import EmailSettings
from app.models.registration import EventRegistration
from app.models.user import User
from app.services.email_service import EmailService


@pytest.fixture(autouse=True)
def _email_enabled(app):
    """Лист має дійти до формування теми, а не відсіктись на 'disabled'."""
    settings = EmailSettings.get()
    settings.is_enabled = True
    settings.smtp_server = 'localhost'
    settings.smtp_port = 25
    settings.smtp_username = 'noreply@test.local'
    settings.default_sender = 'noreply@test.local'
    db.session.commit()
    yield
    settings.is_enabled = False
    db.session.commit()


def _registration(lang):
    course = Course(title='Практикум з плазмотерапії',
                    slug=f'em-{uuid4().hex[:6]}', is_active=True)
    course.set_translation('ru', 'title', 'Практикум по плазмотерапии')
    course.set_translation('en', 'title', 'Plasma Therapy Workshop')
    db.session.add(course)
    db.session.flush()

    instance = CourseInstance(
        course_id=course.id, status='published', event_format='online',
        start_date=datetime.now(timezone.utc) + timedelta(days=10),
    )
    db.session.add(instance)

    user = User.create_with_password(
        f'u-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='Тест', last_name='Тестовий', email_confirmed=True,
    )
    user.preferred_language = lang
    db.session.flush()

    reg = EventRegistration(
        user_id=user.id, instance_id=instance.id, phone='+380501112233',
        specialty='Дерматолог', workplace='Клініка', status='confirmed',
    )
    db.session.add(reg)
    db.session.commit()
    return reg


def _sent_subject(monkeypatch, send):
    """Перехопити тему, не надсилаючи листа."""
    captured = {}
    monkeypatch.setattr(EmailService, '_send_async',
                        staticmethod(lambda *a, **kw: None), raising=False)
    monkeypatch.setattr('app.services.email_service.Thread',
                        lambda *a, **kw: type('T', (), {
                            'start': lambda self: None,
                            'daemon': True,
                        })())
    log = send()
    if log is not None:
        captured['subject'] = log.subject
        captured['body'] = log.html_body or ''
    return captured


def test_subject_is_localized_to_recipient(client, monkeypatch):
    reg_ru = _registration('ru')
    out = _sent_subject(
        monkeypatch,
        lambda: EmailService.send_registration_confirmation(reg_ru))
    assert out, 'лист не сформувався'
    assert 'Практикум по плазмотерапии' in out['subject']
    assert 'Практикум з плазмотерапії' not in out['subject']


def test_subject_stays_ukrainian_for_uk_recipient(client, monkeypatch):
    reg = _registration('uk')
    out = _sent_subject(
        monkeypatch,
        lambda: EmailService.send_registration_confirmation(reg))
    assert 'Практикум з плазмотерапії' in out['subject']


def test_course_title_in_body_follows_recipient_language(client, monkeypatch):
    """Адаптер event віддавав канонічну назву -- у тілі вона теж була укр."""
    reg_en = _registration('en')
    out = _sent_subject(
        monkeypatch,
        lambda: EmailService.send_registration_confirmation(reg_en))
    assert 'Plasma Therapy Workshop' in out['body']
    assert 'Практикум з плазмотерапії' not in out['body']


def test_event_shape_has_no_stale_title_attribute(client):
    """Регресія: title/subtitle мають бути властивостями, інакше вони
    обчислюються поза force_locale і локаль отримувача не діє."""
    reg = _registration('ru')
    shape = EmailService._event_from_registration(reg)
    assert isinstance(type(shape).title, property)
    assert isinstance(type(shape).subtitle, property)


@pytest.mark.parametrize('sender_name', [
    'send_registration_confirmation',
    'send_completion_link',
    'send_payment_confirmation',
    'send_status_change',
    'send_certdata_reminder',
])
def test_event_based_senders_do_not_raise(client, monkeypatch, sender_name):
    """Теми стали callable; помилка всередині лямбди зруйнувала б відправку.
    Ці відправники раніше не викликались у тестах узагалі."""
    reg = _registration('ru')
    sender = getattr(EmailService, sender_name)
    kwargs = {}
    if sender_name == 'send_completion_link':
        kwargs = {'complete_url': 'https://example.com/c'}
    elif sender_name == 'send_status_change':
        kwargs = {'old_status': 'pending', 'new_status': 'confirmed'}
    _sent_subject(monkeypatch, lambda: sender(reg, **kwargs))
