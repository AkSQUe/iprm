"""Анкета «Дані для сертифіката»: редагування власного ПІБ учасником.

Прізвище й ім'я живуть у `User`, по батькові -- у `MedicalProfile`, тож до
цього ПІБ був розрізаний: «по батькові» учасник міняв сам, а прізвище й ім'я
-- лише через адміна. Тести тримають усі три поля в одній формі й стежать,
щоб зміна ПІБ не робила вигляд, ніби переоформлює вже видані сертифікати.
"""
import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.certificate import Certificate
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.medical_profile import MedicalProfile
from app.models.registration import EventRegistration
from app.models.user import User
from app.services.email_service import EmailService

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


def _set_middle_name(user, value):
    profile = user.medical_profile
    if profile is None:
        profile = MedicalProfile(user_id=user.id)
        db.session.add(profile)
        user.medical_profile = profile
    profile.middle_name = value
    db.session.flush()
    return profile


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


# ---- канонічна нормалізація ПІБ ---------------------------------------------
#
# Усі інші шляхи запису (адмінка, форма за токеном, xlsx) женуть ПІБ через
# `normalize_name`. Якби анкета лишилась винятком, "IВАНОВ петро" ліг би в БД
# і звідти -- у `Certificate.recipient_name`, тобто на друкований сертифікат.

@pytest.mark.parametrize('given, expected', [
    (('IВАНОВ', 'ПЕТРО'), ('Iванов', 'Петро')),        # CAPS LOCK
    (('iванов', 'петро'), ('Iванов', 'Петро')),        # усе з малої
    (('Iванов  ', '  Петро'), ('Iванов', 'Петро')),    # крайні пробіли
    (('Нечипоренко-Iванов', 'петро'), ('Нечипоренко-Iванов', 'Петро')),
])
def test_normalizes_name_on_save(client, user, given, expected):
    _login(client, user)
    client.post(URL, data=_payload(last_name=given[0], first_name=given[1]))
    saved = db.session.get(User, user.id)
    assert (saved.last_name, saved.first_name) == expected


def test_collapses_inner_whitespace(client, user):
    _login(client, user)
    client.post(URL, data=_payload(last_name='Iванов   Другий'))
    assert db.session.get(User, user.id).last_name == 'Iванов Другий'


def test_apostrophe_keeps_lowercase_after_it(client, user):
    """Мар'яна, а не Мар'Яна -- апостроф не є межею слова."""
    _login(client, user)
    client.post(URL, data=_payload(first_name="мар'яна"))
    assert db.session.get(User, user.id).first_name == "Мар'яна"


def test_normalizes_middle_name_too(client, user):
    _login(client, user)
    client.post(URL, data=_payload(middle_name='IВАНОВИЧ'))
    saved = db.session.get(User, user.id)
    assert saved.medical_profile.middle_name == 'Iванович'


# ---- мінімальна довжина (як при реєстрації) ---------------------------------

@pytest.mark.parametrize('field', ['last_name', 'first_name'])
def test_rejects_single_letter_name(client, user, field):
    """Реєстрація вимагає від 2 символів -- анкета не має бути слабшою."""
    _login(client, user)
    resp = client.post(URL, data=_payload(**{field: 'X'}))
    assert resp.status_code == 200
    saved = db.session.get(User, user.id)
    assert (saved.last_name, saved.first_name) == ('Тестовий', 'Іван')


# ---- аудит зміни ПІБ ---------------------------------------------------------
#
# ПІБ -- identity-дані, що друкуються на сертифікаті. Адмінські правки учасника
# лишають слід в `audit_logger`; самостійна зміна має лишати такий самий.

def test_name_change_is_audited(client, user, caplog):
    _login(client, user)
    with caplog.at_level(logging.INFO, logger='audit'):
        client.post(URL, data=_payload(last_name='Новий', first_name='Петро'))
    records = [r.getMessage() for r in caplog.records if r.name == 'audit']
    assert any('Тестовий Іван' in m and 'Новий Петро' in m for m in records), records


def test_no_audit_when_name_unchanged(client, user, caplog):
    """По батькові -- теж частина ПІБ, тож "без змін" означає всі три поля."""
    _set_middle_name(user, 'Іванович')
    _login(client, user)
    with caplog.at_level(logging.INFO, logger='audit'):
        client.post(URL, data=_payload(
            last_name='Тестовий', first_name='Іван', middle_name='Іванович'))
    assert not [r for r in caplog.records if r.name == 'audit']


def test_audit_fires_when_only_middle_name_changes(client, user, caplog):
    _set_middle_name(user, 'Іванович')
    _login(client, user)
    with caplog.at_level(logging.INFO, logger='audit'):
        client.post(URL, data=_payload(
            last_name='Тестовий', first_name='Іван', middle_name='Петрович'))
    records = [r.getMessage() for r in caplog.records if r.name == 'audit']
    assert any('Петрович' in m for m in records), records


def test_notice_precedes_name_fields(client, user, registration):
    """Попередження має стояти ДО полів, яких стосується, а не після них."""
    _issue_certificate(user, registration)
    _login(client, user)
    html = client.get(URL).get_data(as_text=True)
    assert html.index(NOTICE) < html.index('id="last_name"')


def test_name_fields_reference_notice(client, user, registration):
    _issue_certificate(user, registration)
    _login(client, user)
    html = client.get(URL).get_data(as_text=True)
    assert html.count('aria-describedby="certdata-name-notice"') == 3


def test_no_dangling_aria_without_notice(client, user):
    """Без нотиса атрибут вказував би в нікуди -- це помилка доступності."""
    _login(client, user)
    assert 'aria-describedby' not in client.get(URL).get_data(as_text=True)


# ---- лист про зміну ПІБ ------------------------------------------------------
#
# ПІБ -- identity-дані. Власник акаунта має дізнатись про зміну навіть тоді,
# коли зробив її не він (той самий принцип, що й для зміни email).

@pytest.fixture
def name_emails(monkeypatch):
    calls = []
    monkeypatch.setattr(
        EmailService, 'send_name_changed',
        staticmethod(lambda *a, **k: calls.append((a, k))))
    return calls


def test_sends_email_on_name_change(client, user, name_emails):
    _login(client, user)
    client.post(URL, data=_payload(last_name='Новий', first_name='Петро'))
    assert len(name_emails) == 1
    args = name_emails[0][0]
    assert 'Тестовий Іван' in args
    assert 'Новий Петро Іванович' in args


def test_no_email_when_name_unchanged(client, user, name_emails):
    _set_middle_name(user, 'Іванович')
    _login(client, user)
    client.post(URL, data=_payload(
        last_name='Тестовий', first_name='Іван', middle_name='Іванович'))
    assert name_emails == []


def test_email_failure_does_not_break_save(client, user, monkeypatch):
    """Лист -- побічний ефект: SMTP не має відкочувати збережений ПІБ."""
    def boom(*a, **k):
        raise RuntimeError('smtp down')
    monkeypatch.setattr(EmailService, 'send_name_changed', staticmethod(boom))
    _login(client, user)
    resp = client.post(URL, data=_payload(last_name='Новий', first_name='Петро'))
    assert resp.status_code == 302
    assert db.session.get(User, user.id).last_name == 'Новий'


# ---- заявка на переоформлення сертифіката -----------------------------------

REISSUE_URL = '/auth/account/certificates/reissue-request'


@pytest.fixture
def reissue_emails(monkeypatch):
    calls = []
    monkeypatch.setattr(
        EmailService, 'send_certificate_reissue_request',
        staticmethod(lambda *a, **k: calls.append((a, k))))
    return calls


def test_reissue_request_notifies_admins(client, user, registration, reissue_emails):
    _issue_certificate(user, registration)
    _login(client, user)
    resp = client.post(REISSUE_URL)
    assert resp.status_code == 302
    assert len(reissue_emails) == 1


def test_reissue_request_rejected_without_certificates(client, user, reissue_emails):
    """Немає що переоформлювати -- немає й заявки."""
    _login(client, user)
    resp = client.post(REISSUE_URL)
    assert resp.status_code == 404
    assert reissue_emails == []


def test_reissue_request_requires_login(client, reissue_emails):
    resp = client.post(REISSUE_URL)
    assert resp.status_code in (302, 401)
    assert 'login' in resp.headers.get('Location', '')
    assert reissue_emails == []


def test_notice_offers_a_way_to_ask(client, user, registration):
    """Нотис каже "зверніться до нас" -- має бути чим."""
    _issue_certificate(user, registration)
    _login(client, user)
    html = client.get(URL).get_data(as_text=True)
    assert REISSUE_URL in html
