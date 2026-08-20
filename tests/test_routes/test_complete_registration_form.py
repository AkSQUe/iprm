"""Публічна форма завершення реєстрації за токеном: поля ПІБ.

Ця форма й анкета в кабінеті беруть прізвище та ім'я з одного міксина
(`UserNameFieldsMixin`), і жоден тест раніше не відкривав саме цей маршрут --
покриті були тільки /pay і /set-password. Тобто зміна спільних полів могла
зламати токен-флоу, а зелений прогін цього не показав би.
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.registration import EventRegistration
from app.models.user import User


@pytest.fixture
def reg(app):
    """Реєстрація з активним токеном завершення."""
    user = User.create_with_password(
        f'cr-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='Іван', last_name='Тестовий')
    db.session.flush()
    course = Course(title=f'Курс {uuid4().hex[:4]}', slug=f'cr-{uuid4().hex[:6]}',
                    is_active=True, event_type='course')
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(
        course_id=course.id, status='published', event_format='online',
        price=0, start_date=datetime.now(timezone.utc) + timedelta(days=30))
    db.session.add(inst)
    db.session.flush()
    reg = EventRegistration(
        user_id=user.id, instance_id=inst.id, phone='+380501234567',
        specialty='Терапія', workplace='Клініка',
        status='pending', payment_status='unpaid')
    reg.issue_completion_token()
    db.session.add(reg)
    db.session.flush()
    return reg


def _payload(**overrides):
    data = {
        'last_name': 'Новий',
        'first_name': 'Петро',
        'middle_name': 'Іванович',
        'email': f'cr-new-{uuid4().hex[:6]}@test.com',
        'phone': '+380671112233',
        'user_type': 'doctor',
        'birth_date': '1985-04-17',
        'education': '2010, НМУ ім. О.О. Богомольця',
        'workplace': 'Клініка',
        'position': 'лікар-ординатор',
        'specializations': ['therapy'],
        'consent_data': 'y',
    }
    data.update(overrides)
    return data


def _url(reg):
    return f'/registration/complete/{reg.completion_token}'


def test_form_renders_name_fields(client, reg):
    html = client.get(_url(reg)).get_data(as_text=True)
    assert 'id="last_name"' in html
    assert 'id="first_name"' in html
    assert 'value="Тестовий"' in html


def test_completion_saves_name(client, reg):
    user_id = reg.user_id
    resp = client.post(_url(reg), data=_payload())
    assert resp.status_code == 302
    saved = db.session.get(User, user_id)
    assert (saved.last_name, saved.first_name) == ('Новий', 'Петро')


def test_completion_normalizes_name(client, reg):
    user_id = reg.user_id
    client.post(_url(reg), data=_payload(last_name='IВАНОВ', first_name='петро'))
    saved = db.session.get(User, user_id)
    assert (saved.last_name, saved.first_name) == ('Iванов', 'Петро')


@pytest.mark.parametrize('field', ['last_name', 'first_name'])
def test_completion_rejects_empty_name(client, reg, field):
    resp = client.post(_url(reg), data=_payload(**{field: ''}))
    assert resp.status_code == 200
    assert reg.completion_token_used_at is None


@pytest.mark.parametrize('field', ['last_name', 'first_name'])
def test_completion_rejects_single_letter_name(client, reg, field):
    resp = client.post(_url(reg), data=_payload(**{field: 'X'}))
    assert resp.status_code == 200
    assert reg.completion_token_used_at is None
