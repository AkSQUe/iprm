"""Анкета «Дані для сертифіката»: редагування власного ПІБ учасником.

Прізвище й ім'я живуть у `User`, по батькові -- у `MedicalProfile`, тож до
цього ПІБ був розрізаний: «по батькові» учасник міняв сам, а прізвище й ім'я
-- лише через адміна. Тести тримають усі три поля в одній формі й стежать,
щоб зміна ПІБ не робила вигляд, ніби переоформлює вже видані сертифікати.
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.certificate import Certificate
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.registration import EventRegistration
from app.models.user import User

URL = '/auth/account/certificate-data'
NOTICE = 'id="certdata-name-notice"'


def _login(client, user):
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id)


def _payload(**overrides):
    """Валідний POST анкети. Форма вимагає всі поля -- часткові дані
    завалюють валідацію ще до того, як черга дійде до ПІБ."""
    data = {
        'last_name': 'Новий',
        'first_name': 'Петро',
        'user_type': 'doctor',
        'middle_name': 'Іванович',
        'birth_date': '1985-04-17',
        'education': '2010, НМУ ім. О.О. Богомольця',
        'workplace': 'Клініка',
        'position': 'лікар-ординатор',
        'specializations': ['therapy'],
    }
    data.update(overrides)
    return data


@pytest.fixture
def user(app):
    user = User.create_with_password(
        f'cn-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='Іван', last_name='Тестовий', email_confirmed=True)
    db.session.flush()
    return user


@pytest.fixture
def registration(user):
    course = Course(title=f'Курс {uuid4().hex[:4]}', slug=f'cn-{uuid4().hex[:6]}',
                    is_active=True, event_type='course')
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(
        course_id=course.id, status='completed', event_format='offline',
        start_date=datetime.now(timezone.utc) - timedelta(days=1))
    db.session.add(inst)
    db.session.flush()
    reg = EventRegistration(
        user_id=user.id, instance_id=inst.id, phone='+380501234567',
        specialty='Терапія', workplace='Клініка', status='confirmed',
        payment_status='paid')
    db.session.add(reg)
    db.session.flush()
    return reg


def _issue_certificate(user, registration, revoked=False):
    cert = Certificate(
        registration_id=registration.id, user_id=user.id,
        number=f'CN-{uuid4().hex[:8]}', recipient_name='Тестовий Іван Іванович',
        event_title='Курс', pdf_path='certificates/x.pdf', revoked=revoked)
    db.session.add(cert)
    db.session.flush()
    return cert


# ---- поля ПІБ у формі --------------------------------------------------------

def test_form_prefills_current_name(client, user):
    _login(client, user)
    html = client.get(URL).get_data(as_text=True)
    assert 'value="Тестовий"' in html
    assert 'value="Іван"' in html


def test_saves_new_name(client, user):
    _login(client, user)
    resp = client.post(URL, data=_payload(), follow_redirects=False)
    assert resp.status_code == 302
    saved = db.session.get(User, user.id)
    assert (saved.last_name, saved.first_name) == ('Новий', 'Петро')


def test_trims_whitespace_around_name(client, user):
    _login(client, user)
    client.post(URL, data=_payload(last_name='  Новий  ', first_name='  Петро  '))
    saved = db.session.get(User, user.id)
    assert (saved.last_name, saved.first_name) == ('Новий', 'Петро')


def test_rejects_empty_last_name(client, user):
    _login(client, user)
    resp = client.post(URL, data=_payload(last_name=''))
    assert resp.status_code == 200
    saved = db.session.get(User, user.id)
    assert saved.last_name == 'Тестовий'


def test_rejects_empty_first_name(client, user):
    _login(client, user)
    resp = client.post(URL, data=_payload(first_name=''))
    assert resp.status_code == 200
    saved = db.session.get(User, user.id)
    assert saved.first_name == 'Іван'


# ---- нотис про вже видані сертифікати ---------------------------------------

def test_no_notice_without_certificates(client, user):
    _login(client, user)
    assert NOTICE not in client.get(URL).get_data(as_text=True)


def test_notice_when_certificate_issued(client, user, registration):
    _issue_certificate(user, registration)
    _login(client, user)
    assert NOTICE in client.get(URL).get_data(as_text=True)


def test_no_notice_when_certificate_revoked(client, user, registration):
    _issue_certificate(user, registration, revoked=True)
    _login(client, user)
    assert NOTICE not in client.get(URL).get_data(as_text=True)
