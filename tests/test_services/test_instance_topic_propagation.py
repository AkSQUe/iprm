"""Тема проведення доїжджає туди, де захід називають: документи, реєстрації,
партнерський канал.

Сенс поля саме в цьому. Колонка, яку видно лише в картці адмінки, нікому не
потрібна: тему заводять, щоб вона стояла в сертифікаті й у поданні до БПР.
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.registration import EventRegistration
from app.models.user import User
from app.services import certificate_service


TOPIC = 'PRP у практиці ортопеда-травматолога'


def _uid():
    return uuid4().hex[:8]


@pytest.fixture
def registration(app):
    user = User(email=f'topic-{_uid()}@test.com', password='pw-' + _uid(),
                first_name='Іван', last_name='Учасник')
    course = Course(title='Базовий курс', slug=f'tpr-{_uid()}',
                    short_description='d', is_active=True, base_price=100,
                    event_type='seminar')
    db.session.add_all([user, course])
    db.session.flush()
    inst = CourseInstance(
        course_id=course.id, status='published', event_format='offline',
        topic=TOPIC, location='м. Харків',
        start_date=datetime.now(timezone.utc) - timedelta(days=3),
    )
    db.session.add(inst)
    db.session.flush()
    reg = EventRegistration(
        user_id=user.id, instance_id=inst.id, status='confirmed',
        phone='+380501112233', specialty='ортопед', workplace='КНП',
        cpd_points_awarded=10,
    )
    db.session.add(reg)
    db.session.flush()
    return reg


def test_certificate_snapshot_takes_topic(registration):
    title = certificate_service._event_snapshot(registration)[0]
    assert title == TOPIC


def test_certificate_snapshot_stays_ukrainian(registration):
    """Знімок не залежить від локалі того, хто спричинив видачу."""
    registration.instance.set_translation('ru', 'topic', 'Тема по-русски')
    db.session.flush()
    assert certificate_service._event_snapshot(registration)[0] == TOPIC


def test_certificate_falls_back_to_course_title(registration):
    registration.instance.topic = None
    db.session.flush()
    assert certificate_service._event_snapshot(registration)[0] == 'Базовий курс'


def test_registration_target_title_takes_topic(registration):
    assert registration.target_title == TOPIC


def test_outgoing_webhook_names_event_by_topic(registration):
    from app.services import partner_events

    payload = partner_events._registration_payload(registration)
    assert payload['event_title'] == TOPIC


def test_partner_api_card_names_event_by_topic(registration, client):
    from app.models.site_settings import SiteSettings

    settings = SiteSettings.get()
    settings.partner_integration_enabled = True
    settings.partner_api_key = 'test-topic-api-key-12345678901234567890'
    registration.instance.start_date = datetime.now(timezone.utc) + timedelta(days=30)
    db.session.commit()
    try:
        data = client.get(
            '/api/v1/events?per_page=100',
            headers={'X-API-Key': settings.partner_api_key},
        ).get_json()
        card = next(i for i in data['items']
                    if i['slug'] == registration.instance.course.slug)
        assert card['title'] == TOPIC
    finally:
        settings.partner_integration_enabled = False
        settings.partner_api_key = ''
        db.session.commit()
